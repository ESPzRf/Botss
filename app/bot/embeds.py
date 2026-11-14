"""Единые эмбеды для ответов и логов."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import discord

from app.core import BOT_NAME
from app.core.models import Case
from app.core.utils import truncate, utcnow

COLOR_BRAND = 0x5865F2
COLOR_OK = 0x3BA55D
COLOR_WARN = 0xFAA61A
COLOR_ERROR = 0xED4245
COLOR_MOD = 0xEB459E
COLOR_LOG = 0x4F545C
COLOR_XP = 0xFEE75C


def base(
    title: str | None = None,
    description: str | None = None,
    *,
    color: int = COLOR_BRAND,
    timestamp: bool = True,
    url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=utcnow() if timestamp else None,
        url=url,
    )
    embed.set_footer(text=BOT_NAME)
    return embed


def success(title: str, description: str | None = None) -> discord.Embed:
    return base(f"✅ {title}", description, color=COLOR_OK)


def error(title: str, description: str | None = None) -> discord.Embed:
    return base(f"⛔ {title}", description, color=COLOR_ERROR)


def warning(title: str, description: str | None = None) -> discord.Embed:
    return base(f"⚠️ {title}", description, color=COLOR_WARN)


def info(title: str, description: str | None = None) -> discord.Embed:
    return base(title, description, color=COLOR_BRAND)


def log_embed(title: str, description: str | None = None, *, color: int = COLOR_LOG) -> discord.Embed:
    embed = base(title, description, color=color)
    return embed


def user_field(embed: discord.Embed, name: str, user: discord.abc.User) -> None:
    user_id = getattr(user, "id", None)
    mention = getattr(user, "mention", None) or (f"<@{user_id}>" if user_id else "—")
    display_name = getattr(user, "name", None) or getattr(user, "global_name", None)
    if display_name:
        display = f"`{user}`"
    else:
        display = "пользователь"
    value = f"{mention}\n{display}"
    if user_id:
        value += f" · ID `{user_id}`"
    embed.add_field(name=name, value=value, inline=True)


def reason_field(embed: discord.Embed, reason: str) -> None:
    embed.add_field(name="Причина", value=truncate(reason or "не указана", 1024), inline=False)


def duration_field(embed: discord.Embed, seconds: int | None) -> None:
    from app.core.durations import format_duration

    embed.add_field(name="Длительность", value=format_duration(seconds), inline=True)


def mod_action_embed(
    *,
    title: str,
    target: discord.abc.User,
    moderator: discord.abc.User,
    reason: str,
    color: int = COLOR_MOD,
    case: Case | None = None,
    duration: int | None = None,
    extra: Iterable[tuple[str, str]] = (),
) -> discord.Embed:
    embed = base(title, color=color)
    user_field(embed, "Участник", target)
    user_field(embed, "Модератор", moderator)
    reason_field(embed, reason)
    if duration is not None:
        duration_field(embed, duration)
    if case is not None:
        embed.add_field(name="Наказание", value=f"`#{case.id}` · {case.kind_label}", inline=True)
    for name, value in extra:
        embed.add_field(name=name, value=value, inline=True)
    return embed


def dm_punishment_embed(
    *,
    guild_name: str,
    action: str,
    reason: str,
    duration: int | None = None,
    case_id: int | None = None,
) -> discord.Embed:
    embed = base(f"Модерация · {guild_name}", color=COLOR_WARN)
    embed.add_field(name="Действие", value=action, inline=True)
    if duration is not None:
        duration_field(embed, duration)
    reason_field(embed, reason)
    if case_id:
        embed.set_footer(text=f"{BOT_NAME} · случай #{case_id}")
    return embed


def dt(value: datetime | None, style: str = "R") -> str:
    if value is None:
        return "—"
    return discord.utils.format_dt(value, style)


def timestamp_now() -> str:
    return discord.utils.format_dt(utcnow(), "F")
