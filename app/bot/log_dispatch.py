"""Отправка событий в канал логов с учётом настроек сервера."""

from __future__ import annotations

import logging

import discord

from app.bot.embeds import apply_user_avatar
from app.bot.runtime import Runtime

logger = logging.getLogger(__name__)
_warned_channels: set[int] = set()


async def send_event_log(
    runtime: Runtime,
    guild: discord.Guild,
    event_key: str,
    embed: discord.Embed,
    *,
    channel: discord.abc.GuildChannel | None = None,
    user: discord.abc.User | None = None,
    avatar_user: discord.abc.User | None = None,
) -> bool:
    """Отправляет эмбед, если событие включено и канал настроен."""
    try:
        config = await runtime.config(guild)
    except Exception:  # noqa: BLE001 - логирование не должно ломать события
        logger.exception("Не удалось прочитать настройки сервера %s", guild.id)
        return False

    if not config.event_enabled(event_key):
        return False
    if channel is not None and channel.id in config.ignore_channels:
        return False
    if user is not None and user.id in config.ignore_users:
        return False

    channel_id = config.log_channel_for(event_key)
    if not channel_id:
        return False

    target = guild.get_channel_or_thread(channel_id)
    if target is None:
        try:
            fetched = await runtime.bot.fetch_channel(channel_id)  # type: ignore[union-attr]
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            if channel_id not in _warned_channels:
                _warned_channels.add(channel_id)
                logger.warning("Канал логов %s недоступен на сервере %s", channel_id, guild.id)
            return False
        if isinstance(fetched, (discord.TextChannel, discord.Thread)):
            target = fetched

    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        return False

    apply_user_avatar(embed, avatar_user or user)

    runtime.spawn(
        _deliver(target, embed, channel_id),
        name=f"log:{event_key}:{guild.id}",
    )
    return True


async def _deliver(
    target: discord.TextChannel | discord.Thread,
    embed: discord.Embed,
    channel_id: int,
) -> None:
    try:
        await target.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        if channel_id not in _warned_channels:
            _warned_channels.add(channel_id)
            logger.warning("Нет прав на отправку логов в канал %s", channel_id)
    except discord.HTTPException:
        logger.exception("Ошибка отправки лога в канал %s", channel_id)


async def send_mod_action(
    runtime: Runtime,
    guild: discord.Guild,
    embed: discord.Embed,
    *,
    user: discord.abc.User | None = None,
) -> bool:
    return await send_event_log(runtime, guild, "mod_action", embed, user=user)


async def try_dm(user: discord.abc.User, embed: discord.Embed) -> bool:
    """Пытается отправить личное сообщение, не падая на закрытых ЛС."""
    try:
        await user.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
