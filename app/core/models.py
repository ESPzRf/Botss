"""Модели данных, в которые репозиторий превращает строки SQLite."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.core.events import DEFAULT_EVENTS


def _json_list(raw: Any) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw: Any) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class GuildConfig:
    guild_id: int
    name: str = ""
    icon: str | None = None
    log_channel_id: int | None = None
    mod_log_channel_id: int | None = None
    events: dict[str, bool] = field(default_factory=dict)
    ignore_channels: list[int] = field(default_factory=list)
    ignore_users: list[int] = field(default_factory=list)
    autorole_ids: list[int] = field(default_factory=list)
    autorole_bots: bool = False
    restore_roles: bool = False
    mute_role_id: int | None = None
    escalations: list[dict[str, Any]] = field(default_factory=list)
    xp_enabled: bool = True
    xp_min: int = 15
    xp_max: int = 25
    xp_cooldown: int = 60
    xp_voice_per_min: int = 5
    xp_ignore_channels: list[int] = field(default_factory=list)
    xp_ignore_roles: list[int] = field(default_factory=list)
    level_up_channel_id: int | None = None
    level_up_message: str = "🎉 {user}, новый уровень — **{level}**!"
    level_roles: list[dict[str, Any]] = field(default_factory=list)
    loyalty_enabled: bool = True
    loyalty_per_message: int = 1
    loyalty_per_voice_min: int = 2
    achievements_enabled: bool = True
    achievements_channel_id: int | None = None
    shop_enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "GuildConfig":
        return cls(
            guild_id=int(row["guild_id"]),
            name=row["name"] or "",
            icon=row["icon"],
            log_channel_id=row["log_channel_id"],
            mod_log_channel_id=row["mod_log_channel_id"],
            events={str(k): bool(v) for k, v in _json_dict(row["events_json"]).items()},
            ignore_channels=[int(v) for v in _json_list(row["ignore_channels_json"])],
            ignore_users=[int(v) for v in _json_list(row["ignore_users_json"])],
            autorole_ids=[int(v) for v in _json_list(row["autorole_ids_json"])],
            autorole_bots=bool(row["autorole_bots"]),
            restore_roles=bool(row["restore_roles"]),
            mute_role_id=row["mute_role_id"],
            escalations=[e for e in _json_list(row["escalations_json"]) if isinstance(e, dict)],
            xp_enabled=bool(row["xp_enabled"]),
            xp_min=int(row["xp_min"]),
            xp_max=int(row["xp_max"]),
            xp_cooldown=int(row["xp_cooldown"]),
            xp_voice_per_min=int(row["xp_voice_per_min"]),
            xp_ignore_channels=[int(v) for v in _json_list(row["xp_ignore_channels_json"])],
            xp_ignore_roles=[int(v) for v in _json_list(row["xp_ignore_roles_json"])],
            level_up_channel_id=row["level_up_channel_id"],
            level_up_message=row["level_up_message"],
            level_roles=[e for e in _json_list(row["level_roles_json"]) if isinstance(e, dict)],
            loyalty_enabled=bool(row["loyalty_enabled"]),
            loyalty_per_message=int(row["loyalty_per_message"]),
            loyalty_per_voice_min=int(row["loyalty_per_voice_min"]),
            achievements_enabled=bool(row["achievements_enabled"]),
            achievements_channel_id=row["achievements_channel_id"],
            shop_enabled=bool(row["shop_enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def event_enabled(self, key: str) -> bool:
        return bool(self.events.get(key, DEFAULT_EVENTS.get(key, False)))

    def log_channel_for(self, key: str) -> int | None:
        if key == "mod_action" and self.mod_log_channel_id:
            return self.mod_log_channel_id
        return self.log_channel_id

    def escalation_for(self, warning_count: int) -> dict[str, Any] | None:
        matches = [
            rule
            for rule in self.escalations
            if int(rule.get("count", 0) or 0) == warning_count
        ]
        return matches[0] if matches else None

    def level_rewards(self) -> list[tuple[int, int]]:
        rewards: list[tuple[int, int]] = []
        for item in self.level_roles:
            try:
                rewards.append((int(item["level"]), int(item["role_id"])))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(rewards, key=lambda pair: pair[0])


CASE_TIMEOUT = "timeout"
CASE_MUTE = "mute"
CASE_BAN = "ban"
CASE_KICK = "kick"

CASE_KIND_LABELS = {
    CASE_TIMEOUT: "Тайм-аут",
    CASE_MUTE: "Мут",
    CASE_BAN: "Бан",
    CASE_KICK: "Кик",
}

CASE_KIND_EMOJI = {
    CASE_TIMEOUT: "⏳",
    CASE_MUTE: "🔇",
    CASE_BAN: "🔨",
    CASE_KICK: "👢",
}


@dataclass(slots=True)
class Warning:
    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str
    created_at: str
    active: bool = True
    removed_by: int | None = None
    removed_at: str | None = None
    removed_reason: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Warning":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            moderator_id=int(row["moderator_id"]),
            reason=row["reason"],
            created_at=row["created_at"],
            active=bool(row["active"]),
            removed_by=row["removed_by"],
            removed_at=row["removed_at"],
            removed_reason=row["removed_reason"],
        )


@dataclass(slots=True)
class Case:
    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    kind: str
    reason: str
    created_at: str
    expires_at: str | None = None
    active: bool = True
    ended_at: str | None = None
    ended_by: int | None = None
    end_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Case":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            moderator_id=int(row["moderator_id"]),
            kind=row["kind"],
            reason=row["reason"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            active=bool(row["active"]),
            ended_at=row["ended_at"],
            ended_by=row["ended_by"],
            end_reason=row["end_reason"],
            extra=_json_dict(row["extra_json"]),
        )

    @property
    def kind_label(self) -> str:
        return CASE_KIND_LABELS.get(self.kind, self.kind)


@dataclass(slots=True)
class MemberStats:
    guild_id: int
    user_id: int
    xp: int = 0
    level: int = 0
    messages: int = 0
    voice_seconds: int = 0
    loyalty: int = 0
    last_xp_at: str | None = None
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "MemberStats":
        return cls(
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            xp=int(row["xp"]),
            level=int(row["level"]),
            messages=int(row["messages"]),
            voice_seconds=int(row["voice_seconds"]),
            loyalty=int(row["loyalty"]),
            last_xp_at=row["last_xp_at"],
            updated_at=row["updated_at"],
        )

    @property
    def voice_minutes(self) -> int:
        return self.voice_seconds // 60


@dataclass(slots=True)
class RolePanel:
    id: int
    guild_id: int
    channel_id: int
    message_id: int | None
    title: str
    description: str
    mode: str
    created_by: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "RolePanel":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            message_id=row["message_id"],
            title=row["title"],
            description=row["description"],
            mode=row["mode"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class PanelOption:
    id: int
    panel_id: int
    role_id: int
    label: str
    emoji: str | None
    style: int
    position: int

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PanelOption":
        return cls(
            id=int(row["id"]),
            panel_id=int(row["panel_id"]),
            role_id=int(row["role_id"]),
            label=row["label"] or "",
            emoji=row["emoji"],
            style=int(row["style"]),
            position=int(row["position"]),
        )


@dataclass(slots=True)
class Achievement:
    id: int
    guild_id: int
    code: str
    title: str
    description: str
    emoji: str
    condition_type: str
    threshold: int
    reward_role_id: int | None
    reward_loyalty: int
    enabled: bool
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Achievement":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            code=row["code"],
            title=row["title"],
            description=row["description"],
            emoji=row["emoji"],
            condition_type=row["condition_type"],
            threshold=int(row["threshold"]),
            reward_role_id=row["reward_role_id"],
            reward_loyalty=int(row["reward_loyalty"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ShopItem:
    id: int
    guild_id: int
    role_id: int
    name: str
    description: str
    price: int
    stock: int
    enabled: bool
    position: int
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ShopItem":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            role_id=int(row["role_id"]),
            name=row["name"],
            description=row["description"],
            price=int(row["price"]),
            stock=int(row["stock"]),
            enabled=bool(row["enabled"]),
            position=int(row["position"]),
            created_at=row["created_at"],
        )

    @property
    def is_unlimited(self) -> bool:
        return self.stock < 0


@dataclass(slots=True)
class WebSession:
    token: str
    user_id: int
    username: str
    avatar: str | None
    guilds: list[dict[str, Any]]
    csrf: str
    created_at: str
    expires_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WebSession":
        guilds = [g for g in _json_list(row["guilds_json"]) if isinstance(g, dict)]
        return cls(
            token=row["token"],
            user_id=int(row["user_id"]),
            username=row["username"],
            avatar=row["avatar"],
            guilds=guilds,
            csrf=row["csrf"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def can_manage(self, guild_id: int) -> bool:
        for guild in self.guilds:
            try:
                if int(guild.get("id", 0)) == int(guild_id):
                    return bool(guild.get("owner")) or bool(int(guild.get("permissions", 0)) & 0x28)
            except (TypeError, ValueError):
                continue
        return False

    def managed_guild_ids(self) -> set[int]:
        result: set[int] = set()
        for guild in self.guilds:
            try:
                gid = int(guild.get("id", 0))
            except (TypeError, ValueError):
                continue
            if guild.get("owner") or int(guild.get("permissions", 0)) & 0x28:
                result.add(gid)
        return result
