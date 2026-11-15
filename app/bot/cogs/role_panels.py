"""Ког панелей ролей: постоянные кнопки и управление панелями."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.checks import admin_only, hierarchy_error
from app.bot.services.panels import build_panel_view, publish_panel
from app.core.utils import truncate

logger = logging.getLogger(__name__)


class RolePanels(commands.Cog):
    panel = app_commands.Group(
        name="panel",
        description="Панели с кнопками выдачи ролей",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        panels = await self.runtime.repo.all_panels_with_options()
        restored = 0
        for panel, options in panels:
            if not options:
                continue
            try:
                self.bot.add_view(build_panel_view(panel, options))
                restored += 1
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось восстановить панель %s", panel.id)
        logger.info("Восстановлено панелей ролей: %s", restored)

    # ── События ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        panel = await self.runtime.repo.panel_by_message(payload.message_id)
        if panel is not None:
            await self.runtime.repo.set_panel_message(panel.id, None)
            logger.info("Сообщение панели %s удалено вручную", panel.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        panel_ids = await self.runtime.repo.remove_role_references(role.guild.id, role.id)
        self.runtime.invalidate_config(role.guild.id)
        self.runtime.invalidate_achievements(role.guild.id)
        for panel_id in panel_ids:
            await publish_panel(self.runtime, panel_id)

    # ── Команды ──────────────────────────────────────────────────────────────

    @panel.command(name="list", description="Список панелей ролей")
    @admin_only()
    async def list_panels(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        panels = await self.runtime.repo.list_panels(interaction.guild.id)
        if not panels:
            await interaction.response.send_message(
                embed=embeds.info(
                    "Панелей нет",
                    "Создайте панель в дашборде, затем опубликуйте её.",
                ),
                ephemeral=True,
            )
            return
        lines = []
        for panel in panels:
            channel = interaction.guild.get_channel(panel.channel_id)
            channel_text = channel.mention if channel else f"`{panel.channel_id}`"
            if panel.message_id and channel and isinstance(channel, discord.TextChannel):
                link = f" · [сообщение](https://discord.com/channels/{interaction.guild.id}/{channel.id}/{panel.message_id})"
            else:
                link = " · не опубликована"
            lines.append(
                f"`#{panel.id}` **{truncate(panel.title, 60)}** — {channel_text} "
                f"(`{panel.mode}`){link}"
            )
        embed = embeds.base("Панели ролей", "\n".join(lines))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @panel.command(name="add", description="Добавить роль в панель")
    @app_commands.describe(panel_id="ID панели", role="Роль", label="Текст кнопки")
    @admin_only()
    async def add_role(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        role: discord.Role,
        label: str | None = None,
    ) -> None:
        assert interaction.guild is not None
        panel = await self.runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Панель не найдена", "Проверьте ID панели."), ephemeral=True
            )
            return
        problem = hierarchy_error(interaction.guild, role)
        if problem:
            await interaction.response.send_message(
                embed=embeds.error("Нельзя добавить роль", problem), ephemeral=True
            )
            return
        options = await self.runtime.repo.list_panel_options(panel_id)
        if len(options) >= 25:
            await interaction.response.send_message(
                embed=embeds.error("Лимит", "В одной панели может быть не больше 25 ролей."),
                ephemeral=True,
            )
            return
        created = await self.runtime.repo.add_panel_option(
            panel_id, role.id, label=(label or role.name)[:80]
        )
        if created is None:
            await interaction.response.send_message(
                embed=embeds.warning("Уже есть", "Эта роль уже добавлена в панель."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await publish_panel(self.runtime, panel_id)
        embed = (
            embeds.success("Роль добавлена", message)
            if ok
            else embeds.warning("Роль добавлена, но панель не обновлена", message)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @panel.command(name="remove", description="Убрать роль из панели")
    @app_commands.describe(panel_id="ID панели", role="Роль")
    @admin_only()
    async def remove_role(
        self, interaction: discord.Interaction, panel_id: int, role: discord.Role
    ) -> None:
        assert interaction.guild is not None
        panel = await self.runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Панель не найдена"), ephemeral=True
            )
            return
        removed = await self.runtime.repo.delete_panel_option(panel_id, role.id)
        if not removed:
            await interaction.response.send_message(
                embed=embeds.warning("Не найдено", "Этой роли нет в панели."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await publish_panel(self.runtime, panel_id)
        embed = (
            embeds.success("Роль убрана", message)
            if ok
            else embeds.warning("Роль убрана, но панель не обновлена", message)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @panel.command(name="post", description="Опубликовать или обновить панель")
    @app_commands.describe(panel_id="ID панели")
    @admin_only()
    async def post_panel(self, interaction: discord.Interaction, panel_id: int) -> None:
        assert interaction.guild is not None
        panel = await self.runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Панель не найдена"), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await publish_panel(self.runtime, panel_id)
        embed = embeds.success("Готово", message) if ok else embeds.error("Ошибка", message)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @panel.command(name="delete", description="Удалить панель")
    @app_commands.describe(panel_id="ID панели")
    @admin_only()
    async def delete_panel(self, interaction: discord.Interaction, panel_id: int) -> None:
        assert interaction.guild is not None
        panel = await self.runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Панель не найдена"), ephemeral=True
            )
            return
        if panel.message_id:
            channel = interaction.guild.get_channel(panel.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(panel.message_id)
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        await self.runtime.repo.delete_panel(panel_id)
        await interaction.response.send_message(
            embed=embeds.success("Панель удалена", "Сообщение с кнопками тоже удалено."),
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolePanels(bot))
