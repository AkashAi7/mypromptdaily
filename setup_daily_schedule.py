from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from daily_schedule import DEFAULT_CONFIG_PATH, DEFAULT_STATE_PATH, DEFAULT_TASK_NAME, DISPLAY_TO_CANONICAL_AGENT, DailyScheduleConfig, display_agent_name, save_schedule_config, validate_ist_time


def load_questionary():
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - protected by package dependency
        raise RuntimeError("questionary is not installed. Reinstall the package with `python -m pip install -e .`.") from exc
    return questionary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a daily M365 Copilot schedule and register a Windows Task Scheduler task.")
    parser.add_argument("--email", help="Recipient email address. Usually your own email.")
    parser.add_argument("--agent", help="Agent to run each day.")
    parser.add_argument("--prompt", help="Prompt to run each day.")
    parser.add_argument("--time-ist", help="Daily send time in IST using 24-hour HH:MM format.")
    parser.add_argument("--subject", help="Email subject line.")
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME, help="Windows Task Scheduler task name.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to write the schedule config JSON file.")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to write the scheduler state JSON file.")
    parser.add_argument("--debugger-address", help="Existing Edge debugger address.")
    parser.add_argument("--copilot-url", help="M365 Copilot URL.")
    parser.add_argument("--cc", help="Optional CC recipient.")
    parser.add_argument("--mode", choices=["draft", "send"], default="send", help="Outlook mode for the scheduled run.")
    parser.add_argument("--response-timeout", type=int, default=240, help="Response timeout in seconds.")
    parser.add_argument("--no-register", action="store_true", help="Only write the config file and skip Windows Task Scheduler registration.")
    return parser


def prompt_required(prompt_text: str, default_value: str = "") -> str:
    suffix = f" [{default_value}]" if default_value else ""
    while True:
        value = input(f"{prompt_text}{suffix}: ").strip()
        if value:
            return value
        if default_value:
            return default_value
        print("This value is required.")


def prompt_agent(default_value: str) -> str:
    questionary = load_questionary()
    choices = [questionary.Choice(label, value=label) for label in DISPLAY_TO_CANONICAL_AGENT]
    return questionary.select("Choose the daily agent", choices=choices, default=default_value).ask()


def prompt_ist_time(default_value: str) -> str:
    questionary = load_questionary()

    def _validator(text: str):
        try:
            validate_ist_time(text)
            return True
        except ValueError as exc:
            return str(exc)

    return questionary.text("Daily send time in IST, 24-hour HH:MM", default=default_value, validate=_validator).ask().strip()


def build_task_command(config_path: Path, state_path: Path) -> tuple[str, Path]:
    launcher_path = config_path.parent / "run_mypromptdaily_schedule.cmd"
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    python_command = subprocess.list2cmdline(
        [
            sys.executable,
            "-m",
            "mypromptdaily",
            "schedule-run",
            "--config",
            str(config_path),
            "--state",
            str(state_path),
        ]
    )
    launcher_path.write_text(f"@echo off\r\n{python_command}\r\n", encoding="utf-8")
    return subprocess.list2cmdline([str(launcher_path)]), launcher_path


def register_windows_task(task_name: str, command: str) -> None:
    start_time = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "MINUTE",
            "/MO",
            "1",
            "/ST",
            start_time,
            "/TR",
            command,
            "/F",
            "/IT",
        ],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    state_path = Path(args.state).resolve()
    default_agent = display_agent_name(os.getenv("AGENT_NAME", "Researcher") or os.getenv("RESEARCHER_AGENT_NAME", "Researcher"))
    default_prompt = os.getenv("PROMPT_TEXT", "")
    default_email = os.getenv("OUTLOOK_TO", "")
    default_subject = os.getenv("OUTLOOK_SUBJECT", "M365 Copilot Daily Summary")
    default_debugger = os.getenv("EDGE_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    default_copilot_url = os.getenv("COPILOT_URL", "https://m365.cloud.microsoft/chat")

    email = args.email or prompt_required("Self email address", default_email)
    agent = args.agent or prompt_agent(default_agent)
    prompt_text = args.prompt or prompt_required("Daily prompt", default_prompt)
    send_time_ist = args.time_ist or prompt_ist_time("09:00")
    subject = args.subject or prompt_required("Email subject", default_subject)
    debugger_address = args.debugger_address or default_debugger
    copilot_url = args.copilot_url or default_copilot_url

    config = DailyScheduleConfig(
        email_to=email,
        agent_name=agent,
        prompt_text=prompt_text,
        subject=subject,
        send_time_ist=send_time_ist,
        task_name=args.task_name,
        edge_debugger_address=debugger_address,
        copilot_url=copilot_url,
        outlook_mode=args.mode,
        response_timeout_seconds=args.response_timeout,
        email_cc=args.cc or os.getenv("OUTLOOK_CC", ""),
    )
    save_schedule_config(config_path, config)
    command, launcher_path = build_task_command(config_path, state_path)

    if args.no_register:
        print(f"Saved schedule config to {config_path}")
        print("Skipped Windows Task Scheduler registration.")
        print(f"Launcher script: {launcher_path}")
        print(f"Manual task command: {command}")
        return 0

    register_windows_task(config.task_name, command)
    print(f"Saved schedule config to {config_path}")
    print(f"Launcher script: {launcher_path}")
    print(f"Registered scheduled task '{config.task_name}' to run every minute and send once daily after {config.send_time_ist} IST.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())