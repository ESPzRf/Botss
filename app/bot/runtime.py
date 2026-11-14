"""Контейнер времени выполнения: настройки, БД, репозиторий и ссылка на бота."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.database import Database
from app.core.models import GuildConfig
from app.core.repository import Repository
from app.core.utils import utcnow
from app.settings import Settings

if TYPE_CHECKING:
    import discord

    from app.bot.client import ModerationBot

CONFIG_TTL = 30.0


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.repo = Repository(self.db)
        self.bot: "ModerationBot | None" = None
        self.started_at: datetime = utcnow()
        self._config_cache: dict[int, tuple[float, GuildConfig]] = {}
        self._config_lock = asyncio.Lock()

    @property
    def bot_ready(self) -> bool:
        return self.bot is not None and self.bot.is_ready()

    @property
    def uptime_seconds(self) -> int:
        return int((utcnow() - self.started_at).total_seconds())

    async def config(
        self,
        guild: "discord.Guild | int",
        *,
        refresh: bool = False,
        name: str = "",
        icon: str | None = None,
    ) -> GuildConfig:
        if isinstance(guild, int):
            guild_id = guild
        else:
            guild_id = guild.id
            name = guild.name
            icon = guild.icon.url if guild.icon else None

        if not refresh:
            cached = self._config_cache.get(guild_id)
            if cached and time.monotonic() - cached[0] < CONFIG_TTL:
                return cached[1]

        async with self._config_lock:
            if not refresh:
                cached = self._config_cache.get(guild_id)
                if cached and time.monotonic() - cached[0] < CONFIG_TTL:
                    return cached[1]
            config = await self.repo.ensure_guild(guild_id, name, icon)
            self._config_cache[guild_id] = (time.monotonic(), config)
            return config

    def invalidate_config(self, guild_id: int) -> None:
        self._config_cache.pop(guild_id, None)

    def ready_guild(self, guild_id: int) -> "discord.Guild | None":
        if not self.bot_ready:
            return None
        return self.bot.get_guild(guild_id) if self.bot else None

    async def close(self) -> None:
        if self.bot and not self.bot.is_closed():
            await self.bot.close()
        await self.db.close()

    def __repr__(self) -> str:  # pragma: no cover - отладочное
        return f"<Runtime bot_ready={self.bot_ready} db={self.settings.db_path}>"
