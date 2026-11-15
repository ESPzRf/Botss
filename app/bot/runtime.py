"""Контейнер времени выполнения: настройки, БД, репозиторий и ссылка на бота."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Coroutine

from app.core.database import Database
from app.core.models import Achievement, GuildConfig
from app.core.repository import Repository
from app.core.utils import utcnow
from app.settings import Settings

if TYPE_CHECKING:
    import discord

    from app.bot.client import ModerationBot

logger = logging.getLogger(__name__)

CONFIG_TTL = 30.0
ACHIEVEMENTS_TTL = 60.0
MAX_BACKGROUND_TASKS = 1000


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.repo = Repository(self.db)
        self.bot: "ModerationBot | None" = None
        self.started_at: datetime = utcnow()
        self._config_cache: dict[int, tuple[float, GuildConfig]] = {}
        self._config_lock = asyncio.Lock()
        self._achievements_cache: dict[int, tuple[float, list[Achievement]]] = {}
        self._achievements_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._closing = False

    @property
    def bot_ready(self) -> bool:
        return self.bot is not None and self.bot.is_ready()

    @property
    def uptime_seconds(self) -> int:
        return int((utcnow() - self.started_at).total_seconds())

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task | None:
        """Запускает некритичную операцию в фоне.

        Используется для отправки логов и личных сообщений, чтобы команда
        не ждала сетевой ответ Discord.
        """
        if self._closing:
            coro.close()
            return None
        if len(self._tasks) >= MAX_BACKGROUND_TASKS:
            coro.close()
            logger.warning("Очередь фоновых задач переполнена, операция пропущена")
            return None
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Фоновая задача %s завершилась с ошибкой",
                task.get_name(),
                exc_info=(type(error), error, error.__traceback__),
            )

    async def shutdown_tasks(self, timeout: float = 5.0) -> None:
        """Даёт фоновым задачам завершиться и отменяет оставшиеся."""
        self._closing = True
        tasks = list(self._tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.difference_update(tasks)

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

    async def achievements(self, guild_id: int, *, refresh: bool = False) -> list[Achievement]:
        if not refresh:
            cached = self._achievements_cache.get(guild_id)
            if cached and time.monotonic() - cached[0] < ACHIEVEMENTS_TTL:
                return cached[1]
        async with self._achievements_lock:
            if not refresh:
                cached = self._achievements_cache.get(guild_id)
                if cached and time.monotonic() - cached[0] < ACHIEVEMENTS_TTL:
                    return cached[1]
            items = await self.repo.list_achievements(guild_id, enabled_only=True)
            self._achievements_cache[guild_id] = (time.monotonic(), items)
            return items

    def invalidate_achievements(self, guild_id: int) -> None:
        self._achievements_cache.pop(guild_id, None)

    def ready_guild(self, guild_id: int) -> "discord.Guild | None":
        if not self.bot_ready:
            return None
        return self.bot.get_guild(guild_id) if self.bot else None

    async def close(self) -> None:
        await self.shutdown_tasks()
        if self.bot and not self.bot.is_closed():
            await self.bot.close()
        await self.db.close()

    def __repr__(self) -> str:  # pragma: no cover - отладочное
        return f"<Runtime bot_ready={self.bot_ready} db={self.settings.db_path}>"
