"""Тесты оформления эмбедов."""

from __future__ import annotations

import unittest

import discord

from app.bot.embeds import apply_user_avatar, base


class _Avatar:
    url = "https://cdn.discordapp.com/avatars/1/avatar.png?size=128"


class _User:
    display_avatar = _Avatar()


class EmbedTests(unittest.TestCase):
    def test_avatar_is_set(self) -> None:
        embed = base("Тест")
        apply_user_avatar(embed, _User())  # type: ignore[arg-type]
        self.assertEqual(embed.thumbnail.url, _Avatar.url)

    def test_object_without_avatar_is_ignored(self) -> None:
        embed = base("Тест")
        apply_user_avatar(embed, discord.Object(id=123))  # type: ignore[arg-type]
        self.assertIsNone(embed.thumbnail.url)

    def test_none_is_ignored(self) -> None:
        embed = base("Тест")
        apply_user_avatar(embed, None)
        self.assertIsNone(embed.thumbnail.url)


if __name__ == "__main__":
    unittest.main()
