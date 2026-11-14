"""Проверки прав и иерархии ролей для слэш-команд."""

from __future__ import annotations

from typing import Callable

import discord
from discord import app_commands

MODERATION_PERMS = (
    "administrator",
    "moderate_members",
    "kick_members",
    "ban_members",
    "manage_messages",
)
ADMIN_PERMS = ("administrator", "manage_guild")


def is_moderator(member: discord.Member) -> bool:
    return any(getattr(member.guild_permissions, perm, False) for perm in MODERATION_PERMS)


def is_admin(member: discord.Member) -> bool:
    return any(getattr(member.guild_permissions, perm, False) for perm in ADMIN_PERMS)


def mod_only() -> Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage("Команда работает только на сервере.")
        if not isinstance(interaction.user, discord.Member) or not is_moderator(interaction.user):
            raise app_commands.CheckFailure(
                "Нужны права **Управлять участниками**, **Кикать** или **Банить**."
            )
        return True

    return app_commands.check(predicate)


def admin_only() -> Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage("Команда работает только на сервере.")
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            raise app_commands.CheckFailure("Нужны права **Управлять сервером**.")
        return True

    return app_commands.check(predicate)


async def ensure_target(
    interaction: discord.Interaction,
    target: discord.abc.User,
    *,
    action: str = "применить действие",
) -> str | None:
    """Возвращает текст ошибки, если действие над участником невозможно."""
    guild = interaction.guild
    assert guild is not None
    me = guild.me
    actor = interaction.user

    if target.id == actor.id:
        return f"Нельзя {action} по отношению к себе."
    if me is not None and target.id == me.id:
        return f"Нельзя {action} по отношению к боту."
    if target.id == guild.owner_id:
        return f"Нельзя {action} по отношению к владельцу сервера."

    if isinstance(target, discord.Member):
        if me is not None and target.top_role >= me.top_role:
            return (
                "Роль участника выше или равна роли бота — Discord не позволит "
                f"{action}. Поднимите роль бота в списке ролей."
            )
        if (
            isinstance(actor, discord.Member)
            and actor.id != guild.owner_id
            and target.top_role >= actor.top_role
        ):
            return "Нельзя модерировать участника с равной или более высокой ролью."
    return None


def can_manage_role(guild: discord.Guild, role: discord.Role) -> bool:
    me = guild.me
    if me is None:
        return False
    return (
        not role.is_default()
        and not role.managed
        and role < me.top_role
        and me.guild_permissions.manage_roles
    )


def hierarchy_error(guild: discord.Guild, role: discord.Role) -> str | None:
    me = guild.me
    if me is None:
        return "Бот не найден на сервере."
    if not me.guild_permissions.manage_roles:
        return "У бота нет права **Управлять ролями**."
    if role.is_default():
        return "Нельзя выдавать роль @everyone."
    if role.managed:
        return "Эту роль управляет интеграция, выдать её нельзя."
    if role >= me.top_role:
        return "Роль находится выше роли бота — поднимите роль бота."
    return None
