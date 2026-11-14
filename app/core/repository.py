"""Репозиторий: все SQL-запросы приложения в одном месте."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any, Iterable, Sequence

from app.core.database import Database
from app.core.defaults import DEFAULT_ACHIEVEMENTS
from app.core.levels import level_for_xp
from app.core.models import (
    Achievement,
    Case,
    GuildConfig,
    MemberStats,
    PanelOption,
    RolePanel,
    ShopItem,
    Warning,
    WebSession,
)
from app.core.utils import now_iso, utcnow

_SETTING_COLUMNS: dict[str, str] = {
    "name": "name",
    "icon": "icon",
    "log_channel_id": "log_channel_id",
    "mod_log_channel_id": "mod_log_channel_id",
    "events": "events_json",
    "ignore_channels": "ignore_channels_json",
    "ignore_users": "ignore_users_json",
    "autorole_ids": "autorole_ids_json",
    "autorole_bots": "autorole_bots",
    "restore_roles": "restore_roles",
    "mute_role_id": "mute_role_id",
    "escalations": "escalations_json",
    "xp_enabled": "xp_enabled",
    "xp_min": "xp_min",
    "xp_max": "xp_max",
    "xp_cooldown": "xp_cooldown",
    "xp_voice_per_min": "xp_voice_per_min",
    "xp_ignore_channels": "xp_ignore_channels_json",
    "xp_ignore_roles": "xp_ignore_roles_json",
    "level_up_channel_id": "level_up_channel_id",
    "level_up_message": "level_up_message",
    "level_roles": "level_roles_json",
    "loyalty_enabled": "loyalty_enabled",
    "loyalty_per_message": "loyalty_per_message",
    "loyalty_per_voice_min": "loyalty_per_voice_min",
    "achievements_enabled": "achievements_enabled",
    "achievements_channel_id": "achievements_channel_id",
    "shop_enabled": "shop_enabled",
}
_JSON_SETTINGS = {
    "events",
    "ignore_channels",
    "ignore_users",
    "autorole_ids",
    "escalations",
    "xp_ignore_channels",
    "xp_ignore_roles",
    "level_roles",
}
_BOOL_SETTINGS = {
    "autorole_bots",
    "restore_roles",
    "xp_enabled",
    "loyalty_enabled",
    "achievements_enabled",
    "shop_enabled",
}


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Настройки сервера ────────────────────────────────────────────────────

    async def ensure_guild(
        self, guild_id: int, name: str = "", icon: str | None = None
    ) -> GuildConfig:
        row = await self.db.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        if row is None:
            timestamp = now_iso()
            try:
                await self.db.execute(
                    "INSERT INTO guild_settings (guild_id, name, icon, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (guild_id, name, icon, timestamp, timestamp),
                )
            except sqlite3.IntegrityError:
                pass
            await self._seed_achievements(guild_id)
            row = await self.db.fetchone(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
        if row is None:
            raise RuntimeError(f"Не удалось создать настройки для сервера {guild_id}")
        return GuildConfig.from_row(row)

    async def _seed_achievements(self, guild_id: int) -> None:
        timestamp = now_iso()
        rows = [
            (
                guild_id,
                item["code"],
                item["title"],
                item["description"],
                item["emoji"],
                item["condition_type"],
                item["threshold"],
                None,
                item.get("reward_loyalty", 0),
                1,
                timestamp,
            )
            for item in DEFAULT_ACHIEVEMENTS
        ]
        await self.db.executemany(
            "INSERT OR IGNORE INTO achievements"
            " (guild_id, code, title, description, emoji, condition_type, threshold,"
            "  reward_role_id, reward_loyalty, enabled, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    async def get_config(self, guild_id: int) -> GuildConfig | None:
        row = await self.db.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        return GuildConfig.from_row(row) if row else None

    async def list_guilds(self) -> list[GuildConfig]:
        rows = await self.db.fetchall("SELECT * FROM guild_settings ORDER BY name COLLATE NOCASE")
        return [GuildConfig.from_row(row) for row in rows]

    async def touch_guild_meta(self, guild_id: int, name: str, icon: str | None) -> None:
        await self.db.execute_count(
            "UPDATE guild_settings SET name = ?, icon = ? WHERE guild_id = ?"
            " AND (name <> ? OR IFNULL(icon, '') <> IFNULL(?, ''))",
            (name, icon, guild_id, name, icon),
        )

    async def update_settings(self, guild_id: int, **fields: Any) -> GuildConfig:
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            column = _SETTING_COLUMNS.get(key)
            if column is None:
                raise ValueError(f"Неизвестная настройка: {key}")
            if key in _JSON_SETTINGS:
                value = json.dumps(value, ensure_ascii=False)
            elif key in _BOOL_SETTINGS:
                value = int(bool(value))
            assignments.append(f"{column} = ?")
            params.append(value)
        if not assignments:
            config = await self.get_config(guild_id)
            if config is None:
                raise LookupError("Сервер не найден")
            return config
        assignments.append("updated_at = ?")
        params.append(now_iso())
        params.append(guild_id)
        await self.db.execute_count(
            f"UPDATE guild_settings SET {', '.join(assignments)} WHERE guild_id = ?",
            tuple(params),
        )
        config = await self.get_config(guild_id)
        if config is None:
            raise LookupError("Сервер не найден")
        return config

    async def guild_counters(self, guild_id: int) -> dict[str, int]:
        warnings = await self.db.scalar(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND active = 1", (guild_id,)
        )
        active_cases = await self.db.scalar(
            "SELECT COUNT(*) FROM cases WHERE guild_id = ? AND active = 1", (guild_id,)
        )
        tracked = await self.db.scalar(
            "SELECT COUNT(*) FROM member_stats WHERE guild_id = ?", (guild_id,)
        )
        achievements = await self.db.scalar(
            "SELECT COUNT(*) FROM achievements WHERE guild_id = ? AND enabled = 1", (guild_id,)
        )
        return {
            "warnings": int(warnings),
            "active_cases": int(active_cases),
            "tracked": int(tracked),
            "achievements": int(achievements),
        }

    # ── Предупреждения ───────────────────────────────────────────────────────

    async def add_warning(
        self, guild_id: int, user_id: int, moderator_id: int, reason: str
    ) -> Warning:
        timestamp = now_iso()
        warning_id = await self.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, timestamp),
        )
        row = await self.db.fetchone("SELECT * FROM warnings WHERE id = ?", (warning_id,))
        assert row is not None
        return Warning.from_row(row)

    async def get_warning(self, warning_id: int) -> Warning | None:
        row = await self.db.fetchone("SELECT * FROM warnings WHERE id = ?", (warning_id,))
        return Warning.from_row(row) if row else None

    async def count_active_warnings(self, guild_id: int, user_id: int) -> int:
        value = await self.db.scalar(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ? AND active = 1",
            (guild_id, user_id),
        )
        return int(value)

    async def list_warnings(
        self,
        guild_id: int,
        *,
        user_id: int | None = None,
        active_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Warning]:
        conditions = ["guild_id = ?"]
        params: list[Any] = [guild_id]
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if active_only:
            conditions.append("active = 1")
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            "SELECT * FROM warnings WHERE "
            + " AND ".join(conditions)
            + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [Warning.from_row(row) for row in rows]

    async def deactivate_warning(
        self, warning_id: int, moderator_id: int, reason: str = ""
    ) -> bool:
        changed = await self.db.execute_count(
            "UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?, removed_reason = ?"
            " WHERE id = ? AND active = 1",
            (moderator_id, now_iso(), reason, warning_id),
        )
        return changed > 0

    async def clear_warnings(self, guild_id: int, user_id: int, moderator_id: int) -> int:
        return await self.db.execute_count(
            "UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?,"
            " removed_reason = 'Очистка всех предупреждений'"
            " WHERE guild_id = ? AND user_id = ? AND active = 1",
            (moderator_id, now_iso(), guild_id, user_id),
        )

    # ── Наказания ────────────────────────────────────────────────────────────

    async def create_case(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        kind: str,
        reason: str,
        *,
        expires_at: str | None = None,
        extra: dict[str, Any] | None = None,
        active: bool = True,
    ) -> Case:
        timestamp = now_iso()
        case_id = await self.db.execute(
            "INSERT INTO cases (guild_id, user_id, moderator_id, kind, reason, created_at,"
            " expires_at, active, ended_at, ended_by, end_reason, extra_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                user_id,
                moderator_id,
                kind,
                reason,
                timestamp,
                expires_at,
                int(active),
                None if active else timestamp,
                None if active else moderator_id,
                None if active else "Наказание не требует снятия",
                json.dumps(extra or {}, ensure_ascii=False),
            ),
        )
        row = await self.db.fetchone("SELECT * FROM cases WHERE id = ?", (case_id,))
        assert row is not None
        return Case.from_row(row)

    async def get_case(self, case_id: int, guild_id: int | None = None) -> Case | None:
        if guild_id is None:
            row = await self.db.fetchone("SELECT * FROM cases WHERE id = ?", (case_id,))
        else:
            row = await self.db.fetchone(
                "SELECT * FROM cases WHERE id = ? AND guild_id = ?", (case_id, guild_id)
            )
        return Case.from_row(row) if row else None

    async def list_cases(
        self,
        guild_id: int,
        *,
        user_id: int | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Case]:
        conditions = ["guild_id = ?"]
        params: list[Any] = [guild_id]
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if active is not None:
            conditions.append("active = ?")
            params.append(int(active))
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            "SELECT * FROM cases WHERE "
            + " AND ".join(conditions)
            + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [Case.from_row(row) for row in rows]

    async def due_cases(self, limit: int = 100) -> list[Case]:
        rows = await self.db.fetchall(
            "SELECT * FROM cases WHERE active = 1 AND expires_at IS NOT NULL"
            " AND expires_at <= ? ORDER BY expires_at LIMIT ?",
            (now_iso(), limit),
        )
        return [Case.from_row(row) for row in rows]

    async def active_case(
        self, guild_id: int, user_id: int, kinds: Sequence[str] | None = None
    ) -> Case | None:
        params: list[Any] = [guild_id, user_id]
        query = "SELECT * FROM cases WHERE guild_id = ? AND user_id = ? AND active = 1"
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            query += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        query += " ORDER BY id DESC LIMIT 1"
        row = await self.db.fetchone(query, tuple(params))
        return Case.from_row(row) if row else None

    async def close_case(
        self, case_id: int, ended_by: int | None, reason: str = ""
    ) -> bool:
        changed = await self.db.execute_count(
            "UPDATE cases SET active = 0, ended_at = ?, ended_by = ?, end_reason = ?"
            " WHERE id = ? AND active = 1",
            (now_iso(), ended_by, reason, case_id),
        )
        return changed > 0

    async def close_active_cases(
        self,
        guild_id: int,
        user_id: int,
        kinds: Sequence[str],
        ended_by: int | None,
        reason: str,
    ) -> int:
        if not kinds:
            return 0
        placeholders = ",".join("?" for _ in kinds)
        params: list[Any] = [now_iso(), ended_by, reason, guild_id, user_id, *kinds]
        return await self.db.execute_count(
            "UPDATE cases SET active = 0, ended_at = ?, ended_by = ?, end_reason = ?"
            f" WHERE guild_id = ? AND user_id = ? AND active = 1 AND kind IN ({placeholders})",
            tuple(params),
        )

    async def update_case_reason(self, case_id: int, reason: str) -> bool:
        changed = await self.db.execute_count(
            "UPDATE cases SET reason = ? WHERE id = ?", (reason, case_id)
        )
        return changed > 0

    async def count_active_cases(self, guild_id: int) -> int:
        return int(
            await self.db.scalar(
                "SELECT COUNT(*) FROM cases WHERE guild_id = ? AND active = 1", (guild_id,)
            )
        )

    # ── Опыт и лояльность ────────────────────────────────────────────────────

    async def get_stats(self, guild_id: int, user_id: int) -> MemberStats:
        row = await self.db.fetchone(
            "SELECT * FROM member_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row:
            return MemberStats.from_row(row)
        return MemberStats(guild_id=guild_id, user_id=user_id, updated_at=now_iso())

    async def _progress(
        self,
        guild_id: int,
        user_id: int,
        *,
        xp_amount: int,
        loyalty_amount: int,
        seconds: int,
        messages: int,
    ) -> tuple[MemberStats, int]:
        def operation(conn: sqlite3.Connection) -> tuple[MemberStats, int]:
            row = conn.execute(
                "SELECT xp, level FROM member_stats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            old_level = int(row["level"]) if row else 0
            old_xp = int(row["xp"]) if row else 0
            new_xp = max(0, old_xp + int(xp_amount))
            new_level = level_for_xp(new_xp)
            timestamp = now_iso()
            if row is None:
                conn.execute(
                    "INSERT INTO member_stats (guild_id, user_id, xp, level, messages,"
                    " voice_seconds, loyalty, last_xp_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        guild_id,
                        user_id,
                        new_xp,
                        new_level,
                        messages,
                        seconds,
                        max(0, loyalty_amount),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE member_stats SET xp = ?, level = ?, messages = messages + ?,"
                    " voice_seconds = voice_seconds + ?, loyalty = MAX(0, loyalty + ?),"
                    " last_xp_at = ?, updated_at = ?"
                    " WHERE guild_id = ? AND user_id = ?",
                    (
                        new_xp,
                        new_level,
                        messages,
                        seconds,
                        int(loyalty_amount),
                        timestamp,
                        timestamp,
                        guild_id,
                        user_id,
                    ),
                )
            updated = conn.execute(
                "SELECT * FROM member_stats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            assert updated is not None
            return MemberStats.from_row(updated), old_level

        return await self.db.run_tx(operation)

    async def add_message_progress(
        self, guild_id: int, user_id: int, xp_amount: int, loyalty_amount: int
    ) -> tuple[MemberStats, int]:
        return await self._progress(
            guild_id,
            user_id,
            xp_amount=xp_amount,
            loyalty_amount=loyalty_amount,
            seconds=0,
            messages=1,
        )

    async def add_voice_progress(
        self, guild_id: int, user_id: int, xp_amount: int, loyalty_amount: int, seconds: int
    ) -> tuple[MemberStats, int]:
        return await self._progress(
            guild_id,
            user_id,
            xp_amount=xp_amount,
            loyalty_amount=loyalty_amount,
            seconds=seconds,
            messages=0,
        )

    async def add_xp(self, guild_id: int, user_id: int, amount: int) -> tuple[MemberStats, int]:
        return await self._progress(
            guild_id,
            user_id,
            xp_amount=amount,
            loyalty_amount=0,
            seconds=0,
            messages=0,
        )

    async def add_loyalty(self, guild_id: int, user_id: int, amount: int) -> None:
        await self.db.execute_count(
            "INSERT INTO member_stats (guild_id, user_id, loyalty, updated_at)"
            " VALUES (?, ?, MAX(0, ?), ?)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET"
            " loyalty = MAX(0, member_stats.loyalty + ?), updated_at = excluded.updated_at",
            (guild_id, user_id, amount, now_iso(), amount),
        )

    async def spend_loyalty(self, guild_id: int, user_id: int, amount: int) -> bool:
        if amount <= 0:
            return False
        changed = await self.db.execute_count(
            "UPDATE member_stats SET loyalty = loyalty - ?, updated_at = ?"
            " WHERE guild_id = ? AND user_id = ? AND loyalty >= ?",
            (amount, now_iso(), guild_id, user_id, amount),
        )
        return changed > 0

    async def reset_stats(self, guild_id: int, user_id: int) -> None:
        await self.db.execute_count(
            "DELETE FROM member_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def leaderboard(
        self, guild_id: int, limit: int = 10, offset: int = 0
    ) -> list[MemberStats]:
        rows = await self.db.fetchall(
            "SELECT * FROM member_stats WHERE guild_id = ? AND xp > 0"
            " ORDER BY xp DESC, user_id ASC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )
        return [MemberStats.from_row(row) for row in rows]

    async def rank_position(self, guild_id: int, user_id: int) -> int:
        stats = await self.get_stats(guild_id, user_id)
        better = await self.db.scalar(
            "SELECT COUNT(*) FROM member_stats WHERE guild_id = ? AND xp > ?",
            (guild_id, stats.xp),
        )
        return int(better) + 1

    async def loyalty_leaderboard(self, guild_id: int, limit: int = 10) -> list[MemberStats]:
        rows = await self.db.fetchall(
            "SELECT * FROM member_stats WHERE guild_id = ? AND loyalty > 0"
            " ORDER BY loyalty DESC, user_id ASC LIMIT ?",
            (guild_id, limit),
        )
        return [MemberStats.from_row(row) for row in rows]

    async def list_tracked_stats(self, guild_id: int, limit: int = 10000) -> list[MemberStats]:
        rows = await self.db.fetchall(
            "SELECT * FROM member_stats WHERE guild_id = ? LIMIT ?", (guild_id, limit)
        )
        return [MemberStats.from_row(row) for row in rows]

    # ── Роли при выходе ──────────────────────────────────────────────────────

    async def save_member_roles(self, guild_id: int, user_id: int, role_ids: Iterable[int]) -> None:
        await self.db.execute(
            "INSERT INTO member_roles (guild_id, user_id, role_ids_json, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET"
            " role_ids_json = excluded.role_ids_json, updated_at = excluded.updated_at",
            (guild_id, user_id, json.dumps(list(role_ids)), now_iso()),
        )

    async def get_member_roles(self, guild_id: int, user_id: int) -> list[int]:
        row = await self.db.fetchone(
            "SELECT role_ids_json FROM member_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if not row:
            return []
        try:
            return [int(value) for value in json.loads(row["role_ids_json"])]
        except (TypeError, ValueError):
            return []

    async def clear_member_roles(self, guild_id: int, user_id: int) -> None:
        await self.db.execute_count(
            "DELETE FROM member_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    # ── Панели ролей ─────────────────────────────────────────────────────────

    async def create_panel(
        self,
        guild_id: int,
        channel_id: int,
        title: str,
        description: str,
        mode: str,
        created_by: int | None,
        options: list[tuple[int, str, str | None, int]],
    ) -> RolePanel:
        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO role_panels (guild_id, channel_id, message_id, title,"
                " description, mode, created_by, created_at) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (guild_id, channel_id, title, description, mode, created_by, now_iso()),
            )
            panel_id = int(cursor.lastrowid)
            for position, (role_id, label, emoji, style) in enumerate(options):
                conn.execute(
                    "INSERT OR IGNORE INTO role_panel_options"
                    " (panel_id, role_id, label, emoji, style, position) VALUES (?, ?, ?, ?, ?, ?)",
                    (panel_id, role_id, label, emoji, style, position),
                )
            return panel_id

        panel_id = await self.db.run_tx(operation)
        panel = await self.get_panel(panel_id)
        assert panel is not None
        return panel

    async def get_panel(self, panel_id: int) -> RolePanel | None:
        row = await self.db.fetchone("SELECT * FROM role_panels WHERE id = ?", (panel_id,))
        return RolePanel.from_row(row) if row else None

    async def set_panel_message(self, panel_id: int, message_id: int | None) -> None:
        await self.db.execute_count(
            "UPDATE role_panels SET message_id = ? WHERE id = ?", (message_id, panel_id)
        )

    async def list_panels(self, guild_id: int) -> list[RolePanel]:
        rows = await self.db.fetchall(
            "SELECT * FROM role_panels WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)
        )
        return [RolePanel.from_row(row) for row in rows]

    async def list_all_panels(self) -> list[RolePanel]:
        rows = await self.db.fetchall("SELECT * FROM role_panels ORDER BY id")
        return [RolePanel.from_row(row) for row in rows]

    async def delete_panel(self, panel_id: int) -> bool:
        changed = await self.db.execute_count("DELETE FROM role_panels WHERE id = ?", (panel_id,))
        return changed > 0

    async def panel_by_message(self, message_id: int) -> RolePanel | None:
        row = await self.db.fetchone(
            "SELECT * FROM role_panels WHERE message_id = ?", (message_id,)
        )
        return RolePanel.from_row(row) if row else None

    async def list_panel_options(self, panel_id: int) -> list[PanelOption]:
        rows = await self.db.fetchall(
            "SELECT * FROM role_panel_options WHERE panel_id = ? ORDER BY position, id",
            (panel_id,),
        )
        return [PanelOption.from_row(row) for row in rows]

    async def add_panel_option(
        self,
        panel_id: int,
        role_id: int,
        *,
        label: str = "",
        emoji: str | None = None,
        style: int = 2,
    ) -> PanelOption | None:
        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO role_panel_options"
                " (panel_id, role_id, label, emoji, style, position)"
                " VALUES (?, ?, ?, ?, ?, (SELECT IFNULL(MAX(position), 0) + 1"
                " FROM role_panel_options WHERE panel_id = ?))",
                (panel_id, role_id, label, emoji, style, panel_id),
            )
            return int(cursor.lastrowid or 0)

        option_id = await self.db.run_tx(operation)
        if not option_id:
            return None
        row = await self.db.fetchone(
            "SELECT * FROM role_panel_options WHERE id = ?", (option_id,)
        )
        return PanelOption.from_row(row) if row else None

    async def delete_panel_option(self, panel_id: int, role_id: int) -> bool:
        changed = await self.db.execute_count(
            "DELETE FROM role_panel_options WHERE panel_id = ? AND role_id = ?",
            (panel_id, role_id),
        )
        return changed > 0

    async def panel_ids_with_role(self, guild_id: int, role_id: int) -> list[int]:
        rows = await self.db.fetchall(
            "SELECT DISTINCT p.id FROM role_panels p"
            " JOIN role_panel_options o ON o.panel_id = p.id"
            " WHERE p.guild_id = ? AND o.role_id = ?",
            (guild_id, role_id),
        )
        return [int(row["id"]) for row in rows]

    async def remove_role_references(self, guild_id: int, role_id: int) -> list[int]:
        """Чистит ссылки на удалённую роль. Возвращает ID затронутых панелей."""

        def operation(conn: sqlite3.Connection) -> list[int]:
            panel_rows = conn.execute(
                "SELECT DISTINCT p.id FROM role_panels p"
                " JOIN role_panel_options o ON o.panel_id = p.id"
                " WHERE p.guild_id = ? AND o.role_id = ?",
                (guild_id, role_id),
            ).fetchall()
            panel_ids = [int(row["id"]) for row in panel_rows]

            settings = conn.execute(
                "SELECT autorole_ids_json, level_roles_json, mute_role_id"
                " FROM guild_settings WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            if settings is not None:
                try:
                    autoroles = [
                        int(v) for v in json.loads(settings["autorole_ids_json"]) if int(v) != role_id
                    ]
                except (TypeError, ValueError):
                    autoroles = []
                try:
                    level_roles = [
                        item
                        for item in json.loads(settings["level_roles_json"])
                        if int(item.get("role_id", 0)) != role_id
                    ]
                except (TypeError, ValueError, AttributeError):
                    level_roles = []
                mute_role_id = settings["mute_role_id"]
                conn.execute(
                    "UPDATE guild_settings SET autorole_ids_json = ?, level_roles_json = ?,"
                    " mute_role_id = ?, updated_at = ? WHERE guild_id = ?",
                    (
                        json.dumps(autoroles),
                        json.dumps(level_roles, ensure_ascii=False),
                        None if mute_role_id == role_id else mute_role_id,
                        now_iso(),
                        guild_id,
                    ),
                )

            conn.execute(
                "UPDATE achievements SET reward_role_id = NULL"
                " WHERE guild_id = ? AND reward_role_id = ?",
                (guild_id, role_id),
            )
            conn.execute(
                "DELETE FROM role_panel_options WHERE role_id = ? AND panel_id IN"
                " (SELECT id FROM role_panels WHERE guild_id = ?)",
                (role_id, guild_id),
            )
            conn.execute(
                "DELETE FROM shop_items WHERE guild_id = ? AND role_id = ?",
                (guild_id, role_id),
            )
            return panel_ids

        return await self.db.run_tx(operation)

    async def all_panels_with_options(self) -> list[tuple[RolePanel, list[PanelOption]]]:
        panels = await self.list_all_panels()
        result: list[tuple[RolePanel, list[PanelOption]]] = []
        for panel in panels:
            result.append((panel, await self.list_panel_options(panel.id)))
        return result

    # ── Достижения ───────────────────────────────────────────────────────────

    async def list_achievements(self, guild_id: int, enabled_only: bool = False) -> list[Achievement]:
        query = "SELECT * FROM achievements WHERE guild_id = ?"
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY threshold, id"
        rows = await self.db.fetchall(query, (guild_id,))
        return [Achievement.from_row(row) for row in rows]

    async def get_achievement(self, achievement_id: int) -> Achievement | None:
        row = await self.db.fetchone(
            "SELECT * FROM achievements WHERE id = ?", (achievement_id,)
        )
        return Achievement.from_row(row) if row else None

    async def create_achievement(
        self,
        guild_id: int,
        *,
        title: str,
        description: str,
        emoji: str,
        condition_type: str,
        threshold: int,
        reward_role_id: int | None = None,
        reward_loyalty: int = 0,
    ) -> Achievement:
        code = f"custom_{secrets.token_hex(4)}"
        achievement_id = await self.db.execute(
            "INSERT INTO achievements (guild_id, code, title, description, emoji,"
            " condition_type, threshold, reward_role_id, reward_loyalty, enabled, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (
                guild_id,
                code,
                title,
                description,
                emoji,
                condition_type,
                threshold,
                reward_role_id,
                reward_loyalty,
                now_iso(),
            ),
        )
        achievement = await self.get_achievement(achievement_id)
        assert achievement is not None
        return achievement

    async def set_achievement_enabled(self, achievement_id: int, enabled: bool) -> None:
        await self.db.execute_count(
            "UPDATE achievements SET enabled = ? WHERE id = ?", (int(enabled), achievement_id)
        )

    async def delete_achievement(self, achievement_id: int) -> bool:
        changed = await self.db.execute_count(
            "DELETE FROM achievements WHERE id = ?", (achievement_id,)
        )
        return changed > 0

    async def unlocked_achievement_ids(self, guild_id: int, user_id: int) -> set[int]:
        rows = await self.db.fetchall(
            "SELECT achievement_id FROM member_achievements WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return {int(row["achievement_id"]) for row in rows}

    async def unlock_achievement(
        self, guild_id: int, user_id: int, achievement_id: int
    ) -> bool:
        changed = await self.db.execute_count(
            "INSERT OR IGNORE INTO member_achievements"
            " (guild_id, user_id, achievement_id, unlocked_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, achievement_id, now_iso()),
        )
        return changed > 0

    async def list_user_achievements(
        self, guild_id: int, user_id: int
    ) -> list[tuple[Achievement, str]]:
        rows = await self.db.fetchall(
            "SELECT a.*, ma.unlocked_at FROM achievements a"
            " JOIN member_achievements ma ON ma.achievement_id = a.id"
            " WHERE ma.guild_id = ? AND ma.user_id = ? ORDER BY ma.unlocked_at DESC",
            (guild_id, user_id),
        )
        return [(Achievement.from_row(row), row["unlocked_at"]) for row in rows]

    async def count_unlocked(self, guild_id: int, user_id: int) -> int:
        return int(
            await self.db.scalar(
                "SELECT COUNT(*) FROM member_achievements WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
        )

    # ── Магазин лояльности ───────────────────────────────────────────────────

    async def list_shop_items(self, guild_id: int, enabled_only: bool = False) -> list[ShopItem]:
        query = "SELECT * FROM shop_items WHERE guild_id = ?"
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY position, price"
        rows = await self.db.fetchall(query, (guild_id,))
        return [ShopItem.from_row(row) for row in rows]

    async def get_shop_item(self, item_id: int) -> ShopItem | None:
        row = await self.db.fetchone("SELECT * FROM shop_items WHERE id = ?", (item_id,))
        return ShopItem.from_row(row) if row else None

    async def create_shop_item(
        self,
        guild_id: int,
        *,
        role_id: int,
        name: str,
        description: str,
        price: int,
        stock: int,
    ) -> ShopItem:
        item_id = await self.db.execute(
            "INSERT INTO shop_items (guild_id, role_id, name, description, price, stock,"
            " enabled, position, created_at) VALUES (?, ?, ?, ?, ?, ?, 1,"
            " (SELECT IFNULL(MAX(position), 0) + 1 FROM shop_items WHERE guild_id = ?), ?)",
            (guild_id, role_id, name, description, price, stock, guild_id, now_iso()),
        )
        item = await self.get_shop_item(item_id)
        assert item is not None
        return item

    async def set_shop_item_enabled(self, item_id: int, enabled: bool) -> None:
        await self.db.execute_count(
            "UPDATE shop_items SET enabled = ? WHERE id = ?", (int(enabled), item_id)
        )

    async def delete_shop_item(self, item_id: int) -> bool:
        changed = await self.db.execute_count("DELETE FROM shop_items WHERE id = ?", (item_id,))
        return changed > 0

    async def purchase_item(
        self, guild_id: int, user_id: int, item_id: int
    ) -> tuple[ShopItem | None, str]:
        """Списывает баллы и резервирует товар. Возвращает (товар, код ошибки)."""

        def operation(conn: sqlite3.Connection) -> tuple[ShopItem | None, str]:
            item_row = conn.execute(
                "SELECT * FROM shop_items WHERE id = ? AND guild_id = ?", (item_id, guild_id)
            ).fetchone()
            if item_row is None:
                return None, "not_found"
            item = ShopItem.from_row(item_row)
            if not item.enabled:
                return None, "disabled"
            if item.stock == 0:
                return None, "out_of_stock"
            balance_row = conn.execute(
                "SELECT loyalty FROM member_stats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            balance = int(balance_row["loyalty"]) if balance_row else 0
            if balance < item.price:
                return None, "no_money"
            timestamp = now_iso()
            conn.execute(
                "UPDATE member_stats SET loyalty = loyalty - ?, updated_at = ?"
                " WHERE guild_id = ? AND user_id = ?",
                (item.price, timestamp, guild_id, user_id),
            )
            if item.stock > 0:
                conn.execute("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (item.id,))
            conn.execute(
                "INSERT INTO shop_purchases (guild_id, user_id, item_id, price, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, item.id, item.price, timestamp),
            )
            return item, "ok"

        return await self.db.run_tx(operation)

    async def refund_purchase(self, guild_id: int, user_id: int, item_id: int) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT id, price FROM shop_purchases WHERE guild_id = ? AND user_id = ?"
                " AND item_id = ? ORDER BY id DESC LIMIT 1",
                (guild_id, user_id, item_id),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "UPDATE member_stats SET loyalty = loyalty + ? WHERE guild_id = ? AND user_id = ?",
                (int(row["price"]), guild_id, user_id),
            )
            conn.execute(
                "UPDATE shop_items SET stock = stock + 1 WHERE id = ? AND stock >= 0", (item_id,)
            )
            conn.execute("DELETE FROM shop_purchases WHERE id = ?", (int(row["id"]),))

        await self.db.run_tx(operation)

    async def list_purchases(self, guild_id: int, limit: int = 20) -> list[sqlite3.Row]:
        return await self.db.fetchall(
            "SELECT * FROM shop_purchases WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        )

    # ── Веб-сессии ───────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        user_id: int,
        username: str,
        avatar: str | None,
        guilds: list[dict[str, Any]],
        access_token: str,
        refresh_token: str | None,
        ttl_days: int = 7,
    ) -> WebSession:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        created = utcnow()
        expires = created + timedelta(days=ttl_days)
        await self.db.execute(
            "INSERT INTO web_sessions (token, user_id, username, avatar, guilds_json, csrf,"
            " access_token, refresh_token, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                username,
                avatar,
                json.dumps(guilds, ensure_ascii=False),
                csrf,
                access_token,
                refresh_token,
                created.replace(microsecond=0).isoformat(),
                expires.replace(microsecond=0).isoformat(),
            ),
        )
        session = await self.get_session(token)
        assert session is not None
        return session

    async def get_session(self, token: str) -> WebSession | None:
        row = await self.db.fetchone(
            "SELECT * FROM web_sessions WHERE token = ? AND expires_at > ?",
            (token, now_iso()),
        )
        return WebSession.from_row(row) if row else None

    async def delete_session(self, token: str) -> None:
        await self.db.execute_count("DELETE FROM web_sessions WHERE token = ?", (token,))

    async def purge_expired_sessions(self) -> None:
        await self.db.execute_count("DELETE FROM web_sessions WHERE expires_at <= ?", (now_iso(),))
