from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import create_chrome_driver, find_chromedriver
from filler import AnswerFiller, accept_pending_alert, action_alert_succeeded, load_answers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把本地答案表填入国科大慕课测验页面（默认暂存，可显式提交）")
    parser.add_argument("--answers", required=True, help="答案 JSON 文件")
    parser.add_argument("--set", dest="answer_set", help="答案文件中的答案组名称，例如 1.1章节测验")
    parser.add_argument(
        "--search",
        action="store_true",
        help="遍历页面按题干/选项文字搜索答案；不使用题号和 chapterId",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="从当前章节测验开始，暂存成功后自动进入下一测验",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="填写后点击提交并确认；默认只暂时保存",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=2.0,
        help="自动切换章节前的等待秒数，默认 2 秒",
    )
    parser.add_argument("--url", default="http://mooc.ucas.edu.cn/portal", help="打开的网址")
    parser.add_argument("--profile-dir", help="可选的独立 Chrome 用户数据目录，用于保留登录状态")
    parser.add_argument("--driver", help="可选的 chromedriver.exe 路径；默认自动查找本地缓存")
    parser.add_argument("--headless", action="store_true", help="无界面运行，仅用于诊断和测试")
    parser.add_argument("--wait", type=int, default=60, help="等待测验题目加载的秒数，默认 60")
    return parser.parse_args()


