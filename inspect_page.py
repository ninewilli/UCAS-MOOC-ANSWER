from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from selenium import webdriver

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import create_chrome_driver, find_chromedriver
from diagnostics import inspect_frame_tree


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查超星测验页面结构，不填写或保存")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default="page_diagnostic.json")
    parser.add_argument("--driver")
    parser.add_argument("--profile-dir", help="独立 Chrome 配置目录，用于保留检查登录状态")
    args = parser.parse_args()

    options = webdriver.ChromeOptions()
    if args.profile_dir:
        profile_path = Path(args.profile_dir).expanduser().resolve()
        profile_path.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_path}")
    driver_path = find_chromedriver(args.driver)
    if driver_path:
        print(f"使用 ChromeDriver: {driver_path}")

    driver = create_chrome_driver(options, args.driver)
    try:
        driver.get(args.url)
        print("请在浏览器中完成登录，并进入需要检查的章节测验页面。")
        input("确认题目已经显示后，在这里按回车开始只读检查：")
        frames = inspect_frame_tree(driver)
        output = Path(args.output).resolve()
        output.write_text(json.dumps({"frames": frames}, ensure_ascii=False, indent=2), encoding="utf-8")
        question_count = sum(len(frame.get("visibleQuestions", [])) for frame in frames)
        print(f"已检查 {len(frames)} 层页面/iframe，发现 {question_count} 道可见题目。")
        print(f"诊断文件: {output}")
        input("按回车关闭检查浏览器：")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
