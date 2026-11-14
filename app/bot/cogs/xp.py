"""Ког опыта: сообщения, голос, уровни, топ и управление XP."""

from __future__ import annotations

import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot import embeds
from app.bot.checks import admin_only
from app.bot.services.progress import check_achievements, handle_level_up
from app.core.levels import format_number, level_progress, progress_bar
from app.core.utils import truncate

logger = logging.getLogger(__name__)


class XP(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]
        self._cooldowns: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        self.voice_loop.start()

    async def cog_unload(self) -> None:
        self.voice_loop.cancel()

    # ── Начисление опыта ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.is_system():
            return
        if not message.content and not message.attachments:
            return

        try:
            config = await self.runtime.config(message.guild)
        except Exception:  # noqa: BLE001
            logger.exception("XP: не удалось прочитать настройки %s", message.guild.id)
            return
        if not config.xp_enabled and not config.loyalty_enabled:
            return
        if message.channel.id in config.xp_ignore_channels:
            return
        if any(role.id in config.xp_ignore_roles for role in getattr(message.author, "roles", [])):
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self._cooldowns.get(key, 0.0) < max(0, config.xp_cooldown):
            return
        self._cooldowns[key] = now
        if len(self._cooldowns) > 20000:
            cutoff = now - 7200
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}

        xp_amount = 0
        if config.xp_enabled:
            xp_min, xp_max = config.xp_min, config.xp_max
            if xp_min > xp_max:
                xp_min, xp_max = xp_max, xp_min
            xp_amount = random.randint(max(0, xp_min), max(0, xp_max))
        loyalty = 0
        if config.loyalty_enabled and config.loyalty_per_message > 0:
            loyalty = config.loyalty_per_message
        if xp_amount <= 0 and loyalty <= 0:
            return

        stats, old_level = await self.runtime.repo.add_message_progress(
            message.guild.id, message.author.id, xp_amount, loyalty
        )
        if xp_amount > 0 and stats.level > old_level:
            await handle_level_up(self.runtime, message.guild, message.author, stats, old_level)
        elif config.achievements_enabled:
            await check_achievements(self.runtime, message.guild, message.author, stats)

    @tasks.loop(minutes=1)
    async def voice_loop(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                config = await self.runtime.config(guild)
            except Exception:  # noqa: BLE001
                continue
            if not config.xp_enabled and not config.loyalty_enabled:
                continue
            for channel in list(guild.voice_channels):
                if guild.afk_channel is not None and channel.id == guild.afk_channel.id:
                    continue
                if channel.id in config.xp_ignore_channels:
                    continue
                humans = [
                    member
                    for member in channel.members
                    if not member.bot and not member.voice.deaf and not member.voice.self_deaf
                ]
                if len(humans) < 2:
                    continue
                for member in humans:
                    if any(role.id in config.xp_ignore_roles for role in member.roles):
                        continue
                    xp_amount = config.xp_voice_per_min if config.xp_enabled else 0
                    if xp_amount <= 0 and not config.loyalty_enabled:
                        continue
                    loyalty = (
                        config.loyalty_per_voice_min
                        if config.loyalty_enabled and config.loyalty_per_voice_min > 0
                        else 0
                    )
                    try:
                        stats, old_level = await self.runtime.repo.add_voice_progress(
                            guild.id,
                            member.id,
                            xp_amount,
                            loyalty,
                            60,
                        )
                        if xp_amount > 0 and stats.level > old_level:
                            await handle_level_up(self.runtime, guild, member, stats, old_level)
                        elif config.achievements_enabled and stats.voice_minutes % 5 == 0:
                            await check_achievements(self.runtime, guild, member, stats)
                    except Exception:  # noqa: BLE001
                        logger.exception("XP: ошибка начисления голосового опыта %s", member.id)

    @voice_loop.before_loop
    async def before_voice(self) -> None:
        if not hasattr(getattr(self.bot, "_ready", None), "wait"):
            return
        await self.bot.wait_until_ready()

    # ── Команды ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="Показать карточку опыта")
    @app_commands.describe(member="Чью карточку показать")
    async def rank(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        assert interaction.guild is not None
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Участник не найден на сервере."), ephemeral=True
            )
            return
        stats = await self.runtime.repo.get_stats(interaction.guild.id, target.id)
        position = await self.runtime.repo.rank_position(interaction.guild.id, target.id)
        level, current, needed, percent = level_progress(stats.xp)

        embed = embeds.base(f"📊 {target.display_name}", color=embeds.COLOR_XP)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Уровень", value=f"**{level}**", inline=True)
        embed.add_field(name="Опыт", value=f"**{format_number(stats.xp)}** XP", inline=True)
        embed.add_field(name="Место", value=f"**#{position}**", inline=True)
        embed.add_field(name="Сообщения", value=format_number(stats.messages), inline=True)
        embed.add_field(
            name="В голосе",
            value=f"{stats.voice_minutes // 60} ч {stats.voice_minutes % 60} мин",
            inline=True,
        )
        embed.add_field(name="Лояльность", value=f"**{format_number(stats.loyalty)}**", inline=True)
        embed.add_field(
            name="До следующего уровня",
            value=f"{progress_bar(percent)} {current}/{needed}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Топ участников по опыту")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        top = await self.runtime.repo.leaderboard(interaction.guild.id, limit=10)
        embed = embeds.base("🏆 Топ по опыту", color=embeds.COLOR_XP)
        if not top:
            embed.description = "Пока никто не получал опыт."
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for index, stats in enumerate(top, start=1):
            member = interaction.guild.get_member(stats.user_id)
            name = member.display_name if member else f"Пользователь {stats.user_id}"
            lines.append(
                f"{medals.get(index, f'`#{index}`')} **{truncate(name, 40)}** — "
                f"{format_number(stats.xp)} XP · ур. {stats.level}"
            )
        if lines:
            embed.description = "\n".join(lines)
        own = await self.runtime.repo.get_stats(interaction.guild.id, interaction.user.id)
        own_place = await self.runtime.repo.rank_position(interaction.guild.id, interaction.user.id)
        embed.set_footer(text=f"Ваше место: #{own_place} · {format_number(own.xp)} XP")
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

    xp = app_commands.Group(
        name="xp",
        description="Управление опытом участников",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @xp.command(name="add", description="Начислить опыт")
    @app_commands.describe(member="Участник", amount="Количество опыта")
    @admin_only()
    async def xp_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        assert interaction.guild is not None
        stats, old_level = await self.runtime.repo.add_xp(interaction.guild.id, member.id, amount)
        if stats.level > old_level:
            await handle_level_up(self.runtime, interaction.guild, member, stats, old_level)
        await interaction.response.send_message(
            embed=embeds.success(
                "Опыт начислен",
                f"{member.mention}: +{amount} XP (всего {format_number(stats.xp)}, ур. {stats.level}).",
            ),
            ephemeral=True,
        )

    @xp.command(name="remove", description="Снять опыт")
    @app_commands.describe(member="Участник", amount="Количество опыта")
    @admin_only()
    async def xp_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        assert interaction.guild is not None
        stats, _ = await self.runtime.repo.add_xp(interaction.guild.id, member.id, -amount)
        await interaction.response.send_message(
            embed=embeds.success(
                "Опыт снят",
                f"{member.mention}: −{amount} XP (осталось {format_number(stats.xp)}, ур. {stats.level}).",
            ),
            ephemeral=True,
        )

    @xp.command(name="reset", description="Сбросить опыт и статистику участника")
    @app_commands.describe(member="Участник")
    @admin_only()
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        await self.runtime.repo.reset_stats(interaction.guild.id, member.id)
        await interaction.response.send_message(
            embed=embeds.success("Сброшено", f"Статистика {member.mention} удалена."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XP(bot))
