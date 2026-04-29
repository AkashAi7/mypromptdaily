from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, SessionNotCreatedException, TimeoutException
from selenium.webdriver import EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    import win32com.client  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - validated at runtime on Windows
    win32com = None


TEXTAREA_SELECTORS = [
    (By.CSS_SELECTOR, "span[role='textbox'][aria-label='Message Copilot']"),
    (By.CSS_SELECTOR, "[aria-label='Message Copilot']"),
    (By.CSS_SELECTOR, "textarea"),
    (By.CSS_SELECTOR, "div[contenteditable='true']"),
    (By.CSS_SELECTOR, "span[contenteditable='true']"),
    (By.CSS_SELECTOR, "div[role='textbox']"),
    (By.CSS_SELECTOR, "span[role='textbox']"),
]

RESPONSE_SELECTORS = [
    (By.CSS_SELECTOR, "[data-testid='MessageListContainer']"),
    (By.CSS_SELECTOR, "[data-testid='m365-chat-llm-web-ui-chat-message']"),
    (By.CSS_SELECTOR, "div[data-content='ai-message']"),
    (By.CSS_SELECTOR, "div[data-testid='assistant-message']"),
    (By.CSS_SELECTOR, "[data-message-author-role='assistant']"),
    (By.CSS_SELECTOR, "[data-author='assistant']"),
    (By.CSS_SELECTOR, "[role='article']"),
]

RESPONSE_FOOTERS = [
    "Microsoft would love your perspective",
]

LEADING_RESPONSE_NOISE = [
    "AI-generated content may be incorrect",
]

SUPPORTED_AGENTS = [
    "Researcher",
    "Analyst",
    "Sales",
    "Delivery",
    "Customer Success",
    "Prompt Coach",
    "ECIF",
]

AGENT_ALIASES = {
    "Researcher Agent": "Researcher",
    "Analyst Agent": "Analyst",
    "Sales Agent": "Sales",
    "Delivery Agent": "Delivery",
    "Customer Success Agent": "Customer Success",
    "Prompt Coach": "Prompt Coach",
    "ECIF Agent": "ECIF",
}


@dataclass
class WorkflowConfig:
    edge_debugger_address: str
    copilot_url: str
    agent_name: str
    prompt_text: str
    outlook_to: str
    outlook_cc: str
    outlook_subject: str
    outlook_mode: str
    response_timeout_seconds: int
    response_stable_seconds: int
    keep_tab_open: bool


def load_config(args: argparse.Namespace) -> WorkflowConfig:
    load_dotenv()
    prompt_text = args.prompt or os.getenv("PROMPT_TEXT", "").strip()
    outlook_to = args.to or os.getenv("OUTLOOK_TO", "").strip()
    outlook_mode = (args.mode or os.getenv("OUTLOOK_MODE", "draft")).strip().lower()
    keep_tab_open = args.keep_tab_open or os.getenv("KEEP_TAB_OPEN", "").strip().lower() in {"1", "true", "yes", "on"}
    agent_name = (
        args.agent
        or os.getenv("AGENT_NAME", "").strip()
        or os.getenv("RESEARCHER_AGENT_NAME", "Researcher").strip()
    )
    if not prompt_text:
        raise ValueError("Provide a prompt with --prompt or PROMPT_TEXT.")
    if outlook_mode == "send" and not outlook_to:
        raise ValueError("Provide an email recipient with --to or OUTLOOK_TO.")
    if not agent_name:
        raise ValueError("Provide an agent with --agent or AGENT_NAME.")
    agent_name = normalize_agent_name(agent_name)

    return WorkflowConfig(
        edge_debugger_address=os.getenv("EDGE_DEBUGGER_ADDRESS", "127.0.0.1:9222"),
        copilot_url=os.getenv("COPILOT_URL", "https://m365.cloud.microsoft/chat"),
        agent_name=agent_name,
        prompt_text=prompt_text,
        outlook_to=outlook_to,
        outlook_cc=os.getenv("OUTLOOK_CC", "").strip(),
        outlook_subject=args.subject or os.getenv("OUTLOOK_SUBJECT", "M365 Copilot Researcher Summary"),
        outlook_mode=outlook_mode,
        response_timeout_seconds=int(os.getenv("RESPONSE_TIMEOUT_SECONDS", "180")),
        response_stable_seconds=int(os.getenv("RESPONSE_STABLE_SECONDS", "12")),
        keep_tab_open=keep_tab_open,
    )


