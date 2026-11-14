"""Конфигурация приложения, читается из переменных окружения и .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Минимальная замена python-dotenv: KEY=VALUE, без перезаписи окружения."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    client_id: str
    client_secret: str
    dashboard_url: str
    host: str
    port: int
    db_path: Path
    log_level: str
    dev_guild_id: int | None
    session_ttl_days: int = 7

    @property
    def dashboard_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def secure_cookies(self) -> bool:
        return self.dashboard_url.startswith("https://")

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.dashboard_url.rstrip('/')}/auth/callback"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        raw_dev_guild = _env("DEV_GUILD_ID")
        raw_db = _env("DATABASE_PATH", "data/bot.db") or "data/bot.db"
        db_path = Path(raw_db)
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path
        return cls(
            token=_env("DISCORD_TOKEN"),
            client_id=_env("DISCORD_CLIENT_ID"),
            client_secret=_env("DISCORD_CLIENT_SECRET"),
            dashboard_url=(_env("DASHBOARD_URL", "http://localhost:8000") or "http://localhost:8000").rstrip("/"),
            host=_env("DASHBOARD_HOST", "0.0.0.0") or "0.0.0.0",
            port=_int_env("DASHBOARD_PORT", 8000),
            db_path=db_path,
            log_level=_env("LOG_LEVEL", "INFO").upper() or "INFO",
            dev_guild_id=int(raw_dev_guild) if raw_dev_guild.isdigit() else None,
            session_ttl_days=max(1, _int_env("SESSION_TTL_DAYS", 7)),
        )
