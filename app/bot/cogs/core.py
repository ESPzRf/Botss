"""Базовые команды: помощь, статус, ссылка на дашборд."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.core import __version__
from app.core.durations import format_duration

logger = logging.getLogger(__name__)

HELP_SECTIONS = (
    (
        "🛡️ Модерация",
        [
            ("/warn", "выдать предупреждение"),
            ("/warnings", "список предупреждений участника"),
            ("/unwarn", "снять предупреждение по ID"),
            ("/timeout", "временный тайм-аут"),
            ("/mute", "мут ролью или тайм-аут"),
            ("/ban", "бан (можно временный)"),
            ("/kick", "кик участника"),
            ("/purge", "массовое удаление сообщений"),
            ("/cases", "история наказаний"),
        ],
    ),
    (
        "📈 Прогресс",
        [
            ("/rank", "карточка опыта"),
            ("/leaderboard", "топ по опыту"),
            ("/achievements", "достижения"),
            ("/balance", "баллы лояльности"),
            ("/shop", "магазин ролей"),
        ],
    ),
    (
        "⚙️ Настройка",
        [
            ("/settings", "текущие настройки и ссылка на дашборд"),
            ("/panel", "панели ролей с кнопками"),
            ("/botinfo", "информация о боте"),
        ],
    ),
)


class Core(commands.Cog):
    """Служебные команды и централизованная обработка ошибок."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        self.bot.tree.on_error = self.on_tree_error

    async def cog_unload(self) -> None:
        self.bot.tree.on_error = None  # type: ignore[assignment]

    # ── Обработка ошибок слэш-команд ─────────────────────────────────────────

    async def on_tree_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original: BaseException = error
        if isinstance(error, app_commands.CommandInvokeError):
            original = error.original

        if isinstance(original, app_commands.CheckFailure):
            message = str(original) or "Недостаточно прав для этой команды."
            embed = embeds.error("Нет доступа", message)
        elif isinstance(original, app_commands.CommandOnCooldown):
            embed = embeds.warning(
                "Слишком часто", f"Попробуйте через {original.retry_after:.0f} сек."
            )
        elif isinstance(original, app_commands.BotMissingPermissions):
            embed = embeds.error(
                "Боту не хватает прав",
                "Выдайте боту: " + ", ".join(original.missing_permissions),
            )
        elif isinstance(original, app_commands.MissingPermissions):
            embed = embeds.error(
                "Вам не хватает прав",
                "Нужно: " + ", ".join(original.missing_permissions),
            )
        else:
            logger.error(
                "Ошибка команды %s",
                getattr(interaction.command, "qualified_name", "?"),
                exc_info=(type(original), original, original.__traceback__),
            )
            embed = embeds.error(
                "Что-то пошло не так",
                "Команда не выполнилась. Ошибка записана в журнал бота.",
            )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            logger.debug("Не удалось отправить сообщение об ошибке: interaction истёк")

    # ── Команды ──────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Список команд Guardian")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = embeds.base(
            "Guardian · команды",
            "Модерация, логи, автороли и прогресс. Настройка — в веб-дашборде.",
        )
        for title, items in HELP_SECTIONS:
            embed.add_field(
                name=title,
                value="\n".join(f"`{command}` — {description}" for command, description in items),
                inline=False,
            )
        embed.add_field(
            name="Дашборд",
            value=self.runtime.settings.dashboard_url,
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Проверить задержку бота")
    async def ping(self, interaction: discord.Interaction) -> None:
        started = time.perf_counter()
        await interaction.response.send_message("🏓 Измеряю…")
        elapsed = (time.perf_counter() - started) * 1000
        await interaction.edit_original_response(
            content=(
                f"🏓 **Понг!**\n"
                f"WebSocket: `{self.bot.latency * 1000:.0f} мс`\n"
                f"Ответ: `{elapsed:.0f} мс`"
            )
        )

    @app_commands.command(name="botinfo", description="Информация о боте")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        embed = embeds.base("Guardian", "Бот модерации с дашбордом управления.")
        embed.add_field(name="Версия", value=f"`{__version__}`", inline=True)
        embed.add_field(name="Серверов", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(
            name="Участников",
            value=f"`{sum(guild.member_count or 0 for guild in self.bot.guilds):,}`".replace(",", " "),
            inline=True,
        )
        embed.add_field(name="Задержка", value=f"`{self.bot.latency * 1000:.0f} мс`", inline=True)
        embed.add_field(
            name="Аптайм",
            value=f"`{format_duration(self.runtime.uptime_seconds)}`",
            inline=True,
        )
        embed.add_field(name="Дашборд", value=self.runtime.settings.dashboard_url, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="Показать настройки сервера и ссылку на дашборд")
    @app_commands.guild_only()
    async def settings_command(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        config = await self.runtime.config(interaction.guild)
        log_channel = (
            f"<#{config.log_channel_id}>" if config.log_channel_id else "не задан"
        )
        mod_channel = (
            f"<#{config.mod_log_channel_id}>" if config.mod_log_channel_id else "как канал логов"
        )
        embed = embeds.base(
            f"Настройки · {interaction.guild.name}",
            f"Полная настройка доступна в [дашборде]({self.runtime.settings.dashboard_url}).",
        )
        embed.add_field(name="Канал логов", value=log_channel, inline=True)
        embed.add_field(name="Канал модерации", value=mod_channel, inline=True)
        embed.add_field(name="Автороли", value=f"`{len(config.autorole_ids)}`", inline=True)
        embed.add_field(name="Опыт", value="включён" if config.xp_enabled else "выключен", inline=True)
        embed.add_field(
            name="Лояльность",
            value="включена" if config.loyalty_enabled else "выключена",
            inline=True,
        )
        embed.add_field(
            name="Достижения",
            value=f"`{len(await self.runtime.repo.list_achievements(interaction.guild.id, enabled_only=True))}` активно",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
