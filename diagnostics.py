from __future__ import annotations

from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver


INSPECT_SCRIPT = r"""
const questionSelectors = [
  '.questionLi', '.TiMu', '.question-item', '.subject-item', '.topic-item',
  '[data-question-id]', '[data-questionid]', 'li[id^="question"]'
];
const titleSelectors = [
  '.stem', '.mark_name', '.Zy_TItle', '.question-title', '.subject-title',
  '.topic-title', '.qtContent', '.question-content', '[data-role="question-title"]'
];
const textOf = (element) => (element && (element.innerText || element.textContent) || '').trim();
const visible = (element) => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);

const rawQuestions = [...document.querySelectorAll(questionSelectors.join(','))];
const questions = rawQuestions
  .filter(visible)
  .filter((candidate) => !rawQuestions.some((other) => (
    other !== candidate && visible(other) && candidate.contains(other)
  )))
  .map((container, index) => {
    let title = '';
    for (const selector of titleSelectors) {
      const node = container.querySelector(selector);
      if (node && textOf(node)) { title = textOf(node); break; }
    }
    const optionNodes = [...container.querySelectorAll(
      '.Zy_ulTop > li,.answerList > li,.option-list > li,.options > li,[data-option],label'
    )].filter(visible);
    const controls = [...container.querySelectorAll('input,textarea,[contenteditable="true"]')];
    return {
      index: index + 1,
      tag: container.tagName,
      id: container.id || null,
      className: String(container.className || ''),
      dataQuestionId: container.dataset.questionId || container.dataset.questionid || null,
      title: title || textOf(container).slice(0, 500),
      options: optionNodes.map((node) => textOf(node)).filter(Boolean),
      controls: controls.map((control) => ({
        tag: control.tagName,
        type: control.type || null,
        name: control.name || null,
        value: control.value || null,
        checked: !!control.checked,
        className: String(control.className || '')
      })),
      html: container.outerHTML.slice(0, 12000)
    };
  });

return {
  title: document.title,
  url: location.href,
  readyState: document.readyState,
  matchedQuestionNodes: rawQuestions.length,
  visibleQuestions: questions,
  buttons: [...document.querySelectorAll('button,input[type="button"],input[type="submit"],a,[role="button"]')]
    .filter(visible)
    .map((element) => String(element.value || element.innerText || element.textContent || '').trim())
    .filter(Boolean)
    .slice(0, 200),
  frames: [...document.querySelectorAll('iframe,frame')].map((frame) => ({
    id: frame.id || null,
    name: frame.name || null,
    className: String(frame.className || ''),
    src: frame.src || frame.getAttribute('src') || null,
    visible: visible(frame)
  }))
};
"""


def inspect_frame_tree(driver: WebDriver) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    driver.switch_to.default_content()

    def visit(frame_path: str) -> None:
        try:
            data = driver.execute_script(INSPECT_SCRIPT)
            data["framePath"] = frame_path
            results.append(data)
        except Exception as exc:
            results.append({"framePath": frame_path, "error": str(exc)})
            return

        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        for index in range(len(frames)):
            try:
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
                driver.switch_to.frame(frames[index])
                visit(f"{frame_path}/{index}")
                driver.switch_to.parent_frame()
            except Exception as exc:
                results.append({"framePath": f"{frame_path}/{index}", "error": str(exc)})
                driver.switch_to.default_content()
                for raw_index in frame_path.split("/")[1:]:
                    current_frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
                    driver.switch_to.frame(current_frames[int(raw_index)])

    visit("top")
    driver.switch_to.default_content()
    return results

