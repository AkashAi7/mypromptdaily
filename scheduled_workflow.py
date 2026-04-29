from __future__ import annotations

import argparse
import traceback
from datetime import datetime
from pathlib import Path

from daily_schedule import DEFAULT_CONFIG_PATH, DEFAULT_LOG_PATH, DEFAULT_STATE_PATH, append_schedule_log, current_ist_datetime, load_schedule_config, load_schedule_state, save_schedule_state
from workflow import WorkflowConfig, run_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the daily M365 Copilot workflow when the configured IST time is due.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to the saved daily schedule config JSON file.")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path to the scheduler state JSON file.")
    parser.add_argument("--force", action="store_true", help="Run immediately and ignore the time gate.")
    parser.add_argument("--dry-run", action="store_true", help="Print due-state information without sending an email.")
    return parser


def due_for_send(send_time_ist: str, last_sent_ist_date: str | None, now_ist: datetime) -> bool:
    scheduled_hour, scheduled_minute = [int(part) for part in send_time_ist.split(":", 1)]
    scheduled_today = now_ist.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
    if now_ist < scheduled_today:
        return False
    return last_sent_ist_date != now_ist.date().isoformat()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    state_path = Path(args.state).resolve()
    try:
        config = load_schedule_config(config_path)
        state = load_schedule_state(state_path)
        now_ist = current_ist_datetime()
        last_sent_ist_date = state.get("last_sent_ist_date")
        should_send = args.force or due_for_send(config.send_time_ist, last_sent_ist_date, now_ist)

        append_schedule_log(
            f"Scheduled runner invoked. force={args.force} dry_run={args.dry_run} due={'yes' if should_send else 'no'}",
            DEFAULT_LOG_PATH,
        )

        if args.dry_run:
            print(f"IST now: {now_ist.strftime('%Y-%m-%d %H:%M')}")
            print(f"Configured time: {config.send_time_ist}")
            print(f"Last sent IST date: {last_sent_ist_date or 'never'}")
            print(f"Due: {'yes' if should_send else 'no'}")
            return 0

        if not should_send:
            print("Not due yet. Exiting without sending.")
            append_schedule_log("Skipped run because the configured IST time is not due yet.", DEFAULT_LOG_PATH)
            return 0

        workflow_config = WorkflowConfig(
            edge_debugger_address=config.edge_debugger_address,
            copilot_url=config.copilot_url,
            agent_name=config.agent_name,
            prompt_text=config.prompt_text,
            outlook_to=config.email_to,
            outlook_cc=config.email_cc,
            outlook_subject=config.subject,
            outlook_mode=config.outlook_mode,
            response_timeout_seconds=config.response_timeout_seconds,
            response_stable_seconds=config.response_stable_seconds,
            keep_tab_open=config.keep_tab_open,
        )
        run_workflow(workflow_config)
        state["last_sent_ist_date"] = now_ist.date().isoformat()
        state["last_sent_ist_timestamp"] = now_ist.isoformat()
        save_schedule_state(state_path, state)
        append_schedule_log("Daily workflow completed successfully.", DEFAULT_LOG_PATH)
        print("Daily workflow completed.")
        return 0
    except Exception:
        append_schedule_log("Scheduled workflow failed:\n" + traceback.format_exc().rstrip(), DEFAULT_LOG_PATH)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
