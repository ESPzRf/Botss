"""Клиент Discord и загрузка когов."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.runtime import Runtime
from app.core import __version__
from app.core.utils import utcnow

logger = logging.getLogger(__name__)

COG_EXTENSIONS: tuple[str, ...] = (
    "app.bot.cogs.core",
    "app.bot.cogs.event_logs",
    "app.bot.cogs.autoroles",
    "app.bot.cogs.role_panels",
    "app.bot.cogs.moderation",
    "app.bot.cogs.punishments",
    "app.bot.cogs.xp",
    "app.bot.cogs.achievements",
    "app.bot.cogs.loyalty",
    "app.bot.cogs.shop",
)


class ModerationBot(commands.Bot):
    def __init__(self, runtime: Runtime) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
        )
        self.runtime = runtime
        self.launch_time = utcnow()
        self.version = __version__
        self._bootstrapped = False

    async def setup_hook(self) -> None:
        await self.runtime.db.connect()

        async def guild_only_check(interaction: discord.Interaction) -> bool:
            if interaction.guild is None:
                raise app_commands.NoPrivateMessage("Команды Guardian работают только на сервере.")
            return True

        self.tree.interaction_check = guild_only_check

        for extension in COG_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.debug("Ког загружен: %s", extension)
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось загрузить ког %s", extension)
        await self._sync_commands()
        logger.info("Инициализация завершена")

    async def _sync_commands(self) -> None:
        dev_guild_id = self.runtime.settings.dev_guild_id
        try:
            if dev_guild_id:
                guild = discord.Object(id=dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Синхронизировано %s команд для сервера %s", len(synced), dev_guild_id)
            else:
                synced = await self.tree.sync()
                logger.info("Синхронизировано %s глобальных команд", len(synced))
        except discord.HTTPException:
            logger.exception("Не удалось синхронизировать слэш-команды")

    async def on_ready(self) -> None:
        logger.info(
            "Бот подключён как %s (ID %s), серверов: %s", self.user, getattr(self.user, "id", "?"), len(self.guilds)
        )
        try:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"{len(self.guilds)} серверов · /help",
                ),
                status=discord.Status.online,
            )
        except discord.HTTPException:
            pass
        if not self._bootstrapped:
            self._bootstrapped = True
            self.loop.create_task(self._bootstrap_guilds())

    async def _bootstrap_guilds(self) -> None:
        await self.wait_until_ready()
        for guild in list(self.guilds):
            try:
                icon = guild.icon.url if guild.icon else None
                await self.runtime.repo.touch_guild_meta(guild.id, guild.name, icon)
                await self.runtime.config(guild, refresh=True)
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось подготовить настройки сервера %s", guild.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        logger.info("Бот добавлен на сервер %s (%s)", guild.name, guild.id)
        await self.runtime.config(guild, refresh=True)
        channel = guild.system_channel
        if channel is None:
            return
        dashboard = self.runtime.settings.dashboard_url
        if "localhost" in dashboard or "127.0.0.1" in dashboard:
            dashboard_line = (
                "Дашборд запущен локально и доступен администраторам через SSH-туннель."
            )
        else:
            dashboard_line = f"Дашборд: {dashboard}"
        try:
            embed = discord.Embed(
                title="Привет! Я Guardian",
                description=(
                    "Я помогаю с модерацией, логами, авторолями и системой прогресса.\n\n"
                    f"{dashboard_line}\n"
                    "Список команд: `/help`"
                ),
                color=0x5865F2,
            )
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self.runtime.invalidate_config(guild.id)

    async def close(self) -> None:
        logger.info("Отключение бота…")
        for name in list(self.cogs):
            try:
                await self.remove_cog(name)
            except Exception:  # noqa: BLE001
                logger.debug("Не удалось выгрузить ког %s", name, exc_info=True)
        await super().close()