def build_driver(debugger_address: str) -> WebDriver:
    options = EdgeOptions()
    options.use_chromium = True
    options.add_experimental_option("debuggerAddress", debugger_address)
    service = EdgeService()
    service.creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return webdriver.Edge(service=service, options=options)
    except SessionNotCreatedException as exc:
        raise RuntimeError(
            "Could not attach to the existing Edge debug session at "
            f"{debugger_address}. Start Edge with --remote-debugging-port=9222, sign into M365 Copilot, and try again."
        ) from exc


def normalize_agent_name(agent_name: str) -> str:
    cleaned = agent_name.strip()
    return AGENT_ALIASES.get(cleaned, cleaned)


def open_copilot_in_new_tab(driver: WebDriver, copilot_url: str) -> Tuple[str, str]:
    original_handle = driver.current_window_handle
    driver.switch_to.new_window("tab")
    driver.get(copilot_url)
    return original_handle, driver.current_window_handle


def cleanup_copilot_tab(driver: WebDriver, original_handle: str, copilot_handle: str) -> None:
    try:
        if copilot_handle in driver.window_handles:
            driver.switch_to.window(copilot_handle)
            driver.close()
    except Exception:
        pass

    try:
        remaining_handles = driver.window_handles
        if original_handle in remaining_handles:
            driver.switch_to.window(original_handle)
    except Exception:
        pass


def click_first_matching_text(driver: WebDriver, texts: Iterable[str], timeout_seconds: int = 10) -> bool:
    wait = WebDriverWait(driver, timeout_seconds)
    for text in texts:
        xpath = (
            "//*[self::button or self::a or @role='button' or self::span or self::div]"
            f"[contains(normalize-space(.), \"{text}\")]"
        )
        try:
            element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            element.click()
            return True
        except TimeoutException:
            continue
    return False


def activate_agent(driver: WebDriver, agent_name: str) -> None:
    normalized_agent_name = normalize_agent_name(agent_name)
    candidate_texts = [normalized_agent_name]
    for label, value in AGENT_ALIASES.items():
        if value == normalized_agent_name and label not in candidate_texts:
            candidate_texts.append(label)

    if click_first_matching_text(driver, candidate_texts, timeout_seconds=5):
        return

    if click_first_matching_text(driver, ["Agents", "Explore agents", "Choose agent"], timeout_seconds=8):
        if click_first_matching_text(driver, candidate_texts, timeout_seconds=8):
            return

    raise RuntimeError(
        f"Unable to activate the '{agent_name}' agent. Confirm the M365 Copilot page layout and update the selectors if needed."
    )


def find_prompt_box(driver: WebDriver, timeout_seconds: int = 20):
    wait = WebDriverWait(driver, timeout_seconds)
    for selector in TEXTAREA_SELECTORS:
        try:
            return wait.until(EC.element_to_be_clickable(selector))
        except TimeoutException:
            continue
    raise RuntimeError("Unable to locate the Copilot prompt input box.")


