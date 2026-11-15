"""Выдача уровневых ролей, уведомления и проверка достижений."""

from __future__ import annotations

import logging

import discord

from app.bot import embeds
from app.bot.checks import hierarchy_error
from app.bot.runtime import Runtime
from app.core.defaults import CONDITION_UNITS
from app.core.levels import format_number, level_progress, progress_bar
from app.core.models import Achievement, MemberStats
from app.core.utils import truncate

logger = logging.getLogger(__name__)


async def grant_level_rewards(
    runtime: Runtime, guild: discord.Guild, member: discord.Member, stats: MemberStats
) -> list[discord.Role]:
    config = await runtime.config(guild)
    granted: list[discord.Role] = []
    for level, role_id in config.level_rewards():
        if stats.level < level:
            continue
        role = guild.get_role(role_id)
        if role is None or role in member.roles:
            continue
        problem = hierarchy_error(guild, role)
        if problem:
            logger.warning("Уровневая роль %s не выдана: %s", role_id, problem)
            continue
        try:
            await member.add_roles(role, reason=f"Награда за {level} уровень")
            granted.append(role)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Не удалось выдать уровневую роль %s участнику %s", role_id, member.id)
    return granted


async def handle_level_up(
    runtime: Runtime,
    guild: discord.Guild,
    member: discord.Member,
    stats: MemberStats,
    old_level: int,
) -> None:
    if stats.level <= old_level:
        return

    await grant_level_rewards(runtime, guild, member, stats)
    config = await runtime.config(guild)

    channel = None
    if config.level_up_channel_id:
        found = guild.get_channel(config.level_up_channel_id)
        if isinstance(found, discord.TextChannel):
            channel = found
    if channel is None:
        channel = guild.system_channel
    if channel is None:
        await check_achievements(runtime, guild, member, stats)
        return

    try:
        text = config.level_up_message.format(
            user=member.mention, level=stats.level, xp=format_number(stats.xp)
        )
    except (KeyError, IndexError, ValueError):
        text = f"🎉 {member.mention}, новый уровень — **{stats.level}**!"

    level, current, needed, percent = level_progress(stats.xp)
    embed = embeds.base(f"Новый уровень · {level}", text, color=embeds.COLOR_XP)
    embed.add_field(name="Прогресс", value=f"{progress_bar(percent)} {current}/{needed} XP", inline=False)
    try:
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Не удалось отправить уведомление об уровне в %s", channel.id)

    await check_achievements(runtime, guild, member, stats)


async def check_achievements(
    runtime: Runtime,
    guild: discord.Guild,
    member: discord.Member,
    stats: MemberStats | None = None,
) -> list[Achievement]:
    """Проверяет все достижения участника и выдаёт новые."""
    config = await runtime.config(guild)
    if not config.achievements_enabled:
        return []
    if stats is None:
        stats = await runtime.repo.get_stats(guild.id, member.id)

    achievements = await runtime.achievements(guild.id)
    if not achievements:
        return []
    unlocked = await runtime.repo.unlocked_achievement_ids(guild.id, member.id)
    days = 0
    if member.joined_at is not None:
        from app.core.utils import utcnow

        days = max(0, (utcnow() - member.joined_at).days)

    values = {
        "messages": stats.messages,
        "voice_minutes": stats.voice_minutes,
        "level": stats.level,
        "loyalty": stats.loyalty,
        "days": days,
    }

    new_achievements: list[Achievement] = []
    for achievement in achievements:
        if achievement.id in unlocked:
            continue
        value = values.get(achievement.condition_type, 0)
        if value < achievement.threshold:
            continue
        inserted = await runtime.repo.unlock_achievement(guild.id, member.id, achievement.id)
        if not inserted:
            continue
        new_achievements.append(achievement)
        if achievement.reward_loyalty:
            await runtime.repo.add_loyalty(guild.id, member.id, achievement.reward_loyalty)
            stats.loyalty += achievement.reward_loyalty
        if achievement.reward_role_id:
            role = guild.get_role(achievement.reward_role_id)
            if role is not None and role not in member.roles:
                problem = hierarchy_error(guild, role)
                if problem:
                    logger.warning("Роль за достижение %s не выдана: %s", role.id, problem)
                else:
                    try:
                        await member.add_roles(role, reason=f"Достижение «{achievement.title}»")
                    except (discord.Forbidden, discord.HTTPException):
                        logger.warning("Не удалось выдать роль за достижение %s", role.id)

    if new_achievements:
        await _announce(runtime, guild, member, new_achievements, config.achievements_channel_id)
    return new_achievements


async def _announce(
    runtime: Runtime,
    guild: discord.Guild,
    member: discord.Member,
    achievements: list[Achievement],
    channel_id: int | None,
) -> None:
    channel = None
    if channel_id:
        found = guild.get_channel(channel_id)
        if isinstance(found, discord.TextChannel):
            channel = found
    if channel is None:
        channel = guild.system_channel
    if channel is None:
        return

    lines = []
    for item in achievements[:10]:
        line = f"{item.emoji} **{item.title}** — {item.description}"
        if item.reward_loyalty:
            line += f" (+{item.reward_loyalty} баллов)"
        lines.append(line)
    embed = embeds.base(
        "🏆 Новое достижение!",
        truncate(f"{member.mention} получает:\n\n" + "\n".join(lines), 4000),
        color=embeds.COLOR_XP,
    )
    try:
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Не удалось отправить достижение в канал %s", channel.id)


def achievement_progress_text(achievement: Achievement, stats: MemberStats, days: int) -> str:
    values = {
        "messages": stats.messages,
        "voice_minutes": stats.voice_minutes,
        "level": stats.level,
        "loyalty": stats.loyalty,
        "days": days,
    }
    value = values.get(achievement.condition_type, 0)
    unit = CONDITION_UNITS.get(achievement.condition_type, "")
    return f"{min(value, achievement.threshold)}/{achievement.threshold} {unit}"
