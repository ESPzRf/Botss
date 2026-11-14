"""Ког фонового снятия временных наказаний."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from app.bot import embeds
from app.bot.log_dispatch import send_mod_action, try_dm
from app.core.models import CASE_BAN, CASE_MUTE, CASE_TIMEOUT, Case

logger = logging.getLogger(__name__)


class Punishments(commands.Cog):
    """Раз в 30 секунд проверяет истёкшие наказания и снимает их."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        self.expiry_loop.start()

    async def cog_unload(self) -> None:
        self.expiry_loop.cancel()

    @tasks.loop(seconds=30)
    async def expiry_loop(self) -> None:
        try:
            cases = await self.runtime.repo.due_cases(limit=100)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось получить истёкшие наказания")
            return
        for case in cases:
            try:
                await self._expire(case)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка снятия наказания #%s", case.id)

    @expiry_loop.before_loop
    async def before_expiry(self) -> None:
        if not hasattr(getattr(self.bot, "_ready", None), "wait"):
            return
        await self.bot.wait_until_ready()

    async def _expire(self, case: Case) -> None:
        guild = self.bot.get_guild(case.guild_id)
        if guild is None:
            await self.runtime.repo.close_case(
                case.id, self.bot.user.id, "Сервер недоступен"  # type: ignore[union-attr]
            )
            return

        member = guild.get_member(case.user_id)
        end_reason = "Срок наказания истёк"
        failed = False

        try:
            if case.kind == CASE_BAN:
                await guild.unban(
                    discord.Object(id=case.user_id), reason="Срок бана истёк"
                )
            elif case.kind == CASE_TIMEOUT and member is not None:
                await member.timeout(None, reason="Срок тайм-аута истёк")
            elif case.kind == CASE_MUTE and member is not None:
                role_id = int(case.extra.get("role_id") or 0)
                role = guild.get_role(role_id) if role_id else None
                if role is not None and role in member.roles:
                    await member.remove_roles(role, reason="Срок мута истёк")
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException):
            failed = True
            end_reason = "Не удалось снять автоматически: недостаточно прав"
            logger.warning("Не удалось снять наказание #%s на сервере %s", case.id, guild.id)

        await self.runtime.repo.close_case(case.id, self.bot.user.id, end_reason)  # type: ignore[union-attr]

        embed = embeds.base(
            f"⌛ Наказание #{case.id} завершено",
            f"{case.kind_label} для <@{case.user_id}> снято автоматически.",
            color=embeds.COLOR_OK if not failed else embeds.COLOR_ERROR,
        )
        embed.add_field(name="Причина", value=case.reason or "не указана", inline=False)
        embed.add_field(name="Итог", value=end_reason, inline=False)
        await send_mod_action(self.runtime, guild, embed)

        if member is not None:
            await try_dm(
                member,
                embeds.dm_punishment_embed(
                    guild_name=guild.name,
                    action="Наказание снято",
                    reason=end_reason,
                    case_id=case.id,
                ),
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Punishments(bot))