def submit_prompt(driver: WebDriver, prompt_text: str) -> None:
    prompt_box = find_prompt_box(driver)
    prompt_box.click()
    tag_name = prompt_box.tag_name.lower()
    contenteditable = (prompt_box.get_attribute("contenteditable") or "").lower()

    if tag_name == "textarea":
        prompt_box.clear()
        prompt_box.send_keys(prompt_text)
    elif contenteditable == "true":
        if driver.execute_script(
            """
            const editorEl = arguments[0];
            const text = arguments[1];
            editorEl.focus();
            editorEl.textContent = '';
            editorEl.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'deleteContentBackward',
                data: null,
            }));
            editorEl.textContent = text;
            editorEl.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: text,
            }));
            editorEl.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
            """,
            prompt_box,
            prompt_text,
        ):
            try:
                send_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Send']"))
                )
                if driver.execute_script(
                    """
                    const sendEl = arguments[0];
                    const propsKey = Reflect.ownKeys(sendEl).find((key) => String(key).startsWith('__reactProps$'));
                    const props = propsKey ? sendEl[propsKey] : null;
                    if (props && typeof props.onClick === 'function') {
                        props.onClick({
                            type: 'click',
                            currentTarget: sendEl,
                            target: sendEl,
                            preventDefault() {},
                            stopPropagation() {},
                        });
                        return true;
                    }
                    sendEl.click();
                    return true;
                    """,
                    send_button,
                ):
                    return
            except TimeoutException:
                pass

        editor_state = {
            "root": {
                "children": [
                    {
                        "children": [
                            {
                                "detail": 0,
                                "format": 0,
                                "mode": "normal",
                                "style": "",
                                "text": prompt_text,
                                "type": "text",
                                "version": 1,
                            },
                            {
                                "detail": 0,
                                "format": 0,
                                "mode": "normal",
                                "style": "",
                                "text": "\u200b\u200c",
                                "type": "sentinel",
                                "version": 1,
                            },
                        ],
                        "direction": None,
                        "format": "",
                        "indent": 0,
                        "textFormat": 0,
                        "textStyle": "",
                        "type": "paragraph",
                        "version": 1,
                    }
                ],
                "direction": None,
                "format": "",
                "indent": 0,
                "type": "root",
                "version": 1,
            }
        }
        if driver.execute_script(
            """
            const editorEl = arguments[0];
            const stateJson = arguments[1];
            const lexical = editorEl.__lexicalEditor;
            if (!lexical) {
                return false;
            }
            const nextState = lexical.parseEditorState(JSON.stringify(stateJson));
            lexical.setEditorState(nextState, {tag: 'history-merge'});
            return true;
            """,
            prompt_box,
            editor_state,
        ):
            send_button = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Send']")
            driver.execute_script(
                """
                const sendEl = arguments[0];
                const propsKey = Reflect.ownKeys(sendEl).find((key) => String(key).startsWith('__reactProps$'));
                const props = propsKey ? sendEl[propsKey] : null;
                if (props && typeof props.onClick === 'function') {
                    props.onClick({
                        type: 'click',
                        currentTarget: sendEl,
                        target: sendEl,
                        preventDefault() {},
                        stopPropagation() {},
                    });
                    return true;
                }
                return false;
                """,
                send_button,
            )
            return

        driver.execute_script("arguments[0].focus();", prompt_box)
        driver.execute_cdp_cmd("Input.insertText", {"text": prompt_text})
    else:
        driver.execute_script("arguments[0].innerText = '';", prompt_box)
        prompt_box.send_keys(prompt_text)

    if click_first_matching_text(driver, ["Send"], timeout_seconds=5):
        return

    prompt_box.send_keys(Keys.ENTER)


def strip_response_footers(text: str) -> str:
    cleaned = text.replace("\u200c", "").strip()
    for marker in RESPONSE_FOOTERS:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
    return cleaned


def strip_leading_noise(text: str) -> str:
    cleaned = text.strip()
    for marker in LEADING_RESPONSE_NOISE:
        if cleaned.startswith(marker):
            cleaned = cleaned.split(marker, 1)[1].strip()
    return cleaned


def is_substantive_response(text: str, prompt_text: str) -> bool:
    cleaned = strip_leading_noise(strip_response_footers(text))
    if not cleaned:
        return False
    if prompt_text and cleaned == prompt_text:
        return False
    return len(cleaned) >= 80 or "\n" in cleaned


def extract_response_from_text(text: str, prompt_text: str) -> str:
    cleaned = text.replace("\u200c", "").strip()
    if not cleaned:
        return ""
    if "Copilot said:" in cleaned:
        cleaned = cleaned.rsplit("Copilot said:", 1)[-1].strip()
    elif prompt_text and prompt_text in cleaned:
        cleaned = cleaned.split(prompt_text, 1)[1].strip()

    cleaned = strip_leading_noise(strip_response_footers(cleaned))
    return cleaned.strip()


def get_last_response_text(driver: WebDriver, prompt_text: str = "") -> str:
    for selector in RESPONSE_SELECTORS:
        elements = driver.find_elements(*selector)
        non_empty = []
        for element in elements:
            text = element.text.strip()
            if not text:
                continue
            text = extract_response_from_text(text, prompt_text)
            non_empty.append(text)
        if non_empty:
            return non_empty[-1]
    return ""


