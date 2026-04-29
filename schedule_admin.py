from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from daily_schedule import DEFAULT_CONFIG_PATH, DEFAULT_STATE_PATH, current_ist_datetime, load_schedule_config, load_schedule_state
from scheduled_workflow import due_for_send


def build_status_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show the saved daily schedule configuration and Windows task status.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to the saved daily schedule config JSON file.")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to the scheduler state JSON file.")
    return parser


def build_remove_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove the Windows scheduled task for My Prompt Daily.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to the saved daily schedule config JSON file.")
    parser.add_argument("--delete-files", action="store_true", help="Also delete the saved config and state files after removing the task.")
    return parser


def query_task(task_name: str) -> dict[str, str] | None:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    details: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        details[key.strip()] = value.strip()
    return details


def status_main(argv: list[str] | None = None) -> int:
    args = build_status_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    state_path = Path(args.state).resolve()

    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    config = load_schedule_config(config_path)
    state = load_schedule_state(state_path)
    task_details = query_task(config.task_name)
    now_ist = current_ist_datetime()
    last_sent_ist_date = state.get("last_sent_ist_date")
    should_send = due_for_send(config.send_time_ist, last_sent_ist_date, now_ist)

    print(f"Task name: {config.task_name}")
    print(f"Task registered: {'yes' if task_details else 'no'}")
    if task_details:
        print(f"Task status: {task_details.get('Status', 'unknown')}")
        print(f"Next run time: {task_details.get('Next Run Time', 'unknown')}")
    print(f"Config path: {config_path}")
    print(f"State path: {state_path}")
    print(f"Agent: {config.agent_name}")
    print(f"Send time IST: {config.send_time_ist}")
    print(f"Recipient: {config.email_to}")
    print(f"Last sent IST date: {last_sent_ist_date or 'never'}")
    print(f"Due now: {'yes' if should_send else 'no'}")
    return 0


def remove_main(argv: list[str] | None = None) -> int:
    args = build_remove_parser().parse_args(argv)
    config_path = Path(args.config).resolve()

    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    config = load_schedule_config(config_path)
    result = subprocess.run(["schtasks", "/Delete", "/TN", config.task_name, "/F"], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        print(f"Removed scheduled task '{config.task_name}'.")
    else:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"Scheduled task '{config.task_name}' was not removed: {stderr or 'task not found'}")

    if args.delete_files:
        deleted = []
        for path in (config_path, DEFAULT_STATE_PATH.resolve()):
            if path.exists():
                path.unlink()
                deleted.append(str(path))
        if deleted:
            print("Deleted saved files:")
            for path in deleted:
                print(path)
    return 0
