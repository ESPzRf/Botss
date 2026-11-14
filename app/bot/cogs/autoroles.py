"""Ког авторолей и восстановления ролей после повторного входа."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


def _assignable_roles(guild: discord.Guild, role_ids: list[int]) -> list[discord.Role]:
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return []
    result: list[discord.Role] = []
    for role_id in role_ids:
        role = guild.get_role(int(role_id))
        if role is None or role in result:
            continue
        if role.is_default() or role.managed or role >= me.top_role:
            continue
        result.append(role)
    return result


class AutoRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return
        try:
            config = await self.runtime.config(member.guild)
        except Exception:  # noqa: BLE001
            logger.exception("Автороли: не удалось прочитать настройки %s", member.guild.id)
            return

        if member.bot and not config.autorole_bots:
            return

        roles = _assignable_roles(member.guild, config.autorole_ids)
        if config.restore_roles:
            saved = await self.runtime.repo.get_member_roles(member.guild.id, member.id)
            for role in _assignable_roles(member.guild, saved):
                if role not in roles:
                    roles.append(role)
            await self.runtime.repo.clear_member_roles(member.guild.id, member.id)

        roles = [role for role in roles if role not in member.roles]
        if not roles:
            return
        try:
            await member.add_roles(*roles, reason="Автороли при входе")
            logger.info(
                "Выдано %s авторолей участнику %s на сервере %s",
                len(roles),
                member.id,
                member.guild.id,
            )
        except discord.Forbidden:
            logger.warning("Нет прав выдать автороли участнику %s", member.id)
        except discord.HTTPException:
            logger.exception("Ошибка выдачи авторолей участнику %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot or member.guild is None:
            return
        try:
            config = await self.runtime.config(member.guild)
        except Exception:  # noqa: BLE001
            return
        if not config.restore_roles:
            return

        me = member.guild.me
        if me is None:
            return
        role_ids = [
            role.id
            for role in member.roles
            if not role.is_default()
            and not role.managed
            and role.id != config.mute_role_id
            and role < me.top_role
        ]
        if not role_ids:
            return
        await self.runtime.repo.save_member_roles(member.guild.id, member.id, role_ids)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRoles(bot))