def get_message_list_response(driver: WebDriver, prompt_text: str = "") -> str:
    containers = driver.find_elements(By.CSS_SELECTOR, "[data-testid='MessageListContainer']")
    if not containers:
        return ""

    text = containers[-1].text.strip()
    return extract_response_from_text(text, prompt_text)


def get_body_response(driver: WebDriver, prompt_text: str = "") -> str:
    body_text = driver.find_element(By.TAG_NAME, "body").text
    return extract_response_from_text(body_text, prompt_text)


def wait_for_research_response(driver: WebDriver, prompt_text: str, timeout_seconds: int, stable_seconds: int) -> str:
    deadline = time.time() + timeout_seconds
    previous_text = ""
    stable_since: Optional[float] = None
    best_text = ""

    while time.time() < deadline:
        for extractor in (get_message_list_response, get_last_response_text, get_body_response):
            current_text = extractor(driver, prompt_text)
            if not current_text:
                continue

            if current_text != previous_text:
                previous_text = current_text
                stable_since = time.time()
                if len(current_text) >= len(best_text):
                    best_text = current_text
                continue

            if len(current_text) >= len(best_text):
                best_text = current_text

            if stable_since and time.time() - stable_since >= stable_seconds:
                return current_text

        time.sleep(3)

    if best_text:
        return best_text

    raise TimeoutException("Timed out while waiting for the Researcher response to stabilize.")


def compose_email_body(prompt_text: str, response_text: str, page_url: str) -> str:
    return (
        "M365 Copilot workflow result\n\n"
        f"Prompt:\n{prompt_text}\n\n"
        f"Response:\n{response_text}\n\n"
        f"Source tab:\n{page_url}\n"
    )


def share_via_outlook(config: WorkflowConfig, email_body: str) -> None:
    if win32com is None:
        raise RuntimeError("pywin32 is not installed. Run `pip install -r requirements.txt`.")

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = config.outlook_to
    if config.outlook_cc:
        mail.CC = config.outlook_cc
    mail.Subject = config.outlook_subject
    mail.Body = email_body

    if config.outlook_mode == "send":
        mail.Send()
        print("Email sent with Outlook desktop.")
    else:
        mail.Display()
        print("Email draft opened in Outlook desktop.")


def run_workflow(config: WorkflowConfig) -> None:
    driver = build_driver(config.edge_debugger_address)
    original_handle = driver.current_window_handle
    copilot_handle = original_handle
    try:
        original_handle, copilot_handle = open_copilot_in_new_tab(driver, config.copilot_url)
        activate_agent(driver, config.agent_name)
        submit_prompt(driver, config.prompt_text)
        try:
            response_text = wait_for_research_response(
                driver,
                config.prompt_text,
                config.response_timeout_seconds,
                config.response_stable_seconds,
            )
        except TimeoutException:
            response_text = (
                get_message_list_response(driver, config.prompt_text)
                or get_last_response_text(driver, config.prompt_text)
                or get_body_response(driver, config.prompt_text)
            )
            if not response_text:
                raise

        if not response_text:
            raise RuntimeError("Researcher returned an empty response.")

        email_body = compose_email_body(config.prompt_text, response_text, driver.current_url)
        share_via_outlook(config, email_body)
    finally:
        if not config.keep_tab_open:
            cleanup_copilot_tab(driver, original_handle, copilot_handle)
        driver.quit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an M365 Copilot agent prompt and share the result in Outlook desktop.")
    parser.add_argument("--agent", help="Agent to select in M365 Copilot.")
    parser.add_argument("--prompt", help="Prompt to submit to the selected agent.")
    parser.add_argument("--to", help="Primary Outlook recipient.")
    parser.add_argument("--subject", help="Outlook email subject.")
    parser.add_argument("--keep-tab-open", action="store_true", help="Keep the opened Copilot tab open after the workflow finishes.")
    parser.add_argument(
        "--mode",
        choices=["draft", "send"],
        help="Use `draft` to open an Outlook draft or `send` to send immediately.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args)
        run_workflow(config)
        return 0
    except (RuntimeError, ValueError, TimeoutException, NoSuchElementException) as exc:
        print(f"Workflow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())