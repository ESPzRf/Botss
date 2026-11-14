"""Публикация и обновление панелей ролей."""

from __future__ import annotations

import logging

import discord

from app.bot import embeds
from app.bot.runtime import Runtime
from app.bot.views.role_panel import RolePanelView
from app.core.models import PanelOption, RolePanel

logger = logging.getLogger(__name__)


def build_panel_view(panel: RolePanel, options: list[PanelOption]) -> RolePanelView:
    return RolePanelView(panel, options)


def panel_embed(panel: RolePanel, options: list[PanelOption]) -> discord.Embed:
    description = panel.description or "Выберите роли кнопками ниже."
    embed = embeds.base(f"🎭 {panel.title}", description, color=embeds.COLOR_BRAND)
    if panel.mode == "unique":
        embed.add_field(
            name="Один выбор",
            value="Можно выбрать только одну роль из этой панели.",
            inline=False,
        )
    embed.set_footer(text="Guardian · нажмите кнопку, чтобы получить или снять роль")
    if not options:
        embed.add_field(name="Нет ролей", value="Панель пока не настроена.", inline=False)
    return embed


async def publish_panel(runtime: Runtime, panel_id: int) -> tuple[bool, str]:
    """Публикует панель или обновляет существующее сообщение."""
    if not runtime.bot_ready or runtime.bot is None:
        return False, "Бот не подключён к Discord."
    panel = await runtime.repo.get_panel(panel_id)
    if panel is None:
        return False, "Панель не найдена."
    guild = runtime.bot.get_guild(panel.guild_id)
    if guild is None:
        return False, "Бот не находится на этом сервере."
    channel = guild.get_channel(panel.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return False, "Канал панели не найден или не является текстовым."

    me = guild.me
    if me is None or not channel.permissions_for(me).send_messages:
        return False, "У бота нет права отправлять сообщения в этот канал."

    options = await runtime.repo.list_panel_options(panel.id)
    view = build_panel_view(panel, options)
    embed = panel_embed(panel, options)

    if panel.message_id:
        try:
            message = await channel.fetch_message(panel.message_id)
            await message.edit(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            runtime.bot.add_view(view)
            return True, "Панель обновлена."
        except discord.NotFound:
            pass
        except discord.Forbidden:
            return False, "Нет прав на редактирование сообщения панели."
        except discord.HTTPException:
            logger.exception("Не удалось обновить панель %s", panel.id)

    try:
        message = await channel.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        return False, "У бота нет права отправлять сообщения в этот канал."
    except discord.HTTPException:
        logger.exception("Не удалось отправить панель %s", panel.id)
        return False, "Discord отклонил отправку сообщения."

    await runtime.repo.set_panel_message(panel.id, message.id)
    runtime.bot.add_view(view)
    return True, "Панель опубликована."
