"""Ког событийных логов: пишет в канал всё, что включено в настройках."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.bot import embeds
from app.bot.log_dispatch import send_event_log
from app.core.utils import truncate

logger = logging.getLogger(__name__)


def _roles_text(roles: list[discord.Role], limit: int = 20) -> str:
    values = [role.mention for role in roles if not role.is_default()][:limit]
    return ", ".join(values) if values else "—"


def _channel_text(channel: discord.abc.GuildChannel | None) -> str:
    if channel is None:
        return "—"
    return f"{channel.mention} (`{channel.name}`)"


def _diff_line(label: str, before: object, after: object) -> str | None:
    if before == after:
        return None
    return f"**{label}:** `{truncate(str(before) or '—', 200)}` → `{truncate(str(after) or '—', 200)}`"


class EventLogs(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = bot.runtime  # type: ignore[attr-defined]

    # ── Участники ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return
        embed = embeds.log_embed(
            "📥 Участник зашёл",
            f"{member.mention} · `{member}`",
            color=embeds.COLOR_OK,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Аккаунт создан", value=embeds.dt(member.created_at, "R"), inline=True)
        embed.add_field(
            name="Участников на сервере",
            value=f"`{member.guild.member_count}`",
            inline=True,
        )
        await send_event_log(self.runtime, member.guild, "member_join", embed, user=member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        embed = embeds.log_embed(
            "📤 Участник вышел",
            f"{member.mention} · `{member}`",
            color=embeds.COLOR_ERROR,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        if member.joined_at:
            embed.add_field(name="Был на сервере с", value=embeds.dt(member.joined_at, "D"), inline=True)
        embed.add_field(name="Роли", value=_roles_text(member.roles), inline=False)
        await send_event_log(self.runtime, member.guild, "member_leave", embed, user=member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        lines: list[str] = []
        if before.nick != after.nick:
            lines.append(_diff_line("Никнейм", before.nick or before.name, after.nick or after.name) or "")
        added = [role for role in after.roles if role not in before.roles and not role.is_default()]
        removed = [role for role in before.roles if role not in after.roles and not role.is_default()]
        if added:
            lines.append(f"**Выданы роли:** {_roles_text(added)}")
        if removed:
            lines.append(f"**Сняты роли:** {_roles_text(removed)}")
        if before.timed_out_until != after.timed_out_until:
            value = embeds.dt(after.timed_out_until, "F") if after.timed_out_until else "снят"
            lines.append(f"**Тайм-аут:** {value}")
        if not lines:
            return
        embed = embeds.log_embed(
            "✏️ Участник изменён",
            f"{after.mention} · `{after}`",
            color=embeds.COLOR_WARN,
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        for line in lines:
            if line:
                embed.add_field(name="​", value=line, inline=False)
        await send_event_log(self.runtime, after.guild, "member_update", embed, user=after)

    # ── Сообщения ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        author = message.author
        embed = embeds.log_embed(
            "🗑️ Сообщение удалено",
            f"{author.mention} в {message.channel.mention}",
            color=embeds.COLOR_LOG,
        )
        embed.add_field(
            name="Содержимое",
            value=truncate(message.content or "*(без текста)*", 1024),
            inline=False,
        )
        embed.add_field(name="ID сообщения", value=f"`{message.id}`", inline=True)
        embed.add_field(name="Создано", value=embeds.dt(message.created_at, "R"), inline=True)
        if message.attachments:
            embed.add_field(
                name="Вложения",
                value="\n".join(f"[{a.filename}]({a.url})" for a in message.attachments[:5]),
                inline=False,
            )
        await send_event_log(
            self.runtime,
            message.guild,
            "message_delete",
            embed,
            channel=message.channel,
            user=author,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        lines = []
        for message in messages[:10]:
            lines.append(
                f"{message.author.mention}: {truncate(message.content or '*(без текста)*', 120)}"
            )
        if len(messages) > 10:
            lines.append(f"…и ещё {len(messages) - 10}")
        embed = embeds.log_embed(
            "🧹 Массовое удаление",
            f"Удалено **{len(messages)}** сообщений в {channel.mention}",
            color=embeds.COLOR_ERROR,
        )
        embed.add_field(name="Сообщения", value=truncate("\n".join(lines), 1024), inline=False)
        await send_event_log(
            self.runtime,
            guild,
            "message_bulk_delete",
            embed,
            channel=channel,
            avatar_user=messages[0].author,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.content == after.content or before.author.bot:
            return
        embed = embeds.log_embed(
            "📝 Сообщение изменено",
            f"{after.author.mention} в {after.channel.mention} · [перейти]({after.jump_url})",
            color=embeds.COLOR_WARN,
        )
        embed.add_field(name="Было", value=truncate(before.content or "—", 1024), inline=False)
        embed.add_field(name="Стало", value=truncate(after.content or "—", 1024), inline=False)
        await send_event_log(
            self.runtime,
            after.guild,
            "message_edit",
            embed,
            channel=after.channel,
            user=after.author,
        )

    # ── Голос ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            key, title, color = "voice_join", "🔊 Вход в голосовой канал", embeds.COLOR_OK
            description = f"{member.mention} подключился к {after.channel.mention}"
        elif before.channel is not None and after.channel is None:
            key, title, color = "voice_leave", "🔇 Выход из голосового канала", embeds.COLOR_ERROR
            description = f"{member.mention} отключился от {before.channel.mention}"
        else:
            key, title, color = "voice_move", "🔀 Перемещение в голосе", embeds.COLOR_BRAND
            description = f"{member.mention}: {_channel_text(before.channel)} → {_channel_text(after.channel)}"
        embed = embeds.log_embed(title, description, color=color)
        if after.channel is not None:
            embed.add_field(name="Участников в канале", value=f"`{len(after.channel.members)}`", inline=True)
        await send_event_log(
            self.runtime, member.guild, key, embed, channel=after.channel or before.channel, user=member
        )

    # ── Каналы ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        embed = embeds.log_embed(
            "📁 Канал создан",
            f"{channel.mention} · `{channel.name}`",
            color=embeds.COLOR_OK,
        )
        embed.add_field(name="Тип", value=f"`{channel.type}`", inline=True)
        if channel.category:
            embed.add_field(name="Категория", value=channel.category.name, inline=True)
        await send_event_log(self.runtime, channel.guild, "channel_create", embed, channel=channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        embed = embeds.log_embed(
            "🗂️ Канал удалён",
            f"`{channel.name}`",
            color=embeds.COLOR_ERROR,
        )
        embed.add_field(name="Тип", value=f"`{channel.type}`", inline=True)
        if channel.category:
            embed.add_field(name="Категория", value=channel.category.name, inline=True)
        await send_event_log(self.runtime, channel.guild, "channel_delete", embed, channel=channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        lines = [
            line
            for line in (
                _diff_line("Название", before.name, after.name),
                _diff_line(
                    "Тема",
                    getattr(before, "topic", None),
                    getattr(after, "topic", None),
                ),
                _diff_line(
                    "Медленный режим",
                    getattr(before, "slowmode_delay", None),
                    getattr(after, "slowmode_delay", None),
                ),
                _diff_line(
                    "NSFW",
                    getattr(before, "nsfw", None),
                    getattr(after, "nsfw", None),
                ),
                _diff_line(
                    "Категория",
                    before.category.name if before.category else None,
                    after.category.name if after.category else None,
                ),
            )
            if line
        ]
        if not lines:
            return
        embed = embeds.log_embed(
            "🛠️ Канал изменён",
            f"{after.mention} · `{after.name}`",
            color=embeds.COLOR_WARN,
        )
        for line in lines:
            embed.add_field(name="​", value=line, inline=False)
        await send_event_log(self.runtime, after.guild, "channel_update", embed, channel=after)

    # ── Роли ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = embeds.log_embed(
            "🎖️ Роль создана",
            f"{role.mention} · `{role.name}`",
            color=embeds.COLOR_OK,
        )
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Цвет", value=f"`{role.color}`", inline=True)
        await send_event_log(self.runtime, role.guild, "role_create", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = embeds.log_embed(
            "🎖️ Роль удалена",
            f"`{role.name}`",
            color=embeds.COLOR_ERROR,
        )
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        await send_event_log(self.runtime, role.guild, "role_delete", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        lines = [
            line
            for line in (
                _diff_line("Название", before.name, after.name),
                _diff_line("Цвет", before.color, after.color),
                _diff_line("Отображается отдельно", before.hoist, after.hoist),
                _diff_line("Упоминание", before.mentionable, after.mentionable),
                _diff_line("Права", before.permissions.value, after.permissions.value),
            )
            if line
        ]
        if not lines:
            return
        embed = embeds.log_embed(
            "🎖️ Роль изменена",
            f"{after.mention} · `{after.name}`",
            color=embeds.COLOR_WARN,
        )
        for line in lines[:6]:
            embed.add_field(name="​", value=line, inline=False)
        await send_event_log(self.runtime, after.guild, "role_update", embed)

    # ── Баны ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = embeds.log_embed(
            "🔨 Участник забанен",
            f"{user.mention} · `{user}`",
            color=embeds.COLOR_ERROR,
        )
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        await send_event_log(self.runtime, guild, "ban", embed, user=user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = embeds.log_embed(
            "🔓 Участник разбанен",
            f"{user.mention} · `{user}`",
            color=embeds.COLOR_OK,
        )
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        await send_event_log(self.runtime, guild, "unban", embed, user=user)

    # ── Приглашения ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is None:
            return
        embed = embeds.log_embed(
            "🔗 Приглашение создано",
            f"`{invite.code}` · {getattr(invite.channel, 'mention', '—')}",
            color=embeds.COLOR_BRAND,
        )
        if invite.inviter:
            embed.add_field(name="Создал", value=f"{invite.inviter.mention} · `{invite.inviter}`", inline=False)
        embed.add_field(name="Использований", value=f"`{invite.uses or 0}`", inline=True)
        if invite.max_uses:
            embed.add_field(name="Лимит", value=f"`{invite.max_uses}`", inline=True)
        if invite.expires_at:
            embed.add_field(name="Истекает", value=embeds.dt(invite.expires_at, "R"), inline=True)
        await send_event_log(
            self.runtime, invite.guild, "invite_create", embed, avatar_user=invite.inviter
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is None:
            return
        embed = embeds.log_embed(
            "🔗 Приглашение удалено",
            f"`{invite.code}` · {getattr(invite.channel, 'mention', '—')}",
            color=embeds.COLOR_LOG,
        )
        await send_event_log(
            self.runtime, invite.guild, "invite_delete", embed, avatar_user=invite.inviter
        )

    # ── Ветки и сервер ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        embed = embeds.log_embed(
            "🧵 Ветка создана",
            f"{thread.mention} в {thread.parent.mention if thread.parent else '—'}",
            color=embeds.COLOR_OK,
        )
        embed.add_field(name="Владелец", value=thread.owner.mention if thread.owner else "—", inline=True)
        await send_event_log(
            self.runtime,
            thread.guild,
            "thread_create",
            embed,
            channel=thread.parent,
            avatar_user=thread.owner,
        )

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        embed = embeds.log_embed(
            "🧵 Ветка удалена",
            f"`{thread.name}`",
            color=embeds.COLOR_ERROR,
        )
        await send_event_log(
            self.runtime,
            thread.guild,
            "thread_delete",
            embed,
            channel=thread.parent,
            avatar_user=thread.owner,
        )

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        lines = [
            line
            for line in (
                _diff_line("Название", before.name, after.name),
                _diff_line("Описание", before.description, after.description),
            )
            if line
        ]
        if before.icon != after.icon:
            lines.append("**Иконка:** изменена")
        if not lines:
            return
        embed = embeds.log_embed("🏛️ Сервер изменён", after.name, color=embeds.COLOR_WARN)
        for line in lines:
            embed.add_field(name="​", value=line, inline=False)
        await send_event_log(self.runtime, after, "guild_update", embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        added = [emoji for emoji in after if emoji not in before]
        removed = [emoji for emoji in before if emoji not in after]
        if not added and not removed:
            return
        embed = embeds.log_embed("😀 Эмодзи изменены", guild.name, color=embeds.COLOR_LOG)
        if added:
            embed.add_field(
                name="Добавлены",
                value=" ".join(str(emoji) for emoji in added[:20]),
                inline=False,
            )
        if removed:
            embed.add_field(name="Удалены", value=", ".join(emoji.name for emoji in removed[:20]), inline=False)
        await send_event_log(self.runtime, guild, "emoji_update", embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventLogs(bot))
