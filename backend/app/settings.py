from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    frontend_origins: tuple[str, ...]
    propline_api_key: str
    propline_base_url: str
    propline_timeout_seconds: float
    slate_timezone: str
    cron_job_secret: str

    @property
    def slate_zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.slate_timezone)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise SettingsError(f"{name} is not configured.")
    return value.strip()


def _optional(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _frontend_origins() -> tuple[str, ...]:
    raw_value = _optional("FRONTEND_ORIGINS", "http://localhost:3000")
    return tuple(
        origin.strip()
        for origin in raw_value.split(",")
        if origin.strip()
    )


def _timeout_seconds() -> float:
    raw_value = _optional("PROPLINE_TIMEOUT_SECONDS", "30")
    try:
        timeout = float(raw_value)
    except ValueError as exc:
        raise SettingsError(
            "PROPLINE_TIMEOUT_SECONDS must be numeric."
        ) from exc

    if timeout <= 0:
        raise SettingsError("PROPLINE_TIMEOUT_SECONDS must be positive.")

    return timeout


def _slate_timezone() -> str:
    value = _optional("SLATE_TIMEZONE", "America/New_York")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise SettingsError(f"SLATE_TIMEZONE is invalid: {value}") from exc
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings(
        supabase_url=_required("SUPABASE_URL"),
        supabase_secret_key=_required("SUPABASE_SECRET_KEY"),
        frontend_origins=_frontend_origins(),
        propline_api_key=_required("PROPLINE_API_KEY"),
        propline_base_url=_optional(
            "PROPLINE_BASE_URL",
            "https://api.prop-line.com/v1",
        ).rstrip("/"),
        propline_timeout_seconds=_timeout_seconds(),
        slate_timezone=_slate_timezone(),
        cron_job_secret=_optional("CRON_JOB_SECRET", ""),
    )


@lru_cache
def get_api_settings() -> Settings:
    """Settings needed by the FastAPI app without requiring PropLine config."""
    return Settings(
        supabase_url=os.getenv("SUPABASE_URL", "").strip(),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY", "").strip(),
        frontend_origins=_frontend_origins(),
        propline_api_key=os.getenv("PROPLINE_API_KEY", "").strip(),
        propline_base_url=_optional(
            "PROPLINE_BASE_URL",
            "https://api.prop-line.com/v1",
        ).rstrip("/"),
        propline_timeout_seconds=_timeout_seconds(),
        slate_timezone=_slate_timezone(),
        cron_job_secret=os.getenv("CRON_JOB_SECRET", "").strip(),
    )
