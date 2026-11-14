"""Ког достижений: просмотр, прогресс и периодическая проверка."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot import embeds
from app.bot.services.progress import achievement_progress_text, check_achievements
from app.core.defaults import CONDITION_LABELS
from app.core.utils import utcnow

logger = logging.getLogger(__name__)


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        self.sweep_loop.start()

    async def cog_unload(self) -> None:
        self.sweep_loop.cancel()

    @tasks.loop(hours=6)
    async def sweep_loop(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                config = await self.runtime.config(guild)
                if not config.achievements_enabled:
                    continue
                tracked = await self.runtime.repo.list_tracked_stats(guild.id, limit=5000)
                for stats in tracked:
                    member = guild.get_member(stats.user_id)
                    if member is None:
                        continue
                    try:
                        await check_achievements(self.runtime, guild, member, stats)
                    except Exception:  # noqa: BLE001
                        logger.exception("Ошибка проверки достижений %s", member.id)
                    await asyncio.sleep(0.05)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка фоновой проверки достижений на сервере %s", guild.id)

    @sweep_loop.before_loop
    async def before_sweep(self) -> None:
        if not hasattr(getattr(self.bot, "_ready", None), "wait"):
            return
        await self.bot.wait_until_ready()

    @app_commands.command(name="achievements", description="Достижения участника")
    @app_commands.describe(member="Чьи достижения показать")
    async def achievements(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        assert interaction.guild is not None
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Участник не найден."), ephemeral=True
            )
            return

        config = await self.runtime.config(interaction.guild)
        if not config.achievements_enabled:
            await interaction.response.send_message(
                embed=embeds.warning("Достижения выключены", "Система достижений отключена на сервере."),
                ephemeral=True,
            )
            return

        achievements = await self.runtime.repo.list_achievements(interaction.guild.id)
        unlocked = await self.runtime.repo.unlocked_achievement_ids(interaction.guild.id, target.id)
        stats = await self.runtime.repo.get_stats(interaction.guild.id, target.id)
        days = 0
        if target.joined_at is not None:
            days = max(0, (utcnow() - target.joined_at).days)

        embed = embeds.base(
            f"🏆 Достижения · {target.display_name}",
            f"Открыто **{len(unlocked)}** из **{len(achievements)}**",
            color=embeds.COLOR_XP,
        )
        lines: list[str] = []
        for achievement in achievements[:30]:
            is_unlocked = achievement.id in unlocked
            mark = "✅" if is_unlocked else "🔒"
            line = f"{mark} {achievement.emoji} **{achievement.title}** — {achievement.description}"
            if not is_unlocked:
                line += f"\n　　`{achievement_progress_text(achievement, stats, days)}`"
                line += f" · {CONDITION_LABELS.get(achievement.condition_type, achievement.condition_type)}"
            lines.append(line)
        if not lines:
            embed.description = "Достижения ещё не настроены."
        else:
            chunk: list[str] = []
            for line in lines:
                if sum(len(part) + 1 for part in chunk) + len(line) > 1000:
                    embed.add_field(name="​", value="\n".join(chunk), inline=False)
                    chunk = []
                chunk.append(line)
            if chunk:
                embed.add_field(name="​", value="\n".join(chunk), inline=False)
            if len(achievements) > len(lines):
                embed.add_field(
                    name="​",
                    value=f"Показаны первые {len(lines)} из {len(achievements)} достижений.",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Achievements(bot))
