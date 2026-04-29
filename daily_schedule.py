from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from workflow import AGENT_ALIASES, SUPPORTED_AGENTS, normalize_agent_name

IST = ZoneInfo("Asia/Kolkata")
DISPLAY_TO_CANONICAL_AGENT = {
    "Researcher Agent": "Researcher",
    "Analyst Agent": "Analyst",
    "Sales Agent": "Sales",
    "Delivery Agent": "Delivery",
    "Customer Success Agent": "Customer Success",
    "Prompt Coach": "Prompt Coach",
    "ECIF Agent": "ECIF",
}
CANONICAL_TO_DISPLAY_AGENT = {value: key for key, value in DISPLAY_TO_CANONICAL_AGENT.items()}
DEFAULT_TASK_NAME = "M365CopilotDailyDigest"


def get_app_home() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "mypromptdaily"
    return Path.home() / ".mypromptdaily"


DEFAULT_CONFIG_PATH = get_app_home() / "daily_schedule_config.json"
DEFAULT_STATE_PATH = get_app_home() / "daily_schedule_state.json"


def has_saved_schedule(config_path: Path | None = None) -> bool:
    target = config_path or DEFAULT_CONFIG_PATH
    return target.exists()


@dataclass
class DailyScheduleConfig:
    email_to: str
    agent_name: str
    prompt_text: str
    subject: str
    send_time_ist: str
    task_name: str = DEFAULT_TASK_NAME
    edge_debugger_address: str = "127.0.0.1:9222"
    copilot_url: str = "https://m365.cloud.microsoft/chat"
    outlook_mode: str = "send"
    response_timeout_seconds: int = 240
    response_stable_seconds: int = 12
    keep_tab_open: bool = False
    email_cc: str = ""


def validate_ist_time(time_text: str) -> str:
    try:
        parsed = datetime.strptime(time_text.strip(), "%H:%M")
    except ValueError as exc:
        raise ValueError("Provide IST time in 24-hour HH:MM format.") from exc
    return parsed.strftime("%H:%M")


def normalize_schedule_agent(agent_name: str) -> str:
    cleaned = agent_name.strip()
    if cleaned in DISPLAY_TO_CANONICAL_AGENT:
        return DISPLAY_TO_CANONICAL_AGENT[cleaned]
    normalized = normalize_agent_name(cleaned)
    if normalized not in SUPPORTED_AGENTS:
        supported = ", ".join(DISPLAY_TO_CANONICAL_AGENT)
        raise ValueError(f"Unsupported agent '{agent_name}'. Choose one of: {supported}.")
    return normalized


def display_agent_name(agent_name: str) -> str:
    normalized = normalize_schedule_agent(agent_name)
    return CANONICAL_TO_DISPLAY_AGENT.get(normalized, normalized)


def normalize_config(config: DailyScheduleConfig) -> DailyScheduleConfig:
    return DailyScheduleConfig(
        email_to=config.email_to.strip(),
        agent_name=normalize_schedule_agent(config.agent_name),
        prompt_text=config.prompt_text.strip(),
        subject=config.subject.strip(),
        send_time_ist=validate_ist_time(config.send_time_ist),
        task_name=config.task_name.strip() or DEFAULT_TASK_NAME,
        edge_debugger_address=config.edge_debugger_address.strip() or "127.0.0.1:9222",
        copilot_url=config.copilot_url.strip() or "https://m365.cloud.microsoft/chat",
        outlook_mode=config.outlook_mode.strip().lower() or "send",
        response_timeout_seconds=int(config.response_timeout_seconds),
        response_stable_seconds=int(config.response_stable_seconds),
        keep_tab_open=bool(config.keep_tab_open),
        email_cc=config.email_cc.strip(),
    )


def load_schedule_config(config_path: Path) -> DailyScheduleConfig:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return normalize_config(DailyScheduleConfig(**payload))


def save_schedule_config(config_path: Path, config: DailyScheduleConfig) -> None:
    normalized = normalize_config(config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(asdict(normalized), indent=2), encoding="utf-8")


def load_schedule_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_schedule_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def current_ist_datetime() -> datetime:
    return datetime.now(tz=IST)
