import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from selenium import webdriver

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filler import AnswerFiller, load_answers
from browser import create_chrome_driver, find_chromedriver
from main import (
    chapter_id_from_url,
    load_chapter_sequence,
    process_current_page,
    process_pages_automatically,
    replace_chapter_id,
)


FIXTURE = """
<!doctype html><meta charset="utf-8"><title>fixture</title>
<section class="question-item" data-question-id="q1">
  <h3 class="question-title">1. Python 中哪个关键字用于定义函数？</h3>
  <label><input type="radio" name="q1"> A. class</label>
  <label><input type="radio" name="q1"> B. def</label>
  <label><input type="radio" name="q1"> C. import</label>
</section>
<section class="question-item" data-question-id="q2">
  <h3 class="question-title">下列哪些属于 Python 内置容器？</h3>
  <label><input type="checkbox" name="q2"> A. list</label>
  <label><input type="checkbox" name="q2"> B. thread</label>
  <label><input type="checkbox" name="q2"> C. dict</label>
</section>
<section class="question-item" id="q3">
  <h3 class="question-title">Python 是解释型语言。</h3>
  <label><input type="radio" name="q3">正确</label>
  <label><input type="radio" name="q3">错误</label>
</section>
<section class="question-item" id="q4">
  <h3 class="question-title">请填写课程名称</h3>
  <input type="text">
</section>
<button id="save" onclick="window.saved = (window.saved || 0) + 1">暂时保存</button>
<button id="submit" onclick="window.submitted = true">提交</button>
"""


