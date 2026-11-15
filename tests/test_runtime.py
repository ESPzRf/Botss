"""Тесты фоновых задач и кэша достижений."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from pathlib import Path

from app.bot.runtime import Runtime
from app.settings import Settings


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = Path("data")
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / f"runtime-{uuid.uuid4().hex}.db"
        self.runtime = Runtime(
            Settings(
                token="",
                client_id="",
                client_secret="",
                dashboard_url="http://localhost:8000",
                host="127.0.0.1",
                port=8000,
                db_path=self.db_path,
                log_level="INFO",
                dev_guild_id=None,
            )
        )
        await self.runtime.db.connect()

    async def asyncTearDown(self) -> None:
        await self.runtime.shutdown_tasks()
        await self.runtime.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.db_path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass

    async def test_spawn_runs_and_shutdown_closes(self) -> None:
        event = asyncio.Event()

        async def worker() -> None:
            event.set()

        task = self.runtime.spawn(worker(), name="test-worker")
        self.assertIsNotNone(task)
        await asyncio.wait_for(event.wait(), timeout=2)
        await self.runtime.shutdown_tasks()
        self.assertTrue(self.runtime._closing)  # noqa: SLF001

    async def test_achievements_cache_invalidates(self) -> None:
        await self.runtime.repo.ensure_guild(100, "Test")
        first = await self.runtime.achievements(100)
        self.assertEqual(len(first), 9)

        await self.runtime.repo.create_achievement(
            100,
            title="Новое",
            description="",
            emoji="🔥",
            condition_type="messages",
            threshold=500,
        )
        cached = await self.runtime.achievements(100)
        self.assertEqual(len(cached), 9)

        self.runtime.invalidate_achievements(100)
        refreshed = await self.runtime.achievements(100)
        self.assertEqual(len(refreshed), 10)


if __name__ == "__main__":
    unittest.main()
