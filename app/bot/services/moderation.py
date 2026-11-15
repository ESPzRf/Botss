"""Сверка дел с фактическим состоянием участников в Discord."""

from __future__ import annotations

import discord

from app.bot.runtime import Runtime
from app.core.models import CASE_BAN, CASE_MUTE, CASE_TIMEOUT, Case
from app.core.utils import parse_iso, to_iso, utcnow

DEFAULT_GRACE_SECONDS = 10


def _is_recent(case: Case, grace_seconds: int) -> bool:
    created = parse_iso(case.created_at)
    if created is None or grace_seconds <= 0:
        return False
    return (utcnow() - created).total_seconds() < grace_seconds


async def _close(
    runtime: Runtime,
    case: Case,
    reason: str,
    moderator_id: int | None,
) -> bool:
    return await runtime.repo.close_case(case.id, moderator_id, reason)


async def reconcile_guild(
    runtime: Runtime,
    guild: discord.Guild,
    *,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
    check_bans: bool = True,
) -> int:
    """Закрывает дела, которые уже не действуют в Discord.

    Проверяются тайм-ауты, муты и баны. Возвращает количество закрытых дел.
    """
    bot_id = runtime.bot.user.id if runtime.bot and runtime.bot.user else None
    config = await runtime.config(guild)
    cases = await runtime.repo.list_cases(guild.id, active=True, limit=250)
    closed = 0

    for case in cases:
        if _is_recent(case, grace_seconds):
            continue
        member = guild.get_member(case.user_id)

        if case.kind == CASE_TIMEOUT:
            if member is None:
                continue
            actual = member.timed_out_until
            if actual is None:
                if await _close(runtime, case, "Тайм-аут снят вручную", bot_id):
                    closed += 1
            elif case.expires_at:
                expected = parse_iso(case.expires_at)
                if expected is not None and abs((actual - expected).total_seconds()) > 60:
                    await runtime.repo.update_case_expires(case.id, to_iso(actual))
            continue

        if case.kind == CASE_MUTE:
            if member is None:
                continue
            role_id = int(case.extra.get("role_id") or config.mute_role_id or 0)
            role = guild.get_role(role_id) if role_id else None
            if role is None or role not in member.roles:
                if await _close(runtime, case, "Мут снят вручную", bot_id):
                    closed += 1
            continue

        if case.kind == CASE_BAN:
            if not check_bans:
                continue
            try:
                await guild.fetch_ban(discord.Object(id=case.user_id))
            except discord.NotFound:
                if await _close(runtime, case, "Бан снят вручную", bot_id):
                    closed += 1
            except (discord.Forbidden, discord.HTTPException):
                continue

    return closed
