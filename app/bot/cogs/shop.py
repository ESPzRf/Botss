"""Ког магазина ролей за баллы лояльности."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.checks import admin_only, hierarchy_error
from app.core.levels import format_number

STATUS_TEXT = {
    "not_found": "Товар не найден.",
    "disabled": "Товар временно отключён.",
    "out_of_stock": "Товар закончился.",
    "no_money": "Недостаточно баллов лояльности.",
}


class Shop(commands.Cog):
    shop = app_commands.Group(name="shop", description="Магазин ролей за баллы лояльности")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    @shop.command(name="list", description="Показать товары магазина")
    async def list_items(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        config = await self.runtime.config(interaction.guild)
        if not config.shop_enabled:
            await interaction.response.send_message(
                embed=embeds.warning("Магазин выключен", "Магазин отключён в настройках сервера."),
                ephemeral=True,
            )
            return
        items = await self.runtime.repo.list_shop_items(interaction.guild.id, enabled_only=True)
        stats = await self.runtime.repo.get_stats(interaction.guild.id, interaction.user.id)
        embed = embeds.base("🛒 Магазин ролей", color=embeds.COLOR_XP)
        if not items:
            embed.description = "Пока нет товаров. Загляните позже!"
        for item in items[:24]:
            role = interaction.guild.get_role(item.role_id)
            role_text = role.mention if role else "*роль удалена*"
            stock = "∞" if item.is_unlimited else str(item.stock)
            embed.add_field(
                name=f"`#{item.id}` {item.name} · {format_number(item.price)} 💎",
                value=(
                    f"{role_text}\n"
                    f"{item.description or '—'}\n"
                    f"Осталось: **{stock}**"
                ),
                inline=True,
            )
        if len(items) > 24:
            embed.add_field(
                name="…",
                value=f"Ещё {len(items) - 24} товаров — полный список в дашборде.",
                inline=False,
            )
        embed.set_footer(text=f"Ваш баланс: {format_number(stats.loyalty)} 💎 · покупка: /shop buy <ID>")
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

    @shop.command(name="buy", description="Купить роль за баллы")
    @app_commands.describe(item_id="ID товара из /shop list")
    async def buy(self, interaction: discord.Interaction, item_id: int) -> None:
        assert interaction.guild is not None
        config = await self.runtime.config(interaction.guild)
        if not config.shop_enabled:
            await interaction.response.send_message(
                embed=embeds.warning("Магазин выключен", "Магазин отключён в настройках сервера."),
                ephemeral=True,
            )
            return

        item = await self.runtime.repo.get_shop_item(item_id)
        if item is None or item.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Товар с таким ID не найден."), ephemeral=True
            )
            return
        role = interaction.guild.get_role(item.role_id)
        if role is None:
            await interaction.response.send_message(
                embed=embeds.error("Роль недоступна", "Роль этого товара была удалена."),
                ephemeral=True,
            )
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            return
        if role in member.roles:
            await interaction.response.send_message(
                embed=embeds.warning("Уже есть", "У вас уже есть эта роль."), ephemeral=True
            )
            return
        problem = hierarchy_error(interaction.guild, role)
        if problem:
            await interaction.response.send_message(
                embed=embeds.error("Роль недоступна", problem), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        purchased, status = await self.runtime.repo.purchase_item(
            interaction.guild.id, member.id, item.id
        )
        if purchased is None:
            await interaction.followup.send(
                embed=embeds.error("Не получилось", STATUS_TEXT.get(status, "Ошибка покупки.")),
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(role, reason=f"Покупка в магазине: {item.name}")
        except (discord.Forbidden, discord.HTTPException):
            await self.runtime.repo.refund_purchase(interaction.guild.id, member.id, item.id)
            await interaction.followup.send(
                embed=embeds.error(
                    "Не удалось выдать роль",
                    "Баллы возвращены. Обратитесь к администратору.",
                ),
                ephemeral=True,
            )
            return

        stats = await self.runtime.repo.get_stats(interaction.guild.id, member.id)
        await interaction.followup.send(
            embed=embeds.success(
                "Покупка совершена",
                f"Вы получили {role.mention} за **{format_number(item.price)}** 💎.\n"
                f"Остаток: **{format_number(stats.loyalty)}** 💎.",
            ),
            ephemeral=True,
        )

    @shop.command(name="add", description="Добавить товар в магазин")
    @app_commands.describe(
        role="Роль, которую получит покупатель",
        price="Цена в баллах",
        name="Название товара",
        stock="Количество (пусто или -1 — без ограничений)",
        description="Описание товара",
    )
    @admin_only()
    async def add(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        price: app_commands.Range[int, 1, 1_000_000],
        name: str | None = None,
        stock: app_commands.Range[int, -1, 1_000_000] = -1,
        description: str | None = None,
    ) -> None:
        assert interaction.guild is not None
        problem = hierarchy_error(interaction.guild, role)
        if problem:
            await interaction.response.send_message(
                embed=embeds.error("Нельзя использовать роль", problem), ephemeral=True
            )
            return
        item = await self.runtime.repo.create_shop_item(
            interaction.guild.id,
            role_id=role.id,
            name=(name or role.name)[:80],
            description=(description or "")[:300],
            price=price,
            stock=stock,
        )
        await interaction.response.send_message(
            embed=embeds.success(
                "Товар добавлен",
                f"`#{item.id}` **{item.name}** — {format_number(item.price)} 💎.",
            ),
            ephemeral=True,
        )

    @shop.command(name="remove", description="Удалить товар из магазина")
    @app_commands.describe(item_id="ID товара")
    @admin_only()
    async def remove(self, interaction: discord.Interaction, item_id: int) -> None:
        assert interaction.guild is not None
        item = await self.runtime.repo.get_shop_item(item_id)
        if item is None or item.guild_id != interaction.guild.id:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Товар с таким ID не найден."), ephemeral=True
            )
            return
        await self.runtime.repo.delete_shop_item(item_id)
        await interaction.response.send_message(
            embed=embeds.success("Товар удалён", f"`#{item_id}` больше не продаётся."), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shop(bot))
