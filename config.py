from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


def _as_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    discord_token: str
    discord_client_id: str
    discord_guild_id: str
    discord_alert_channel_id: str
    discord_webhook_url: str
    track_interval_minutes: float
    alert_threshold_percent: float
    futbin_request_timeout_seconds: int
    futbin_max_retries: int
    database_path: str
    log_level: str


def load_config() -> Config:
    return Config(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
        discord_guild_id=os.getenv("DISCORD_GUILD_ID", ""),
        discord_alert_channel_id=os.getenv("DISCORD_ALERT_CHANNEL_ID", ""),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        track_interval_minutes=_as_float("TRACK_INTERVAL_MINUTES", 8),
        alert_threshold_percent=_as_float("ALERT_THRESHOLD_PERCENT", 5),
        futbin_request_timeout_seconds=_as_int("FUTBIN_REQUEST_TIMEOUT_SECONDS", 12),
        futbin_max_retries=_as_int("FUTBIN_MAX_RETRIES", 4),
        database_path=os.getenv("DATABASE_PATH", "./data/tracker.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
