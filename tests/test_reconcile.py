"""Тесты сверки активных наказаний с состоянием Discord."""

from __future__ import annotations

import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from app.bot.runtime import Runtime
from app.bot.services.moderation import reconcile_guild
from app.core.models import CASE_MUTE, CASE_TIMEOUT
from app.core.utils import to_iso, utcnow
from app.settings import Settings


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _Member:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.roles: list[_Role] = []
        self.timed_out_until = None


class _Guild:
    def __init__(self, member: _Member, role: _Role | None = None) -> None:
        self.id = 100
        self.name = "Test"
        self.icon = None
        self.member = member
        self.role = role

    def get_member(self, user_id: int):
        return self.member if user_id == self.member.id else None

    def get_role(self, role_id: int):
        return self.role if self.role is not None and self.role.id == role_id else None


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        base = Path("data")
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = base / f"reconcile-{uuid.uuid4().hex}.db"
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
        self.runtime.bot = SimpleNamespace(user=SimpleNamespace(id=999))  # type: ignore[assignment]
        await self.runtime.db.connect()
        await self.runtime.repo.ensure_guild(100, "Test")

    async def asyncTearDown(self) -> None:
        await self.runtime.shutdown_tasks()
        await self.runtime.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.db_path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass

    async def test_removed_timeout_is_closed(self) -> None:
        case = await self.runtime.repo.create_case(
            100,
            1,
            999,
            CASE_TIMEOUT,
            "Флуд",
            expires_at=to_iso(utcnow() + timedelta(hours=1)),
        )
        member = _Member(1)
        guild = _Guild(member)

        closed = await reconcile_guild(
            self.runtime, guild, grace_seconds=0, check_bans=False  # type: ignore[arg-type]
        )

        self.assertEqual(closed, 1)
        refreshed = await self.runtime.repo.get_case(case.id)
        self.assertIsNotNone(refreshed)
        self.assertFalse(refreshed.active)  # type: ignore[union-attr]
        self.assertEqual(refreshed.end_reason, "Тайм-аут снят вручную")  # type: ignore[union-attr]

    async def test_removed_mute_role_is_closed(self) -> None:
        role = _Role(55)
        await self.runtime.repo.update_settings(100, mute_role_id=55)
        self.runtime.invalidate_config(100)
        case = await self.runtime.repo.create_case(
            100,
            1,
            999,
            CASE_MUTE,
            "Мут",
            expires_at=to_iso(utcnow() + timedelta(hours=1)),
            extra={"role_id": role.id},
        )
        member = _Member(1)
        guild = _Guild(member, role)

        closed = await reconcile_guild(
            self.runtime, guild, grace_seconds=0, check_bans=False  # type: ignore[arg-type]
        )

        self.assertEqual(closed, 1)
        refreshed = await self.runtime.repo.get_case(case.id)
        self.assertFalse(refreshed.active)  # type: ignore[union-attr]
        self.assertEqual(refreshed.end_reason, "Мут снят вручную")  # type: ignore[union-attr]

    async def test_active_timeout_is_kept(self) -> None:
        case = await self.runtime.repo.create_case(
            100,
            1,
            999,
            CASE_TIMEOUT,
            "Флуд",
            expires_at=to_iso(utcnow() + timedelta(hours=1)),
        )
        member = _Member(1)
        member.timed_out_until = utcnow() + timedelta(hours=1)
        guild = _Guild(member)

        closed = await reconcile_guild(
            self.runtime, guild, grace_seconds=0, check_bans=False  # type: ignore[arg-type]
        )

        self.assertEqual(closed, 0)
        refreshed = await self.runtime.repo.get_case(case.id)
        self.assertTrue(refreshed.active)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
