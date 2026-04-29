from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from daily_schedule import DISPLAY_TO_CANONICAL_AGENT, display_agent_name, validate_ist_time
import schedule_admin
import scheduled_workflow
import setup_daily_schedule
import workflow

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mypromptdaily",
        description="Run and schedule daily M365 Copilot prompts that email the result through Outlook desktop.",
    )
    parser.add_argument("--version", action="version", version=f"mypromptdaily {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run a one-off Copilot prompt and email the result.",
        description="Run a one-off Copilot prompt and email the result.",
    )
    _copy_actions(workflow.build_parser(), run_parser)
    run_parser.set_defaults(handler=lambda args: workflow.main(args.forwarded_args))

    setup_parser = subparsers.add_parser(
        "setup",
        help="Create the daily config and register the Windows scheduled task.",
        description="Create the daily config and register the Windows scheduled task.",
    )
    _copy_actions(setup_daily_schedule.build_parser(), setup_parser)
    setup_parser.set_defaults(handler=lambda args: setup_daily_schedule.main(args.forwarded_args))

    schedule_parser = subparsers.add_parser(
        "schedule-run",
        help="Run the scheduled job if the configured IST time is due.",
        description="Run the scheduled job if the configured IST time is due.",
    )
    _copy_actions(scheduled_workflow.build_parser(), schedule_parser)
    schedule_parser.set_defaults(handler=lambda args: scheduled_workflow.main(args.forwarded_args))

    status_parser = subparsers.add_parser(
        "status",
        help="Show saved schedule details and Windows task status.",
        description="Show saved schedule details and Windows task status.",
    )
    _copy_actions(schedule_admin.build_status_parser(), status_parser)
    status_parser.set_defaults(handler=lambda args: schedule_admin.status_main(args.forwarded_args))

    remove_parser = subparsers.add_parser(
        "remove-schedule",
        help="Remove the Windows scheduled task.",
        description="Remove the Windows scheduled task.",
    )
    _copy_actions(schedule_admin.build_remove_parser(), remove_parser)
    remove_parser.set_defaults(handler=lambda args: schedule_admin.remove_main(args.forwarded_args))

    return parser


def _copy_actions(source: argparse.ArgumentParser, target: argparse.ArgumentParser) -> None:
    for action in source._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        option_strings = list(action.option_strings)
        kwargs: dict[str, object] = {
            "dest": action.dest,
            "default": action.default,
            "help": action.help,
            "metavar": action.metavar,
        }
        if action.required:
            kwargs["required"] = True
        if action.choices is not None:
            kwargs["choices"] = action.choices

        if isinstance(action, argparse._StoreTrueAction):
            target.add_argument(*option_strings, action="store_true", help=action.help, default=action.default, dest=action.dest)
            continue

        if isinstance(action, argparse._StoreFalseAction):
            target.add_argument(*option_strings, action="store_false", help=action.help, default=action.default, dest=action.dest)
            continue

        if action.nargs is not None:
            kwargs["nargs"] = action.nargs
        if action.const is not None:
            kwargs["const"] = action.const
        if action.type is not None:
            kwargs["type"] = action.type

        target.add_argument(*option_strings, **kwargs)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        return run_interactive_menu()

    args.forwarded_args = argv[1:] if argv else _extract_forwarded_args()
    return args.handler(args)


def _extract_forwarded_args() -> list[str]:
    return sys.argv[2:]


def run_interactive_menu() -> int:
    questionary = _load_questionary()
    choices = [
        questionary.Choice("Run a one-off prompt", value="run"),
        questionary.Choice("Set up daily schedule", value="setup"),
        questionary.Choice("Check scheduled status", value="status"),
        questionary.Choice("Run the scheduled job now", value="schedule-run"),
        questionary.Choice("Remove scheduled task", value="remove-schedule"),
        questionary.Choice("Exit", value="exit"),
    ]
    action = questionary.select("What do you want to do?", choices=choices).ask()
    if not action or action == "exit":
        return 0
    if action == "run":
        return workflow.main(_build_run_args(questionary))
    if action == "setup":
        return setup_daily_schedule.main(_build_setup_args(questionary))
    if action == "status":
        return schedule_admin.status_main([])
    if action == "schedule-run":
        return scheduled_workflow.main(_build_schedule_run_args(questionary))
    return schedule_admin.remove_main(_build_remove_args(questionary))


