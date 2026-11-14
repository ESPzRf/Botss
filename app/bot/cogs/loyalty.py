"""Ког лояльности: баланс, выдача баллов и топ."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.checks import admin_only
from app.core.levels import format_number


class Loyalty(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    @app_commands.command(name="balance", description="Показать баланс баллов лояльности")
    @app_commands.describe(member="Чей баланс показать")
    async def balance(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        assert interaction.guild is not None
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Участник не найден."), ephemeral=True
            )
            return
        stats = await self.runtime.repo.get_stats(interaction.guild.id, target.id)
        embed = embeds.base(
            f"💎 Лояльность · {target.display_name}",
            f"Баланс: **{format_number(stats.loyalty)}** баллов",
            color=embeds.COLOR_XP,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Сообщения", value=format_number(stats.messages), inline=True)
        embed.add_field(name="Голос", value=f"{stats.voice_minutes} мин", inline=True)
        embed.add_field(
            name="Как получить",
            value="Баллы начисляются за сообщения и время в голосовых каналах.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    loyalty = app_commands.Group(name="loyalty", description="Управление баллами лояльности")

    @loyalty.command(name="give", description="Начислить баллы участнику")
    @app_commands.describe(member="Участник", amount="Сколько баллов начислить")
    @admin_only()
    async def give(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        assert interaction.guild is not None
        await self.runtime.repo.add_loyalty(interaction.guild.id, member.id, amount)
        stats = await self.runtime.repo.get_stats(interaction.guild.id, member.id)
        await interaction.response.send_message(
            embed=embeds.success(
                "Баллы начислены",
                f"{member.mention} получил **{amount}** баллов.\nБаланс: **{format_number(stats.loyalty)}**.",
            ),
            ephemeral=True,
        )

    @loyalty.command(name="take", description="Снять баллы у участника")
    @app_commands.describe(member="Участник", amount="Сколько баллов снять")
    @admin_only()
    async def take(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        assert interaction.guild is not None
        await self.runtime.repo.add_loyalty(interaction.guild.id, member.id, -amount)
        stats = await self.runtime.repo.get_stats(interaction.guild.id, member.id)
        await interaction.response.send_message(
            embed=embeds.success(
                "Баллы сняты",
                f"У {member.mention} снято **{amount}** баллов.\nБаланс: **{format_number(stats.loyalty)}**.",
            ),
            ephemeral=True,
        )

    @loyalty.command(name="top", description="Топ по баллам лояльности")
    async def top(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        top = await self.runtime.repo.loyalty_leaderboard(interaction.guild.id, limit=10)
        embed = embeds.base("💎 Топ по лояльности", color=embeds.COLOR_XP)
        if not top:
            embed.description = "Пока ни у кого нет баллов."
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for index, stats in enumerate(top, start=1):
            member = interaction.guild.get_member(stats.user_id)
            name = member.display_name if member else f"Пользователь {stats.user_id}"
            lines.append(f"{medals.get(index, f'`#{index}`')} **{name}** — {format_number(stats.loyalty)}")
        if lines:
            embed.description = "\n".join(lines)
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Loyalty(bot))
