"""Ког фонового снятия временных наказаний."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from app.bot import embeds
from app.bot.log_dispatch import send_mod_action, try_dm
from app.bot.services.moderation import reconcile_guild
from app.core.models import CASE_BAN, CASE_MUTE, CASE_TIMEOUT, Case
from app.core.utils import to_iso

logger = logging.getLogger(__name__)


class Punishments(commands.Cog):
    """Снимает истёкшие наказания и сверяет активные дела с Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        self.expiry_loop.start()
        self.reconcile_loop.start()

    async def cog_unload(self) -> None:
        self.expiry_loop.cancel()
        self.reconcile_loop.cancel()

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Ловит ручное снятие тайм-аута или роли мута."""
        guild = after.guild

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until is None:
                await self.runtime.repo.close_active_cases(
                    guild.id,
                    after.id,
                    (CASE_TIMEOUT,),
                    self.bot.user.id if self.bot.user else None,
                    "Тайм-аут снят вручную",
                )
            else:
                case = await self.runtime.repo.active_case(
                    guild.id, after.id, (CASE_TIMEOUT,)
                )
                if case is not None:
                    await self.runtime.repo.update_case_expires(
                        case.id, to_iso(after.timed_out_until)
                    )

        if before.roles == after.roles:
            return
        config = await self.runtime.config(guild)
        role = guild.get_role(config.mute_role_id) if config.mute_role_id else None
        if role is not None and role in before.roles and role not in after.roles:
            await self.runtime.repo.close_active_cases(
                guild.id,
                after.id,
                (CASE_MUTE,),
                self.bot.user.id if self.bot.user else None,
                "Мут снят вручную",
            )

    @tasks.loop(minutes=5)
    async def reconcile_loop(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                await reconcile_guild(self.runtime, guild)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка сверки наказаний на сервере %s", guild.id)

    @reconcile_loop.before_loop
    async def before_reconcile(self) -> None:
        if not hasattr(getattr(self.bot, "_ready", None), "wait"):
            return
        await self.bot.wait_until_ready()

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
        await send_mod_action(
            self.runtime,
            guild,
            embed,
            user=member or discord.Object(id=case.user_id),
        )

        if member is not None:
            self.runtime.spawn(
                try_dm(
                    member,
                    embeds.dm_punishment_embed(
                        guild_name=guild.name,
                        action="Наказание снято",
                        reason=end_reason,
                        case_id=case.id,
                    ),
                ),
                name=f"dm-expire:{case.id}",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Punishments(bot))
