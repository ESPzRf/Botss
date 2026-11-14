"""Discord OAuth2 для входа в дашборд."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.settings import Settings

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
ME_URL = "https://discord.com/api/users/@me"
GUILDS_URL = "https://discord.com/api/users/@me/guilds"


class OAuthError(RuntimeError):
    pass


def avatar_url(user_id: int, avatar_hash: str | None) -> str:
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


def guild_icon_url(guild_id: int, icon_hash: str | None) -> str | None:
    if not icon_hash:
        return None
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png?size=96"


class DiscordOAuth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.dashboard_configured

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.oauth_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params, quote_via=quote)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        data = {
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oauth_redirect_uri,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Discord отклонил OAuth-код: %s", exc.response.text[:300])
            raise OAuthError("Discord отклонил вход. Попробуйте ещё раз.") from exc
        except httpx.HTTPError as exc:
            logger.warning("OAuth-запрос не удался: %s", exc)
            raise OAuthError("Не удалось связаться с Discord.") from exc

    async def fetch_user(self, access_token: str) -> dict[str, Any]:
        return await self._get(ME_URL, access_token)

    async def fetch_guilds(self, access_token: str) -> list[dict[str, Any]]:
        data = await self._get(GUILDS_URL, access_token)
        return data if isinstance(data, list) else []

    async def _get(self, url: str, access_token: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Discord API %s: %s", url, exc.response.status_code)
            raise OAuthError("Discord не отдал данные профиля.") from exc
        except httpx.HTTPError as exc:
            logger.warning("Запрос к Discord API не удался: %s", exc)
            raise OAuthError("Не удалось связаться с Discord.") from exc


def managed_guilds(guilds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет серверы, где пользователь владелец или имеет Manage Guild/Admin."""
    result: list[dict[str, Any]] = []
    for guild in guilds:
        try:
            permissions = int(guild.get("permissions", 0))
        except (TypeError, ValueError):
            permissions = 0
        is_owner = bool(guild.get("owner"))
        if not is_owner and not permissions & 0x28:
            continue
        result.append(
            {
                "id": str(guild["id"]),
                "name": guild.get("name") or "Сервер",
                "icon": guild.get("icon"),
                "owner": is_owner,
                "permissions": permissions,
            }
        )
    result.sort(key=lambda item: item["name"].casefold())
    return result