class AnswerValidationTest(unittest.TestCase):
    def test_replaces_only_chapter_id_in_course_url(self):
        original = "https://example.test/studentstudy?chapterId=1&courseId=2&clazzid=3&enc=abc"
        changed = replace_chapter_id(original, "99")
        self.assertEqual(chapter_id_from_url(changed), "99")
        self.assertIn("courseId=2", changed)
        self.assertIn("clazzid=3", changed)
        self.assertIn("enc=abc", changed)

    def test_auto_navigation_uses_mapping_order_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({
                "answer_sets": {
                    "一": [{"index": 1, "type": "single", "answer": "A"}],
                    "二": [{"index": 1, "type": "single", "answer": "B"}],
                    "三": [{"index": 1, "type": "single", "answer": "C"}],
                },
                "chapter_sets": {"11": "一", "22": "二", "33": "三"},
            }, ensure_ascii=False), encoding="utf-8")

            class Driver:
                current_url = "https://example.test/studentstudy?chapterId=11&courseId=2"
                visited = []

                def get(self, url):
                    self.current_url = url
                    self.visited.append(chapter_id_from_url(url))

            driver = Driver()
            args = SimpleNamespace(answers=str(path), page_delay=0)
            with patch("main.process_current_page", side_effect=[0, 6]) as process, \
                    patch("main.accept_pending_alert", return_value=None):
                result = process_pages_automatically(driver, args)
            self.assertEqual(result, 6)
            self.assertEqual(driver.visited, ["22"])
            self.assertEqual(process.call_count, 2)

    def test_chapter_sequence_ignores_mappings_without_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({
                "answer_sets": {"一": [{"index": 1, "type": "single", "answer": "A"}]},
                "chapter_sets": {"11": "一", "22": "不存在"},
            }, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_chapter_sequence(path), [("11", "一")])

    def test_finds_explicit_driver(self):
        driver_path = os.environ.get("CHROMEDRIVER")
        if not driver_path:
            self.skipTest("CHROMEDRIVER is not set")
        self.assertEqual(find_chromedriver(driver_path), Path(driver_path).resolve())

    def test_loads_answer_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({"answers": [{"index": 1, "type": "single", "answer": "A"}]}), encoding="utf-8")
            self.assertEqual(load_answers(path)[0]["answer"], "A")

    def test_rejects_multiple_answer_string(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({"answers": [{"index": 1, "type": "multiple", "answer": "A,C"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必须是数组"):
                load_answers(path)

    def test_selects_named_answer_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(
                json.dumps(
                    {
                        "answer_sets": {
                            "1.1章节测验": [{"index": 1, "type": "single", "answer": "D"}],
                            "1.2章节测验": [{"index": 1, "type": "judge", "answer": "对"}],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_answers(path, "1.2章节测验")[0]["answer"], "对")
            with self.assertRaisesRegex(ValueError, "--set"):
                load_answers(path)

    def test_search_all_flattens_answer_sets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(
                json.dumps({
                    "answer_sets": {
                        "一": [{"index": 1, "type": "single", "answer": "A", "note": "甲"}],
                        "二": [{"index": 1, "type": "single", "answer": "B", "note": "乙"}],
                    }
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            answers = load_answers(path, search_all=True)
            self.assertEqual(len(answers), 2)
            self.assertEqual({item["_answer_set"] for item in answers}, {"一", "二"})

    def test_selects_set_from_chapter_url_and_rejects_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(
                json.dumps(
                    {
                        "answer_sets": {
                            "1.1章节测验": [{"index": 1, "type": "single", "answer": "D"}],
                            "7.1章节测验": [{"index": 1, "type": "text", "answer": "备份"}],
                        },
                        "chapter_sets": {"661774": "7.1章节测验"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            url = "https://example.test/studentstudy?chapterId=661774"
            self.assertEqual(load_answers(path, source_url=url)[0]["answer"], "备份")
            with self.assertRaisesRegex(ValueError, "不能使用"):
                load_answers(path, "1.1章节测验", url)


class BrowserFillerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_directory = tempfile.TemporaryDirectory()
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-data-dir={cls.profile_directory.name}")
        cls.driver = create_chrome_driver(options, os.environ.get("CHROMEDRIVER"))

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile_directory.cleanup()

    def test_fills_supported_question_types_without_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "fixture.html"
            fixture_path.write_text(FIXTURE, encoding="utf-8")
            self.driver.get(fixture_path.as_uri())
            answers = [
                {"question": "Python 中哪个关键字用于定义函数？", "type": "single", "answer": "B"},
                {"id": "q2", "type": "multiple", "answer": ["A", "dict"]},
                {"question": "Python 是解释型语言。", "type": "judge", "answer": "正确"},
                {"index": 4, "type": "text", "answer": "示例课程"},
            ]
            report = AnswerFiller(self.driver, answers).fill_current_page()

            self.assertEqual(report.filled_count, 4)
            self.assertEqual(self.driver.execute_script("return [...document.querySelectorAll('input:checked')].map(x => x.parentElement.innerText.trim())"), ["B. def", "A. list", "C. dict", "正确"])
            self.assertEqual(self.driver.execute_script("return document.querySelector('input[type=text]').value"), "示例课程")
            self.assertTrue(report.draft_saved)
            self.assertEqual(self.driver.execute_script("return window.saved"), 1)
            self.assertIsNone(self.driver.execute_script("return window.submitted"))

    def test_process_skips_already_submitted_page(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "already-completed.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div>任务点已完成</div><div>查看已批阅作业</div>
                <button onclick="window.repeatedSubmit = true">提交</button>""",
                encoding="utf-8",
            )
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(
                json.dumps({"answers": [{"index": 1, "type": "single", "answer": "A"}]}),
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            args = SimpleNamespace(
                answers=str(answers_path),
                answer_set=None,
                search=False,
                submit=True,
                wait=0,
            )
            self.assertEqual(process_current_page(self.driver, args, require_complete=True), 0)
            self.assertIsNone(self.driver.execute_script("return window.repeatedSubmit"))

    def test_detects_multiple_choice_from_page_checkbox(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "checkbox.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="TiMu">
                  <div class="Zy_TItle">【多选题】请选择两个答案</div>
                  <ul class="Zy_ulTop">
                    <li><label><input type="checkbox" name="q">A</label><span>劳动</span></li>
                    <li><label><input type="checkbox" name="q">B</label><span>资本</span></li>
                    <li><label><input type="checkbox" name="q">C</label><span>空间</span></li>
                  </ul>
                </div>
                <button onclick="window.saved = true">暂时保存</button>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())

            # Even with a bad configured type, the real checkbox controls win.
            report = AnswerFiller(
                self.driver,
                [{"index": 1, "type": "single", "answer": ["A", "B"]}],
            ).fill_current_page()

            self.assertEqual(report.filled_count, 1)
            self.assertEqual(
                self.driver.execute_script("return [...document.querySelectorAll('input:checked')].map(x => x.parentElement.innerText)"),
                ["A", "B"],
            )
            self.assertIn("多选", report.filled[0]["detail"])

    def test_search_mode_ignores_index_and_matches_option_text(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "search.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="TiMu"><div class="Zy_TItle">题目顺序已变化</div>
                  <ul class="Zy_ulTop"><li><label><input type="radio" name="q">A. 甲</label></li>
                  <li><label><input type="radio" name="q">B. 乙</label></li></ul>
                </div>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"index": 99, "type": "single", "answer": "B", "note": "乙"}],
                search_only=True,
            ).fill_current_page()
            self.assertEqual(report.filled_count, 1)
            self.assertEqual(self.driver.execute_script("return document.querySelector('input:checked').parentElement.innerText"), "B. 乙")

    def test_fills_question_inside_nested_iframe(self):
        with tempfile.TemporaryDirectory() as directory:
            child_path = Path(directory) / "child.html"
            child_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="TiMu" data-question-id="nested">
                  <div class="Zy_TItle">嵌套页面中的题目</div>
                  <label><input type="radio" name="nested">A. 否</label>
                  <label><input type="radio" name="nested">B. 是</label>
                </div>
                <button onclick="window.submitted = true">保存并提交</button>""",
                encoding="utf-8",
            )
            parent_path = Path(directory) / "parent.html"
            parent_path.write_text(
                f'<!doctype html><meta charset="utf-8"><iframe src="{child_path.as_uri()}"></iframe>',
                encoding="utf-8",
            )
            self.driver.get(parent_path.as_uri())

            report = AnswerFiller(
                self.driver,
                [{"id": "nested", "type": "single", "answer": "B"}],
            ).fill_current_page()

            self.assertEqual(report.frame_count, 2)
            self.assertEqual(report.filled_count, 1)
            self.assertFalse(report.draft_saved)
            self.driver.switch_to.frame(0)
            self.assertEqual(
                self.driver.execute_script("return document.querySelector('input:checked').parentElement.innerText.trim()"),
                "B. 是",
            )
            self.assertIsNone(self.driver.execute_script("return window.submitted"))
            self.driver.switch_to.default_content()

    def test_saves_from_nested_iframe_with_extended_button_text(self):
        with tempfile.TemporaryDirectory() as directory:
            child_path = Path(directory) / "save-child.html"
            child_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="question-item"><h3 class="question-title">嵌套保存题</h3>
                  <label><input type="radio" name="q">A. 是</label></div>
                <button onclick="window.saved = true">暂时保存答案</button>
                <button onclick="window.submitted = true">提交</button>""",
                encoding="utf-8",
            )
            parent_path = Path(directory) / "save-parent.html"
            parent_path.write_text(f'<!doctype html><iframe src="{child_path.as_uri()}"></iframe>', encoding="utf-8")
            self.driver.get(parent_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "嵌套保存题", "type": "single", "answer": "A"}],
            ).fill_current_page()
            self.assertTrue(report.draft_saved)
            self.driver.switch_to.frame(0)
            self.assertTrue(self.driver.execute_script("return window.saved"))
            self.assertIsNone(self.driver.execute_script("return window.submitted"))
            self.driver.switch_to.default_content()

    def test_accepts_save_success_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "save-alert.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="question-item"><h3 class="question-title">保存提示题</h3>
                  <label><input type="radio" name="q">A. 是</label></div>
                <button onclick="alert('保存成功')">暂时保存</button>
                <button onclick="window.submitted = true">提交</button>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "保存提示题", "type": "single", "answer": "A"}],
            ).fill_current_page()
            self.assertTrue(report.draft_saved)
            self.assertIn("保存成功", report.draft_save_detail)
            self.assertEqual(self.driver.title, "")
            self.assertIsNone(self.driver.execute_script("return window.submitted"))

    def test_submit_mode_confirms_and_waits_for_success_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "submit-alert.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="question-item"><h3 class="question-title">提交提示题</h3>
                  <label><input type="radio" name="q">A. 是</label></div>
                <button onclick="window.saved = true">暂时保存</button>
                <button onclick="if (confirm('确认提交？')) { window.submitted = true; setTimeout(() => alert('提交成功'), 50); }">提交</button>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "提交提示题", "type": "single", "answer": "A"}],
                submit=True,
            ).fill_current_page()
            self.assertTrue(report.submitted)
            self.assertIn("提交成功", report.submit_detail)
            self.assertTrue(self.driver.execute_script("return window.submitted"))
            self.assertIsNone(self.driver.execute_script("return window.saved"))

    def test_submit_mode_clicks_web_dialog_yes_button(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "submit-web-dialog.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="question-item"><h3 class="question-title">网页确认题</h3>
                  <label><input type="radio" name="q">A. 是</label></div>
                <button onclick="document.getElementById('confirm').hidden = false">提交</button>
                <div id="confirm" role="dialog" hidden>
                  <p>是否确认提交？</p>
                  <button onclick="window.submitted = true; alert('提交成功')">是</button>
                  <button onclick="this.parentElement.hidden = true">否</button>
                </div>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "网页确认题", "type": "single", "answer": "A"}],
                submit=True,
            ).fill_current_page()
            self.assertTrue(report.submitted)
            self.assertIn("已点击提交确认", report.submit_detail)
            self.assertIn("提交成功", report.submit_detail)
            self.assertTrue(self.driver.execute_script("return window.submitted"))

    def test_submit_mode_clicks_real_confirm_sub_win_button(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "submit-confirm-sub-win.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="question-item"><h3 class="question-title">真实确认框题</h3>
                  <label><input type="radio" name="q">A. 是</label></div>
                <button onclick="document.getElementById('confirmSubWin').hidden = false">提交</button>
                <div id="confirmSubWin" role="alertdialog" hidden>
                  <h3>确认提交</h3>
                  <button onclick="window.submitted = true; alert('提交成功')">确定</button>
                  <button>取消</button>
                </div>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "真实确认框题", "type": "single", "answer": "A"}],
                submit=True,
            ).fill_current_page()
            self.assertTrue(report.submitted)
            self.assertIn("提交成功", report.submit_detail)
            self.assertTrue(self.driver.execute_script("return window.submitted"))

    def test_submit_mode_accepts_completed_page_without_success_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "submit-completed-page.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <main id="work">
                  <div class="question-item"><h3 class="question-title">完成页确认题</h3>
                    <label><input type="radio" name="q">A. 是</label></div>
                  <button onclick="document.getElementById('confirmSubWin').hidden = false">提交</button>
                  <div id="confirmSubWin" role="alertdialog" hidden>
                    <h3>确认提交</h3>
                    <button onclick="document.getElementById('work').innerHTML = '<div>任务点已完成</div><div>查看已批阅作业</div>'">确定</button>
                    <button>取消</button>
                  </div>
                </main>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())
            report = AnswerFiller(
                self.driver,
                [{"question": "完成页确认题", "type": "single", "answer": "A"}],
                submit=True,
            ).fill_current_page()
            self.assertTrue(report.submitted)
            self.assertIn("任务点已完成", report.submit_detail)

    def test_clicks_chaoxing_option_rows_without_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "chaoxing.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="TiMu" style="display:none">
                  <div class="Zy_TItle">隐藏模板题</div>
                  <ul class="Zy_ulTop"><li>A. 模板选项</li></ul>
                </div>
                <div class="questionLi">
                  <div class="TiMu" data-question-id="cx1">
                    <div class="Zy_TItle">超星无 input 单选题</div>
                    <ul class="Zy_ulTop">
                      <li onclick="this.parentElement.querySelectorAll('li').forEach(x => x.classList.remove('cur')); this.classList.add('cur')">B. 选项乙</li>
                      <li onclick="this.parentElement.querySelectorAll('li').forEach(x => x.classList.remove('cur')); this.classList.add('cur')">A. 选项甲</li>
                    </ul>
                  </div>
                </div>
                <button onclick="window.saved = true">暂时保存</button>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())

            report = AnswerFiller(
                self.driver,
                [{"index": 1, "type": "single", "answer": "B", "note": "选项乙"}],
            ).fill_current_page()

            self.assertEqual(report.question_count, 1)
            self.assertEqual(report.filled_count, 1)
            self.assertEqual(
                self.driver.execute_script("return document.querySelector('.Zy_ulTop .cur').innerText"),
                "B. 选项乙",
            )
            self.assertTrue(report.draft_saved)

    def test_fills_chaoxing_ueditor_blanks_in_question_order(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "ueditor.html"
            fixture_path.write_text(
                """<!doctype html><meta charset="utf-8">
                <div class="TiMu">
                  <div class="Zy_TItle">信息安全目标是____和____。</div>
                  <textarea id="answerEditor1" style="display:none"></textarea>
                  <iframe id="ueditor_0" srcdoc="<body contenteditable='true'></body>"></iframe>
                  <textarea id="answerEditor2" style="display:none"></textarea>
                  <iframe id="ueditor_1" srcdoc="<body contenteditable='true'></body>"></iframe>
                </div>
                <button onclick="window.saved = true">暂时保存</button>
                <script>
                  window.UE = { getEditor(id) { return {
                    setContent(value) { document.getElementById(id).dataset.editorValue = value; },
                    sync() { document.getElementById(id).value = document.getElementById(id).dataset.editorValue; }
                  }; } };
                </script>""",
                encoding="utf-8",
            )
            self.driver.get(fixture_path.as_uri())

            report = AnswerFiller(
                self.driver,
                [{"index": 1, "type": "text", "answer": ["机密性", "完整性"]}],
            ).fill_current_page()

            self.assertEqual(report.question_count, 1)
            self.assertEqual(report.frame_count, 1)
            self.assertEqual(report.filled_count, 1)
            self.assertEqual(
                self.driver.execute_script("return [...document.querySelectorAll('textarea')].map(x => x.value)"),
                ["机密性", "完整性"],
            )
            self.assertTrue(report.draft_saved)


if __name__ == "__main__":
    unittest.main()
