"""Проверка, что все коги загружаются и регистрируют команды."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from app.bot.client import COG_EXTENSIONS, ModerationBot
from app.bot.runtime import Runtime
from app.settings import Settings


class CogLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = Path("data")
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / f"cogs-{uuid.uuid4().hex}.db"
        settings = Settings(
            token="",
            client_id="",
            client_secret="",
            dashboard_url="http://test",
            host="127.0.0.1",
            port=8000,
            db_path=self.db_path,
            log_level="INFO",
            dev_guild_id=None,
        )
        self.runtime = Runtime(settings)
        await self.runtime.db.connect()
        self.bot = ModerationBot(self.runtime)
        self.runtime.bot = self.bot
        for extension in COG_EXTENSIONS:
            await self.bot.load_extension(extension)

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        await self.runtime.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.db_path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass

    async def test_expected_commands_are_registered(self) -> None:
        names = {command.name for command in self.bot.tree.get_commands()}
        expected = {
            "help",
            "warn",
            "timeout",
            "ban",
            "kick",
            "purge",
            "rank",
            "leaderboard",
            "achievements",
            "balance",
            "panel",
            "xp",
            "loyalty",
            "shop",
        }
        self.assertTrue(expected.issubset(names), expected - names)
        self.assertEqual(len(self.bot.cogs), 10)

    async def test_cogs_have_no_duplicate_top_level_names(self) -> None:
        names = [command.name for command in self.bot.tree.get_commands()]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