def _build_run_args(questionary) -> list[str]:
    default_agent = _default_agent_label()
    default_email = os.getenv("OUTLOOK_TO", "")
    default_subject = os.getenv("OUTLOOK_SUBJECT", "M365 Copilot Daily Summary")
    default_prompt = os.getenv("PROMPT_TEXT", "")
    agent = _ask_agent(questionary, default_agent)
    prompt_text = _ask_text(questionary, "Prompt to run", default_prompt)
    email_to = _ask_text(questionary, "Send result to", default_email)
    subject = _ask_text(questionary, "Email subject", default_subject)
    mode = questionary.select(
        "Outlook mode",
        choices=[
            questionary.Choice("Draft", value="draft"),
            questionary.Choice("Send immediately", value="send"),
        ],
        default="draft",
    ).ask()
    return ["--agent", agent, "--prompt", prompt_text, "--to", email_to, "--subject", subject, "--mode", mode]


def _build_setup_args(questionary) -> list[str]:
    default_agent = _default_agent_label()
    default_email = os.getenv("OUTLOOK_TO", "")
    default_subject = os.getenv("OUTLOOK_SUBJECT", "M365 Copilot Daily Summary")
    default_prompt = os.getenv("PROMPT_TEXT", "")
    default_debugger = os.getenv("EDGE_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    default_copilot_url = os.getenv("COPILOT_URL", "https://m365.cloud.microsoft/chat")
    default_cc = os.getenv("OUTLOOK_CC", "")
    agent = _ask_agent(questionary, default_agent)
    prompt_text = _ask_text(questionary, "Daily prompt", default_prompt)
    email_to = _ask_text(questionary, "Self email address", default_email)
    subject = _ask_text(questionary, "Email subject", default_subject)
    send_time_ist = _ask_ist_time(questionary, "09:00")
    mode = questionary.select(
        "Scheduled Outlook mode",
        choices=[
            questionary.Choice("Send immediately", value="send"),
            questionary.Choice("Open draft", value="draft"),
        ],
        default="send",
    ).ask()
    register_task = questionary.confirm("Register the Windows scheduled task now?", default=True).ask()

    args = [
        "--email",
        email_to,
        "--agent",
        agent,
        "--prompt",
        prompt_text,
        "--time-ist",
        send_time_ist,
        "--subject",
        subject,
        "--debugger-address",
        default_debugger,
        "--copilot-url",
        default_copilot_url,
        "--mode",
        mode,
    ]
    if default_cc:
        args.extend(["--cc", default_cc])
    if not register_task:
        args.append("--no-register")
    return args


def _build_schedule_run_args(questionary) -> list[str]:
    dry_run = questionary.confirm("Dry run only?", default=True).ask()
    if dry_run:
        return ["--dry-run"]
    force = questionary.confirm("Force a send even if the IST time is not due yet?", default=False).ask()
    return ["--force"] if force else []


def _build_remove_args(questionary) -> list[str]:
    delete_files = questionary.confirm("Also delete the saved config and state files?", default=False).ask()
    return ["--delete-files"] if delete_files else []


def _ask_agent(questionary, default_value: str) -> str:
    choices = [questionary.Choice(label, value=label) for label in DISPLAY_TO_CANONICAL_AGENT]
    return questionary.select("Choose an agent", choices=choices, default=default_value).ask()


def _ask_text(questionary, message: str, default_value: str) -> str:
    return questionary.text(message, default=default_value, validate=lambda text: bool(text.strip()) or "This value is required.").ask().strip()


def _ask_ist_time(questionary, default_value: str) -> str:
    def _validator(text: str):
        try:
            validate_ist_time(text)
            return True
        except ValueError as exc:
            return str(exc)

    return questionary.text("Daily send time in IST (HH:MM)", default=default_value, validate=_validator).ask().strip()


def _default_agent_label() -> str:
    configured = os.getenv("AGENT_NAME", "") or os.getenv("RESEARCHER_AGENT_NAME", "Researcher")
    return display_agent_name(configured)


def _load_questionary():
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - protected by package dependency
        raise RuntimeError("questionary is not installed. Reinstall the package with `python -m pip install -e .`.") from exc
    return questionary