def load_chapter_sequence(path: str | Path) -> list[tuple[str, str]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    answer_sets = payload.get("answer_sets", {}) if isinstance(payload, dict) else {}
    chapter_sets = payload.get("chapter_sets", {}) if isinstance(payload, dict) else {}
    if not isinstance(answer_sets, dict) or not isinstance(chapter_sets, dict):
        raise ValueError("自动翻页需要 answer_sets 和 chapter_sets 对象")
    sequence = [
        (str(chapter_id), str(set_name))
        for chapter_id, set_name in chapter_sets.items()
        if set_name in answer_sets
    ]
    if not sequence:
        raise ValueError("chapter_sets 中没有可用的章节答案映射")
    return sequence


def chapter_id_from_url(url: str) -> str | None:
    return dict(parse_qsl(urlparse(url).query)).get("chapterId")


def replace_chapter_id(url: str, chapter_id: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["chapterId"] = str(chapter_id)
    return urlunparse(parsed._replace(query=urlencode(query)))


def print_report(report, answers, show_unused: bool = True) -> None:
    print(f"\n扫描 {report.frame_count} 个页面/框架，发现 {report.question_count} 道题。")
    print(f"成功填写: {report.filled_count}")
    for item in report.filled:
        source = f" [{item['answerSet']}]" if item.get("answerSet") else ""
        print(f"  [已填]{source} {item.get('question') or '未命名题目'} - {item.get('detail', '')}")

    if report.problems:
        print(f"需要人工检查: {len(report.problems)}")
        for item in report.problems:
            print(f"  [{item.get('status')}] {item.get('question') or item.get('frame')} - {item.get('detail', '')}")

    unused = report.unused_answers(answers)
    if show_unused and unused:
        print(f"未匹配到页面的答案: {len(unused)}")
        for item in unused:
            print(f"  [未匹配] {item.get('question') or item.get('id') or item.get('index')}")

    if report.action_mode == "submit":
        status = "已提交" if report.submitted else "未确认提交成功"
    else:
        status = "已暂时保存" if report.draft_saved else "未暂时保存"
    print(f"{status}: {report.action_detail}")


def fill_after_page_is_ready(
    driver,
    answers,
    timeout: int,
    search_only: bool = False,
    submit: bool = False,
):
    deadline = time.monotonic() + max(timeout, 0)
    attempt = 0
    while True:
        attempt += 1
        report = AnswerFiller(
            driver,
            answers,
            search_only=search_only,
            submit=submit,
        ).fill_current_page()
        if report.question_count:
            return report
        if time.monotonic() >= deadline:
            return report
        if attempt == 1 or attempt % 5 == 0:
            remaining = max(0, int(deadline - time.monotonic()))
            print(f"尚未发现题目，继续等待页面和 iframe 加载（剩余约 {remaining} 秒）...")
        time.sleep(1)


def process_current_page(driver, args, require_complete: bool = False) -> int:
    current_url = driver.current_url
    print(f"\n当前页面: {current_url}")
    try:
        answers = load_answers(
            args.answers,
            args.answer_set,
            current_url,
            search_all=args.search,
        )
    except (OSError, ValueError) as exc:
        print(f"答案文件错误: {exc}", file=sys.stderr)
        return 2

    if require_complete or args.submit:
        status = AnswerFiller(driver, answers).current_submission_status()
        if status.get("completed"):
            print(f"已跳过提交完成的章节：{status.get('detail', '页面显示已完成')}")
            return 0

    report = fill_after_page_is_ready(
        driver,
        answers,
        args.wait,
        search_only=args.search,
        submit=args.submit,
    )
    print_report(report, answers, show_unused=not args.search)
    if report.question_count == 0:
        print("\n没有发现题目。请确认打开的是具体章节测验，而不是课程目录或登录页。")
        return 4
    if report.filled_count == 0:
        print("\n发现了题目，但没有答案匹配成功；请查看上面的未匹配/歧义报告。")
        return 5
    if require_complete and report.filled_count != report.question_count:
        print("\n自动翻页已停止：本页存在未匹配题目，请检查后再继续。")
        return 6
    if require_complete and not report.action_completed:
        action = "提交" if args.submit else "暂时保存"
        print(f"\n自动翻页已停止：本页未确认{action}成功。")
        return 7

    if args.submit:
        print("\n本页答案已提交。")
    else:
        print("\n程序只会选择“暂时保存”，不会点击提交。请在浏览器中逐题检查。")
    return 0


def process_pages_automatically(driver, args) -> int:
    try:
        sequence = load_chapter_sequence(args.answers)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"答案文件错误: {exc}", file=sys.stderr)
        return 2

    current_id = chapter_id_from_url(driver.current_url)
    chapter_ids = [chapter_id for chapter_id, _ in sequence]
    if current_id not in chapter_ids:
        print("自动翻页需要先进入 answers.json 已映射的章节测验页面。", file=sys.stderr)
        return 8

    start = chapter_ids.index(current_id)
    total = len(sequence) - start
    for offset, (chapter_id, set_name) in enumerate(sequence[start:], start=1):
        if chapter_id_from_url(driver.current_url) != chapter_id:
            driver.get(replace_chapter_id(driver.current_url, chapter_id))
        print(f"\n===== 自动填写 {offset}/{total}: {set_name} (chapterId={chapter_id}) =====")
        result = process_current_page(driver, args, require_complete=True)
        if result != 0:
            return result
        alert_text = accept_pending_alert(driver, timeout=3)
        if alert_text:
            print(f"保存提示：{alert_text}")
            if not action_alert_succeeded(alert_text, args.submit):
                action = "提交" if args.submit else "保存"
                print(f"自动翻页已停止：{action}后出现了非成功提示。")
                return 7
        if offset < total:
            time.sleep(max(args.page_delay, 0))
            next_id, next_name = sequence[start + offset]
            print(f"准备进入下一测验：{next_name}")
            driver.get(replace_chapter_id(driver.current_url, next_id))

    print("\n已处理答案表中从当前章节开始的全部测验，并逐章暂时保存。")
    return 0


def main() -> int:
    args = parse_args()
    if args.auto and args.answer_set:
        print("--auto 会按 chapter_sets 自动选择答案组，不能同时使用 --set。", file=sys.stderr)
        return 2
    if args.auto and args.search:
        print("--auto 依赖 chapter_sets 保证章节对应，不能同时使用 --search。", file=sys.stderr)
        return 2

    # Selenium 在部分 Python 3.14/Windows 组合上会把服务清理异常写入日志。
    # 浏览器由本程序显式关闭；压低该日志可避免退出时出现误导性 traceback。
    logging.getLogger("selenium.webdriver.common.service").setLevel(logging.CRITICAL)

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
    if args.profile_dir:
        profile_path = Path(args.profile_dir).expanduser().resolve()
        profile_path.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_path}")

    driver = None
    try:
        resolved_driver = find_chromedriver(args.driver)
        if resolved_driver:
            print(f"使用 ChromeDriver: {resolved_driver}")
        driver = create_chrome_driver(options, args.driver)
    except (FileNotFoundError, WebDriverException) as exc:
        print(f"Chrome 启动失败: {exc}", file=sys.stderr)
        print("请确认 Chrome 已安装；也可以使用 --driver 指定 chromedriver.exe。", file=sys.stderr)
        return 3
    try:
        driver.get(args.url)
        if args.headless:
            return process_current_page(driver, args)

        print("请在浏览器中登录并进入要作答的测验页。")
        if args.auto:
            input("进入起始章节测验后按回车，程序将自动逐章填写并暂存：")
            result = process_pages_automatically(driver, args)
            if result != 0:
                print("浏览器保持在停止的章节，便于检查。")
            while True:
                command = input("浏览器保持打开；输入 q 退出，按回车从当前章节重新运行自动填写：").strip().lower()
                if command in {"q", "quit", "exit"}:
                    print("正在关闭浏览器。")
                    return result
                result = process_pages_automatically(driver, args)

        print("之后可以连续切换章节；每次按回车都会识别当前页面并填写、暂存。")
        while True:
            command = input("按回车识别当前题目，输入 q 退出：").strip().lower()
            if command in {"q", "quit", "exit"}:
                print("正在关闭浏览器。")
                return 0
            process_current_page(driver, args)
            print("\n浏览器保持打开。请检查答案，或切换到下一章节后再次按回车。")
    except KeyboardInterrupt:
        print("\n操作已取消。")
        return 130
    except Exception as exc:
        print(f"处理页面时发生错误: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except (OSError, WebDriverException):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
