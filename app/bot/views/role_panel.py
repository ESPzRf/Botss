"""Постоянная view с кнопками выдачи ролей."""

from __future__ import annotations

import logging

import discord

from app.bot import embeds
from app.core.models import PanelOption, RolePanel

logger = logging.getLogger(__name__)


def _parse_emoji(raw: str | None) -> discord.PartialEmoji | str | None:
    if not raw:
        return None
    if ":" in raw:
        try:
            return discord.PartialEmoji.from_str(raw)
        except (ValueError, TypeError):
            return None
    return raw


def _button_style(value: int) -> discord.ButtonStyle:
    if value in (1, 2, 3, 4):
        return discord.ButtonStyle(value)
    return discord.ButtonStyle.secondary


class RolePanelView(discord.ui.View):
    def __init__(self, panel: RolePanel, options: list[PanelOption]) -> None:
        super().__init__(timeout=None)
        self.panel = panel
        self.option_role_ids = [option.role_id for option in options]
        for option in options[:25]:
            try:
                button = discord.ui.Button(
                    label=(option.label or "Роль")[:80],
                    custom_id=f"rp:{panel.id}:{option.role_id}",
                    style=_button_style(option.style),
                    emoji=_parse_emoji(option.emoji),
                )
            except (ValueError, TypeError):
                button = discord.ui.Button(
                    label=(option.label or "Роль")[:80],
                    custom_id=f"rp:{panel.id}:{option.role_id}",
                    style=_button_style(option.style),
                )
            button.callback = self._callback(option.role_id)
            self.add_item(button)

    def _callback(self, role_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            await handle_role_button(interaction, self.panel, role_id, self.option_role_ids)

        return callback


async def handle_role_button(
    interaction: discord.Interaction,
    panel: RolePanel,
    role_id: int,
    option_role_ids: list[int],
) -> None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message(
            embed=embeds.error("Ошибка", "Кнопка работает только на сервере."), ephemeral=True
        )
        return

    role = guild.get_role(role_id)
    me = guild.me
    if role is None:
        await interaction.response.send_message(
            embed=embeds.error("Роль не найдена", "Возможно, роль была удалена."), ephemeral=True
        )
        return
    if me is None or not me.guild_permissions.manage_roles:
        await interaction.response.send_message(
            embed=embeds.error("Нет прав", "Боту нужно право **Управлять ролями**."), ephemeral=True
        )
        return
    if role.is_default() or role.managed or role >= me.top_role:
        await interaction.response.send_message(
            embed=embeds.error(
                "Роль недоступна",
                "Бот не может выдавать эту роль: она выше его роли или управляется интеграцией.",
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    has_role = role in member.roles

    try:
        if panel.mode == "unique" and not has_role:
            for other_id in option_role_ids:
                if other_id == role_id:
                    continue
                other = guild.get_role(other_id)
                if other is not None and other in member.roles:
                    await member.remove_roles(other, reason=f"Панель ролей #{panel.id}: выбор другой роли")
            await member.add_roles(role, reason=f"Панель ролей #{panel.id}")
            text = f"Вы получили роль {role.mention}."
        elif has_role:
            await member.remove_roles(role, reason=f"Панель ролей #{panel.id}")
            text = f"Роль {role.mention} снята."
        else:
            await member.add_roles(role, reason=f"Панель ролей #{panel.id}")
            text = f"Вы получили роль {role.mention}."
    except discord.Forbidden:
        await interaction.followup.send(
            embed=embeds.error("Не удалось", "У бота недостаточно прав для этой роли."),
            ephemeral=True,
        )
        return
    except discord.HTTPException:
        logger.exception("Ошибка выдачи роли через панель %s", panel.id)
        await interaction.followup.send(
            embed=embeds.error("Ошибка Discord", "Попробуйте ещё раз через минуту."), ephemeral=True
        )
        return

    await interaction.followup.send(embed=embeds.success("Готово", text), ephemeral=True)
