"""Ког модерации: предупреждения, тайм-ауты, муты, баны, кики и история дел."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.checks import ensure_target, hierarchy_error, mod_only
from app.bot.log_dispatch import send_mod_action, try_dm
from app.core.durations import DurationError, format_duration, parse_duration
from app.core.models import CASE_BAN, CASE_KICK, CASE_MUTE, CASE_TIMEOUT, Case
from app.core.utils import parse_iso, to_iso, truncate, utcnow

logger = logging.getLogger(__name__)

MAX_TIMEOUT = 28 * 86400
MAX_REASON = 500


def _missing_perms(guild: discord.Guild, *permissions: str) -> str | None:
    me = guild.me
    if me is None:
        return "Бот не найден на сервере."
    missing = [
        permission for permission in permissions if not getattr(me.guild_permissions, permission, False)
    ]
    if missing:
        return "Боту не хватает прав: " + ", ".join(f"`{value}`" for value in missing)
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    # ── Вспомогательные методы ───────────────────────────────────────────────

    async def _dm(
        self,
        user: discord.abc.User,
        *,
        guild_name: str,
        action: str,
        reason: str,
        duration: int | None = None,
        case_id: int | None = None,
    ) -> None:
        embed = embeds.dm_punishment_embed(
            guild_name=guild_name,
            action=action,
            reason=reason,
            duration=duration,
            case_id=case_id,
        )
        await try_dm(user, embed)

    def _case_embed(self, case: Case) -> discord.Embed:
        color = embeds.COLOR_MOD if case.active else embeds.COLOR_LOG
        embed = embeds.base(
            f"Наказание #{case.id} · {case.kind_label}",
            case.reason or "*без причины*",
            color=color,
        )
        embed.add_field(name="Участник", value=f"<@{case.user_id}>\n`{case.user_id}`", inline=True)
        embed.add_field(name="Модератор", value=f"<@{case.moderator_id}>\n`{case.moderator_id}`", inline=True)
        embed.add_field(name="Статус", value="активно" if case.active else "завершено", inline=True)
        created = parse_iso(case.created_at)
        embed.add_field(name="Создано", value=embeds.dt(created, "F"), inline=True)
        if case.expires_at:
            embed.add_field(name="Истекает", value=embeds.dt(parse_iso(case.expires_at), "F"), inline=True)
        else:
            embed.add_field(name="Длительность", value="бессрочно", inline=True)
        if case.ended_at:
            embed.add_field(
                name="Завершено",
                value=f"{embeds.dt(parse_iso(case.ended_at), 'F')}\n{case.end_reason or ''}",
                inline=False,
            )
        return embed

    async def _log(
        self,
        guild: discord.Guild,
        *,
        title: str,
        target: discord.abc.User,
        moderator: discord.abc.User,
        reason: str,
        case: Case | None = None,
        seconds: int | None = None,
        color: int = embeds.COLOR_MOD,
        extra: tuple[tuple[str, str], ...] = (),
    ) -> None:
        embed = embeds.mod_action_embed(
            title=title,
            target=target,
            moderator=moderator,
            reason=reason,
            case=case,
            duration=seconds,
            color=color,
            extra=extra,
        )
        await send_mod_action(self.runtime, guild, embed, user=target)

    async def _apply_timeout(
        self,
        guild: discord.Guild,
        member: discord.Member,
        seconds: int,
        reason: str,
        moderator_id: int,
    ) -> Case:
        until = utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=truncate(reason, MAX_REASON))
        await self.runtime.repo.close_active_cases(
            guild.id,
            member.id,
            (CASE_TIMEOUT,),
            moderator_id,
            "Заменено новым наказанием",
        )
        return await self.runtime.repo.create_case(
            guild.id,
            member.id,
            moderator_id,
            CASE_TIMEOUT,
            truncate(reason, MAX_REASON),
            expires_at=to_iso(until),
        )

    async def _maybe_escalate(
        self,
        guild: discord.Guild,
        member: discord.Member,
        warning_count: int,
        moderator: discord.abc.User,
    ) -> None:
        config = await self.runtime.config(guild)
        rule = config.escalation_for(warning_count)
        if rule is None:
            return
        action = str(rule.get("action", "")).lower()
        seconds = int(rule.get("seconds", 0) or 0)
        reason = f"Автонаказание: {warning_count} предупреждений"
        case: Case | None = None
        applied = False

        try:
            if action == "timeout":
                seconds = seconds or 3600
                if _missing_perms(guild, "moderate_members"):
                    return
                case = await self._apply_timeout(guild, member, min(seconds, MAX_TIMEOUT), reason, self.bot.user.id)  # type: ignore[union-attr]
                applied = True
            elif action == "mute":
                role = guild.get_role(config.mute_role_id) if config.mute_role_id else None
                if role is None:
                    logger.warning("Автонаказание mute: роль мута не настроена на %s", guild.id)
                    return
                problem = hierarchy_error(guild, role)
                if problem:
                    logger.warning("Автонаказание mute не применено: %s", problem)
                    return
                await member.add_roles(role, reason=reason)
                await self.runtime.repo.close_active_cases(
                    guild.id,
                    member.id,
                    (CASE_MUTE,),
                    self.bot.user.id,  # type: ignore[union-attr]
                    "Заменено новым наказанием",
                )
                case = await self.runtime.repo.create_case(
                    guild.id,
                    member.id,
                    self.bot.user.id,  # type: ignore[union-attr]
                    CASE_MUTE,
                    reason,
                    expires_at=to_iso(utcnow() + timedelta(seconds=seconds)) if seconds else None,
                    extra={"role_id": role.id},
                )
                applied = True
            elif action == "kick":
                await member.kick(reason=reason)
                case = await self.runtime.repo.create_case(
                    guild.id,
                    member.id,
                    self.bot.user.id,  # type: ignore[union-attr]
                    CASE_KICK,
                    reason,
                    active=False,
                )
                applied = True
            elif action == "ban":
                await guild.ban(member, reason=reason, delete_message_seconds=0)
                await self.runtime.repo.close_active_cases(
                    guild.id,
                    member.id,
                    (CASE_BAN,),
                    self.bot.user.id,  # type: ignore[union-attr]
                    "Заменено новым наказанием",
                )
                case = await self.runtime.repo.create_case(
                    guild.id,
                    member.id,
                    self.bot.user.id,  # type: ignore[union-attr]
                    CASE_BAN,
                    reason,
                    expires_at=to_iso(utcnow() + timedelta(seconds=seconds)) if seconds else None,
                )
                applied = True
            else:
                logger.warning("Неизвестное действие автонаказания: %s", action)
        except discord.Forbidden:
            logger.warning("Недостаточно прав для автонаказания %s на %s", action, guild.id)
        except discord.HTTPException:
            logger.exception("Ошибка автонаказания %s на %s", action, guild.id)

        if not applied:
            return
        action_labels = {
            "timeout": "тайм-аут",
            "mute": "мут",
            "kick": "кик",
            "ban": "бан",
        }
        action_label = action_labels.get(action, action)
        try:
            await member.send(
                embed=embeds.warning(
                    f"Автонаказание · {guild.name}",
                    f"Достигнут порог **{warning_count}** предупреждений.\n"
                    f"Действие: **{action_label}**\nПричина: {reason}",
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
        await self._log(
            guild,
            title=f"Автонаказание · {action_label}",
            target=member,
            moderator=self.bot.user,  # type: ignore[arg-type]
            reason=reason,
            case=case,
            seconds=seconds or None,
            color=embeds.COLOR_ERROR,
            extra=(("Предупреждений", str(warning_count)),),
        )

    # ── Предупреждения ───────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(member="Кому выдать предупреждение", reason="Причина")
    @mod_only()
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        assert interaction.guild is not None
        problem = await ensure_target(interaction, member, action="выдать предупреждение")
        if problem:
            await interaction.response.send_message(embed=embeds.error("Нельзя", problem), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        warning = await self.runtime.repo.add_warning(
            interaction.guild.id, member.id, interaction.user.id, truncate(reason, MAX_REASON)
        )
        count = await self.runtime.repo.count_active_warnings(interaction.guild.id, member.id)

        await self._dm(
            member,
            guild_name=interaction.guild.name,
            action="Предупреждение",
            reason=reason,
        )
        embed = embeds.success(
            "Предупреждение выдано",
            f"{member.mention} получил предупреждение `#{warning.id}`.\n"
            f"Активных предупреждений: **{count}**.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await self._log(
            interaction.guild,
            title="Предупреждение",
            target=member,
            moderator=interaction.user,
            reason=reason,
            color=embeds.COLOR_WARN,
            extra=(("Предупреждение", f"`#{warning.id}`"), ("Всего активных", str(count))),
        )
        await self._maybe_escalate(interaction.guild, member, count, interaction.user)

    @app_commands.command(name="warnings", description="Показать предупреждения участника")
    @app_commands.describe(member="Чьи предупреждения показать")
    @mod_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        total = await self.runtime.repo.count_active_warnings(interaction.guild.id, member.id)
        warnings = await self.runtime.repo.list_warnings(
            interaction.guild.id, user_id=member.id, active_only=True, limit=25
        )
        embed = embeds.base(
            f"Предупреждения · {member}",
            f"Активных: **{total}**" + (" (показаны последние 25)" if total > 25 else ""),
            color=embeds.COLOR_WARN if warnings else embeds.COLOR_OK,
        )
        for warning in warnings:
            embed.add_field(
                name=f"#{warning.id} · {embeds.dt(parse_iso(warning.created_at), 'd')}",
                value=f"{truncate(warning.reason, 300)}\nМодератор: <@{warning.moderator_id}>",
                inline=False,
            )
        if not warnings:
            embed.description = "Активных предупреждений нет."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unwarn", description="Снять предупреждение по ID")
    @app_commands.describe(warning_id="ID предупреждения", reason="Причина снятия")
    @mod_only()
    async def unwarn(
        self, interaction: discord.Interaction, warning_id: int, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        warning = await self.runtime.repo.get_warning(warning_id)
        if warning is None or warning.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Предупреждение с таким ID не найдено."), ephemeral=True
            )
            return
        removed = await self.runtime.repo.deactivate_warning(
            warning_id, interaction.user.id, reason or "Снято модератором"
        )
        if not removed:
            await interaction.response.send_message(
                embed=embeds.warning("Уже снято", "Это предупреждение неактивно."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Предупреждение снято", f"`#{warning_id}` больше не учитывается."),
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            title="Предупреждение снято",
            target=interaction.guild.get_member(warning.user_id)
            or discord.Object(id=warning.user_id),
            moderator=interaction.user,
            reason=reason or "Снято модератором",
            color=embeds.COLOR_OK,
            extra=(("Предупреждение", f"`#{warning_id}`"),),
        )

    @app_commands.command(name="clearwarnings", description="Снять все предупреждения участника")
    @app_commands.describe(member="Кому снять все предупреждения", reason="Причина")
    @mod_only()
    async def clearwarnings(
        self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        count = await self.runtime.repo.clear_warnings(
            interaction.guild.id, member.id, interaction.user.id
        )
        if not count:
            await interaction.followup.send(
                embed=embeds.warning("Нечего снимать", "У участника нет активных предупреждений."),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=embeds.success("Готово", f"Снято предупреждений: **{count}**."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Все предупреждения сняты",
            target=member,
            moderator=interaction.user,
            reason=reason or "Очистка предупреждений",
            color=embeds.COLOR_OK,
            extra=(("Снято", str(count)),),
        )

    # ── Тайм-ауты и муты ─────────────────────────────────────────────────────

    @app_commands.command(name="timeout", description="Выдать временный тайм-аут")
    @app_commands.describe(member="Участник", duration="Например 10m, 1h30m, 7d", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str,
    ) -> None:
        assert interaction.guild is not None
        try:
            seconds = parse_duration(duration)
        except DurationError as exc:
            await interaction.response.send_message(embed=embeds.error("Длительность", str(exc)), ephemeral=True)
            return
        if seconds is None:
            await interaction.response.send_message(
                embed=embeds.error("Нужен срок", "Тайм-аут не может быть бессрочным."), ephemeral=True
            )
            return
        if seconds > MAX_TIMEOUT:
            await interaction.response.send_message(
                embed=embeds.error("Слишком долго", "Максимальный тайм-аут Discord — 28 дней."),
                ephemeral=True,
            )
            return
        problem = await ensure_target(interaction, member, action="выдать тайм-аут")
        if problem:
            await interaction.response.send_message(embed=embeds.error("Нельзя", problem), ephemeral=True)
            return
        permission_problem = _missing_perms(interaction.guild, "moderate_members")
        if permission_problem:
            await interaction.response.send_message(
                embed=embeds.error("Нет прав", permission_problem), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            case = await self._apply_timeout(
                interaction.guild, member, seconds, reason, interaction.user.id
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Discord запретил выдать тайм-аут."), ephemeral=True
            )
            return
        except discord.HTTPException:
            logger.exception("Ошибка тайм-аута")
            await interaction.followup.send(
                embed=embeds.error("Ошибка Discord", "Попробуйте ещё раз."), ephemeral=True
            )
            return

        await self._dm(
            member,
            guild_name=interaction.guild.name,
            action="Тайм-аут",
            reason=reason,
            duration=seconds,
            case_id=case.id,
        )
        await interaction.followup.send(
            embed=embeds.success(
                "Тайм-аут выдан",
                f"{member.mention} не сможет писать **{format_duration(seconds)}**.\nДело `#{case.id}`.",
            ),
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            title="Тайм-аут",
            target=member,
            moderator=interaction.user,
            reason=reason,
            case=case,
            seconds=seconds,
        )

    @app_commands.command(name="untimeout", description="Снять тайм-аут")
    @app_commands.describe(member="Участник", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(
        self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        if not member.is_timed_out():
            await interaction.response.send_message(
                embed=embeds.warning("Не в тайм-ауте", "У участника нет активного тайм-аута."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await member.timeout(None, reason=reason or "Снято модератором")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота."), ephemeral=True
            )
            return
        case = await self.runtime.repo.active_case(
            interaction.guild.id, member.id, (CASE_TIMEOUT,)
        )
        await self.runtime.repo.close_active_cases(
            interaction.guild.id,
            member.id,
            (CASE_TIMEOUT,),
            interaction.user.id,
            reason or "Снято модератором",
        )
        await interaction.followup.send(
            embed=embeds.success("Тайм-аут снят", f"С участника {member.mention} снят тайм-аут."),
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            title="Тайм-аут снят",
            target=member,
            moderator=interaction.user,
            reason=reason or "Снято модератором",
            case=case,
            color=embeds.COLOR_OK,
        )

    @app_commands.command(name="mute", description="Заглушить участника (роль или тайм-аут)")
    @app_commands.describe(member="Участник", duration="Например 1h, 7d", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str,
    ) -> None:
        assert interaction.guild is not None
        try:
            seconds = parse_duration(duration)
        except DurationError as exc:
            await interaction.response.send_message(embed=embeds.error("Длительность", str(exc)), ephemeral=True)
            return
        if seconds is None:
            await interaction.response.send_message(
                embed=embeds.error("Нужен срок", "Мут не может быть бессрочным."), ephemeral=True
            )
            return
        problem = await ensure_target(interaction, member, action="заглушить")
        if problem:
            await interaction.response.send_message(embed=embeds.error("Нельзя", problem), ephemeral=True)
            return

        config = await self.runtime.config(interaction.guild)
        role = interaction.guild.get_role(config.mute_role_id) if config.mute_role_id else None

        if role is None:
            # Роль мута не настроена — используем нативный тайм-аут.
            permission_problem = _missing_perms(interaction.guild, "moderate_members")
            if permission_problem:
                await interaction.response.send_message(
                    embed=embeds.error("Нет прав", permission_problem), ephemeral=True
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                case = await self._apply_timeout(
                    interaction.guild, member, min(seconds, MAX_TIMEOUT), reason, interaction.user.id
                )
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send(
                    embed=embeds.error("Не удалось", "Discord запретил выдать тайм-аут."), ephemeral=True
                )
                return
            await self._dm(
                member,
                guild_name=interaction.guild.name,
                action="Мут (тайм-аут)",
                reason=reason,
                duration=seconds,
                case_id=case.id,
            )
            await interaction.followup.send(
                embed=embeds.success(
                    "Мут выдан",
                    f"{member.mention} заглушен на **{format_duration(seconds)}** (тайм-аут).",
                ),
                ephemeral=True,
            )
            await self._log(
                interaction.guild,
                title="Мут (тайм-аут)",
                target=member,
                moderator=interaction.user,
                reason=reason,
                case=case,
                seconds=seconds,
            )
            return

        role_problem = hierarchy_error(interaction.guild, role)
        if role_problem:
            await interaction.response.send_message(
                embed=embeds.error("Роль мута недоступна", role_problem), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await member.add_roles(role, reason=truncate(reason, MAX_REASON))
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота и иерархию ролей."),
                ephemeral=True,
            )
            return
        case = await self.runtime.repo.create_case(
            interaction.guild.id,
            member.id,
            interaction.user.id,
            CASE_MUTE,
            truncate(reason, MAX_REASON),
            expires_at=to_iso(utcnow() + timedelta(seconds=seconds)),
            extra={"role_id": role.id},
        )
        await self._dm(
            member,
            guild_name=interaction.guild.name,
            action="Мут",
            reason=reason,
            duration=seconds,
            case_id=case.id,
        )
        await interaction.followup.send(
            embed=embeds.success(
                "Мут выдан",
                f"{member.mention} заглушен на **{format_duration(seconds)}**.\nДело `#{case.id}`.",
            ),
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            title="Мут",
            target=member,
            moderator=interaction.user,
            reason=reason,
            case=case,
            seconds=seconds,
        )

    @app_commands.command(name="unmute", description="Снять мут")
    @app_commands.describe(member="Участник", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(
        self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = await self.runtime.config(interaction.guild)
        role = interaction.guild.get_role(config.mute_role_id) if config.mute_role_id else None
        removed = False
        try:
            if role is not None and role in member.roles:
                await member.remove_roles(role, reason=reason or "Снято модератором")
                removed = True
            if member.is_timed_out():
                await member.timeout(None, reason=reason or "Снято модератором")
                removed = True
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота."), ephemeral=True
            )
            return
        if not removed:
            await interaction.followup.send(
                embed=embeds.warning("Не заглушен", "У участника нет активного мута."), ephemeral=True
            )
            return
        case = await self.runtime.repo.active_case(
            interaction.guild.id, member.id, (CASE_MUTE, CASE_TIMEOUT)
        )
        await self.runtime.repo.close_active_cases(
            interaction.guild.id,
            member.id,
            (CASE_MUTE, CASE_TIMEOUT),
            interaction.user.id,
            reason or "Снято модератором",
        )
        await interaction.followup.send(
            embed=embeds.success("Мут снят", f"{member.mention} снова может говорить."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Мут снят",
            target=member,
            moderator=interaction.user,
            reason=reason or "Снято модератором",
            case=case,
            color=embeds.COLOR_OK,
        )

    # ── Баны и кики ──────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Забанить участника (можно на срок)")
    @app_commands.describe(
        user="Кого забанить",
        duration="Срок, например 7d; пусто — навсегда",
        reason="Причина",
        clean="Удалить сообщения за N дней (0–7)",
    )
    @mod_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        duration: str | None = None,
        clean: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        assert interaction.guild is not None
        member = interaction.guild.get_member(user.id)
        if member is not None:
            problem = await ensure_target(interaction, member, action="забанить")
            if problem:
                await interaction.response.send_message(embed=embeds.error("Нельзя", problem), ephemeral=True)
                return
        elif user.id in (self.bot.user.id, interaction.guild.owner_id):
            await interaction.response.send_message(
                embed=embeds.error("Нельзя", "Этого пользователя нельзя забанить."), ephemeral=True
            )
            return

        seconds: int | None = None
        if duration:
            try:
                seconds = parse_duration(duration)
            except DurationError as exc:
                await interaction.response.send_message(
                    embed=embeds.error("Длительность", str(exc)), ephemeral=True
                )
                return
        permission_problem = _missing_perms(interaction.guild, "ban_members")
        if permission_problem:
            await interaction.response.send_message(
                embed=embeds.error("Нет прав", permission_problem), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._dm(
            user,
            guild_name=interaction.guild.name,
            action="Бан" if seconds is None else "Временный бан",
            reason=reason,
            duration=seconds,
        )
        try:
            await interaction.guild.ban(
                user,
                reason=truncate(reason, MAX_REASON),
                delete_message_seconds=clean * 86400,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Discord запретил бан."), ephemeral=True
            )
            return
        except discord.HTTPException:
            logger.exception("Ошибка бана %s", user.id)
            await interaction.followup.send(
                embed=embeds.error("Ошибка Discord", "Попробуйте ещё раз."), ephemeral=True
            )
            return

        case = await self.runtime.repo.create_case(
            interaction.guild.id,
            user.id,
            interaction.user.id,
            CASE_BAN,
            truncate(reason, MAX_REASON),
            expires_at=to_iso(utcnow() + timedelta(seconds=seconds)) if seconds else None,
        )
        duration_text = format_duration(seconds)
        await interaction.followup.send(
            embed=embeds.success(
                "Бан выдан",
                f"**{user}** забанен {'на ' + duration_text if seconds else 'навсегда'}.\nДело `#{case.id}`.",
            ),
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            title="Бан",
            target=user,
            moderator=interaction.user,
            reason=reason,
            case=case,
            seconds=seconds,
            color=embeds.COLOR_ERROR,
            extra=(("Длительность", "бессрочно"),) if seconds is None else (),
        )

    @app_commands.command(name="unban", description="Разбанить пользователя")
    @app_commands.describe(user="Кого разбанить", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(
        self, interaction: discord.Interaction, user: discord.User, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.guild.unban(user, reason=reason or "Разбан")
        except discord.NotFound:
            await interaction.followup.send(
                embed=embeds.warning("Не забанен", "Этот пользователь не находится в бане."),
                ephemeral=True,
            )
            return
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота."), ephemeral=True
            )
            return
        case = await self.runtime.repo.active_case(interaction.guild.id, user.id, (CASE_BAN,))
        await self.runtime.repo.close_active_cases(
            interaction.guild.id,
            user.id,
            (CASE_BAN,),
            interaction.user.id,
            reason or "Разбан",
        )
        await interaction.followup.send(
            embed=embeds.success("Разбанен", f"**{user}** больше не забанен."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Разбан",
            target=user,
            moderator=interaction.user,
            reason=reason or "Разбан",
            case=case,
            color=embeds.COLOR_OK,
        )

    @app_commands.command(name="kick", description="Кикнуть участника")
    @app_commands.describe(member="Участник", reason="Причина")
    @mod_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        assert interaction.guild is not None
        problem = await ensure_target(interaction, member, action="кикнуть")
        if problem:
            await interaction.response.send_message(embed=embeds.error("Нельзя", problem), ephemeral=True)
            return
        permission_problem = _missing_perms(interaction.guild, "kick_members")
        if permission_problem:
            await interaction.response.send_message(
                embed=embeds.error("Нет прав", permission_problem), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._dm(
            member,
            guild_name=interaction.guild.name,
            action="Кик",
            reason=reason,
        )
        try:
            await member.kick(reason=truncate(reason, MAX_REASON))
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота."), ephemeral=True
            )
            return
        case = await self.runtime.repo.create_case(
            interaction.guild.id,
            member.id,
            interaction.user.id,
            CASE_KICK,
            truncate(reason, MAX_REASON),
            active=False,
        )
        await interaction.followup.send(
            embed=embeds.success("Кикнут", f"**{member}** исключён с сервера."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Кик",
            target=member,
            moderator=interaction.user,
            reason=reason,
            case=case,
            color=embeds.COLOR_WARN,
        )

    # ── Массовое удаление ────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Удалить сообщения в канале")
    @app_commands.describe(count="Сколько сообщений (1–100)", member="Только сообщения участника")
    @mod_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 100],
        member: discord.Member | None = None,
    ) -> None:
        assert interaction.guild is not None
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                embed=embeds.error("Не тот канал", "Очистка доступна только в текстовых каналах."),
                ephemeral=True,
            )
            return
        permission_problem = _missing_perms(interaction.guild, "manage_messages")
        if permission_problem:
            await interaction.response.send_message(
                embed=embeds.error("Нет прав", permission_problem), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        check = (lambda message: message.author.id == member.id) if member else None
        try:
            deleted = await channel.purge(
                limit=count,
                check=check,
                reason=f"Очистка модератором {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Discord запретил удаление сообщений."), ephemeral=True
            )
            return
        suffix = f" от {member.mention}" if member else ""
        await interaction.followup.send(
            embed=embeds.success("Очищено", f"Удалено сообщений{suffix}: **{len(deleted)}**."),
            ephemeral=True,
        )

    # ── История дел ──────────────────────────────────────────────────────────

    @app_commands.command(name="cases", description="Последние наказания")
    @app_commands.describe(member="Только по этому участнику")
    @mod_only()
    async def cases(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        assert interaction.guild is not None
        cases = await self.runtime.repo.list_cases(
            interaction.guild.id, user_id=member.id if member else None, limit=15
        )
        title = f"Наказания · {member}" if member else "Последние наказания"
        embed = embeds.base(title, color=embeds.COLOR_MOD)
        if not cases:
            embed.description = "Наказаний пока нет."
        for case in cases:
            status = "🟢" if case.active else "⚫"
            embed.add_field(
                name=f"{status} #{case.id} · {case.kind_label}",
                value=(
                    f"<@{case.user_id}> · {truncate(case.reason, 120)}\n"
                    f"{embeds.dt(parse_iso(case.created_at), 'R')}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    case = app_commands.Group(name="case", description="Управление конкретным наказанием")

    @case.command(name="view", description="Показать наказание")
    @app_commands.describe(case_id="ID наказания")
    @mod_only()
    async def case_view(self, interaction: discord.Interaction, case_id: int) -> None:
        assert interaction.guild is not None
        case = await self.runtime.repo.get_case(case_id, interaction.guild.id)
        if case is None:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Наказание с таким ID не найдено."), ephemeral=True
            )
            return
        await interaction.response.send_message(embed=self._case_embed(case), ephemeral=True)

    @case.command(name="reason", description="Изменить причину наказания")
    @app_commands.describe(case_id="ID наказания", reason="Новая причина")
    @mod_only()
    async def case_reason(
        self, interaction: discord.Interaction, case_id: int, reason: str
    ) -> None:
        assert interaction.guild is not None
        case = await self.runtime.repo.get_case(case_id, interaction.guild.id)
        if case is None:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Наказание с таким ID не найдено."), ephemeral=True
            )
            return
        await self.runtime.repo.update_case_reason(case_id, truncate(reason, MAX_REASON))
        await interaction.response.send_message(
            embed=embeds.success("Причина обновлена", f"Дело `#{case_id}` обновлено."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Причина наказания изменена",
            target=interaction.guild.get_member(case.user_id)
            or discord.Object(id=case.user_id),
            moderator=interaction.user,
            reason=reason,
            case=case,
            color=embeds.COLOR_LOG,
        )

    @case.command(name="close", description="Досрочно завершить наказание")
    @app_commands.describe(case_id="ID наказания", reason="Причина")
    @mod_only()
    async def case_close(
        self, interaction: discord.Interaction, case_id: int, reason: str | None = None
    ) -> None:
        assert interaction.guild is not None
        case = await self.runtime.repo.get_case(case_id, interaction.guild.id)
        if case is None or not case.active:
            await interaction.response.send_message(
                embed=embeds.warning("Нельзя закрыть", "Дело не найдено или уже завершено."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = interaction.guild.get_member(case.user_id)
        try:
            if case.kind == CASE_BAN:
                await interaction.guild.unban(
                    discord.Object(id=case.user_id), reason=reason or "Досрочное завершение"
                )
            elif case.kind == CASE_TIMEOUT and member is not None:
                await member.timeout(None, reason=reason or "Досрочное завершение")
            elif case.kind == CASE_MUTE and member is not None:
                role_id = int(case.extra.get("role_id") or 0)
                role = interaction.guild.get_role(role_id) if role_id else None
                if role is not None and role in member.roles:
                    await member.remove_roles(role, reason=reason or "Досрочное завершение")
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send(
                embed=embeds.error("Не удалось", "Проверьте права бота."), ephemeral=True
            )
            return
        await self.runtime.repo.close_case(
            case_id, interaction.user.id, reason or "Завершено модератором"
        )
        await interaction.followup.send(
            embed=embeds.success("Наказание завершено", f"Дело `#{case_id}` закрыто."), ephemeral=True
        )
        await self._log(
            interaction.guild,
            title="Наказание завершено досрочно",
            target=interaction.guild.get_member(case.user_id)
            or discord.Object(id=case.user_id),
            moderator=interaction.user,
            reason=reason or "Завершено модератором",
            case=case,
            color=embeds.COLOR_OK,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
