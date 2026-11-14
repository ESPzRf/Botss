"""Интеграционные тесты репозитория на временной SQLite."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from app.core.database import Database
from app.core.repository import Repository


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = Path("data")
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / f"guardian-test-{uuid.uuid4().hex}.db"
        self.db = Database(self.db_path)
        await self.db.connect()
        self.repo = Repository(self.db)
        self.config = await self.repo.ensure_guild(100, "Test Guild")

    async def asyncTearDown(self) -> None:
        await self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                (Path(str(self.db_path) + suffix)).unlink(missing_ok=True)
            except OSError:
                pass

    async def test_defaults_and_settings(self) -> None:
        self.assertEqual(self.config.guild_id, 100)
        self.assertTrue(self.config.xp_enabled)
        self.assertFalse(self.config.restore_roles)
        self.assertTrue(self.config.event_enabled("member_join"))
        self.assertFalse(self.config.event_enabled("voice_move"))
        self.assertEqual(len(await self.repo.list_achievements(100)), 9)

        await self.repo.update_settings(
            100,
            log_channel_id=555,
            events={"member_join": True, "voice_join": False},
            autorole_ids=[1, 2],
        )
        config = await self.repo.get_config(100)
        assert config is not None
        self.assertEqual(config.log_channel_id, 555)
        self.assertTrue(config.event_enabled("member_join"))
        self.assertFalse(config.event_enabled("voice_join"))
        self.assertEqual(config.autorole_ids, [1, 2])

    async def test_warnings(self) -> None:
        warning = await self.repo.add_warning(100, 200, 300, "Спам")
        self.assertEqual(warning.id, 1)
        self.assertEqual(await self.repo.count_active_warnings(100, 200), 1)
        self.assertTrue(await self.repo.deactivate_warning(1, 300, "Ошибка"))
        self.assertFalse(await self.repo.deactivate_warning(1, 300))
        self.assertEqual(await self.repo.count_active_warnings(100, 200), 0)

    async def test_cases_and_due(self) -> None:
        case = await self.repo.create_case(
            100,
            200,
            300,
            "timeout",
            "Флуд",
            expires_at="2000-01-01T00:00:00+00:00",
        )
        self.assertTrue(case.active)
        due = await self.repo.due_cases()
        self.assertEqual([item.id for item in due], [case.id])
        self.assertTrue(await self.repo.close_case(case.id, 999, "Истёк"))
        self.assertFalse((await self.repo.get_case(case.id)).active)  # type: ignore[union-attr]

    async def test_close_active_cases(self) -> None:
        first = await self.repo.create_case(100, 200, 300, "timeout", "Первый")
        second = await self.repo.create_case(100, 200, 300, "timeout", "Второй")
        await self.repo.create_case(100, 200, 300, "ban", "Другой тип")
        closed = await self.repo.close_active_cases(
            100, 200, ("timeout",), 300, "Заменено новым наказанием"
        )
        self.assertEqual(closed, 2)
        self.assertFalse((await self.repo.get_case(first.id)).active)  # type: ignore[union-attr]
        self.assertFalse((await self.repo.get_case(second.id)).active)  # type: ignore[union-attr]
        active = await self.repo.active_case(100, 200, ("ban",))
        self.assertIsNotNone(active)

    async def test_progress_and_levels(self) -> None:
        stats, old_level = await self.repo.add_message_progress(100, 200, 100, 5)
        self.assertEqual(old_level, 0)
        self.assertEqual(stats.level, 1)
        self.assertEqual(stats.xp, 100)
        self.assertEqual(stats.messages, 1)
        self.assertEqual(stats.loyalty, 5)

        stats, old_level = await self.repo.add_voice_progress(100, 200, 50, 3, 120)
        self.assertEqual(old_level, 1)
        self.assertEqual(stats.voice_minutes, 2)
        self.assertEqual(stats.xp, 150)
        self.assertEqual(await self.repo.rank_position(100, 200), 1)

    async def test_shop_purchase_and_refund(self) -> None:
        item = await self.repo.create_shop_item(
            100, role_id=5, name="VIP", description="", price=40, stock=2
        )
        await self.repo.add_loyalty(100, 200, 100)
        purchased, status = await self.repo.purchase_item(100, 200, item.id)
        self.assertEqual(status, "ok")
        self.assertIsNotNone(purchased)
        stats = await self.repo.get_stats(100, 200)
        self.assertEqual(stats.loyalty, 60)
        self.assertEqual((await self.repo.get_shop_item(item.id)).stock, 1)  # type: ignore[union-attr]

        await self.repo.refund_purchase(100, 200, item.id)
        self.assertEqual((await self.repo.get_stats(100, 200)).loyalty, 100)
        self.assertEqual((await self.repo.get_shop_item(item.id)).stock, 2)  # type: ignore[union-attr]

    async def test_loyalty_take(self) -> None:
        await self.repo.add_loyalty(100, 200, 50)
        await self.repo.add_loyalty(100, 200, -20)
        self.assertEqual((await self.repo.get_stats(100, 200)).loyalty, 30)
        await self.repo.add_loyalty(100, 200, -100)
        self.assertEqual((await self.repo.get_stats(100, 200)).loyalty, 0)
        await self.repo.add_loyalty(100, 300, -10)
        self.assertEqual((await self.repo.get_stats(100, 300)).loyalty, 0)

    async def test_panels(self) -> None:
        panel = await self.repo.create_panel(
            100, 555, "Роли", "Выберите", "toggle", 300, [(1, "A", None, 2), (2, "B", None, 2)]
        )
        self.assertEqual(len(await self.repo.list_panel_options(panel.id)), 2)
        added = await self.repo.add_panel_option(panel.id, 3, label="C")
        self.assertIsNotNone(added)
        self.assertEqual(added.position, 2)  # type: ignore[union-attr]
        self.assertTrue(await self.repo.delete_panel_option(panel.id, 3))
        self.assertEqual(len(await self.repo.list_panel_options(panel.id)), 2)
        await self.repo.set_panel_message(panel.id, 777)
        found = await self.repo.panel_by_message(777)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, panel.id)  # type: ignore[union-attr]

    async def test_remove_role_references(self) -> None:
        panel = await self.repo.create_panel(
            100, 555, "Роли", "", "toggle", 300, [(7, "Role", None, 2)]
        )
        achievement = await self.repo.create_achievement(
            100,
            title="Тест",
            description="",
            emoji="🏆",
            condition_type="messages",
            threshold=1,
            reward_role_id=7,
        )
        await self.repo.create_shop_item(
            100, role_id=7, name="Товар", description="", price=10, stock=-1
        )
        await self.repo.update_settings(100, autorole_ids=[7, 8], level_roles=[{"level": 5, "role_id": 7}])
        panel_ids = await self.repo.remove_role_references(100, 7)
        self.assertEqual(panel_ids, [panel.id])
        self.assertEqual(await self.repo.list_panel_options(panel.id), [])
        self.assertIsNone((await self.repo.get_achievement(achievement.id)).reward_role_id)  # type: ignore[union-attr]
        self.assertEqual(await self.repo.list_shop_items(100), [])
        config = await self.repo.get_config(100)
        assert config is not None
        self.assertEqual(config.autorole_ids, [8])
        self.assertEqual(config.level_roles, [])

    async def test_sessions(self) -> None:
        session = await self.repo.create_session(
            user_id=1,
            username="Alice",
            avatar=None,
            guilds=[{"id": "100", "permissions": 32, "owner": False}],
            access_token="token",
            refresh_token=None,
        )
        loaded = await self.repo.get_session(session.token)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertTrue(loaded.can_manage(100))
        self.assertFalse(loaded.can_manage(101))
        await self.repo.delete_session(session.token)
        self.assertIsNone(await self.repo.get_session(session.token))


if __name__ == "__main__":
    unittest.main()
