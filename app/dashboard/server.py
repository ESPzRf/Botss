"""FastAPI-дашборд: OAuth, страницы настроек и действия, требующие бота."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import discord
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.bot import embeds
from app.bot.runtime import Runtime
from app.bot.services.panels import publish_panel
from app.bot.services.moderation import reconcile_guild
from app.core.defaults import CONDITION_LABELS
from app.core.durations import DurationError, format_duration, parse_duration
from app.core.events import ALL_EVENT_KEYS, EVENT_GROUPS
from app.core.levels import format_number
from app.core.models import GuildConfig, WebSession
from app.core.utils import parse_iso
from app.dashboard.auth import DiscordOAuth, OAuthError, avatar_url, guild_icon_url, managed_guilds
from app.dashboard.forms import (
    FormError,
    as_bool,
    as_id_list,
    as_int,
    check_csrf,
    one,
    parse_id_text,
    read_form,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

SESSION_COOKIE = "guardian_session"
STATE_COOKIE = "guardian_oauth_state"

BOT_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    manage_messages=True,
    manage_roles=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    view_audit_log=True,
)


@dataclass(slots=True)
class GuildPage:
    session: WebSession
    guild: discord.Guild
    config: GuildConfig


def bot_invite_url(client_id: str) -> str | None:
    if not client_id:
        return None
    params = urlencode(
        {
            "client_id": client_id,
            "permissions": BOT_PERMISSIONS.value,
            "scope": "bot applications.commands",
        },
        quote_via=quote,
    )
    return f"https://discord.com/oauth2/authorize?{params}"


def text_channels(guild: discord.Guild) -> list[discord.TextChannel]:
    return sorted(guild.text_channels, key=lambda channel: channel.position)


def all_channels(guild: discord.Guild) -> list[discord.abc.GuildChannel]:
    channels = [
        channel
        for channel in guild.channels
        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel))
    ]
    return sorted(channels, key=lambda channel: channel.position)


def assignable_roles(guild: discord.Guild) -> list[discord.Role]:
    me = guild.me
    if me is None:
        return []
    roles = [
        role
        for role in guild.roles
        if not role.is_default() and not role.managed and role < me.top_role
    ]
    return sorted(roles, key=lambda role: role.position, reverse=True)


def all_roles(guild: discord.Guild) -> list[discord.Role]:
    return sorted(
        [role for role in guild.roles if not role.is_default()],
        key=lambda role: role.position,
        reverse=True,
    )


def format_datetime(value: Any) -> str:
    parsed = parse_iso(value) if isinstance(value, str) else value
    if parsed is None:
        return "—"
    return parsed.strftime("%d.%m.%Y %H:%M")


def duration_input(seconds: Any) -> str:
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    parts: list[str] = []
    for suffix, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if total >= size:
            amount, total = divmod(total, size)
            parts.append(f"{amount}{suffix}")
    return "".join(parts)


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="Guardian Dashboard", docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    oauth = DiscordOAuth(runtime.settings)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["dt"] = format_datetime
    templates.env.filters["num"] = format_number
    templates.env.filters["duration"] = lambda value: format_duration(value)
    templates.env.globals["avatar_url"] = avatar_url
    templates.env.globals["guild_icon"] = guild_icon_url
    templates.env.globals["condition_labels"] = CONDITION_LABELS
    templates.env.globals["all_event_keys"] = ALL_EVENT_KEYS
    templates.env.globals["duration_input"] = duration_input

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Сессия и рендеринг ───────────────────────────────────────────────────

    @app.middleware("http")
    async def load_session(request: Request, call_next):
        request.state.session = None
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            try:
                request.state.session = await runtime.repo.get_session(token)
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось прочитать веб-сессию")
        return await call_next(request)

    def session_of(request: Request) -> WebSession:
        session = getattr(request.state, "session", None)
        if session is None:
            raise HTTPException(status_code=401, detail="Требуется вход через Discord.")
        return session

    async def require_guild(request: Request, guild_id: int) -> GuildPage:
        session = session_of(request)
        if not session.can_manage(guild_id):
            raise HTTPException(status_code=403, detail="Нет прав на управление этим сервером.")
        if runtime.bot is None or not runtime.bot.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Бот ещё подключается к Discord. Обновите страницу через минуту.",
            )
        guild = runtime.bot.get_guild(guild_id)
        if guild is None:
            raise HTTPException(
                status_code=404,
                detail="Бот не находится на этом сервере. Пригласите его и обновите страницу.",
            )
        config = await runtime.repo.ensure_guild(
            guild.id, guild.name, guild.icon.url if guild.icon else None
        )
        return GuildPage(session=session, guild=guild, config=config)

    def render(request: Request, template: str, *, status_code: int = 200, **context: Any):
        settings = runtime.settings
        request_host = (request.url.hostname or "").lower()
        oauth_host = (urlparse(settings.dashboard_url).hostname or "").lower()
        loopback = {"localhost", "127.0.0.1", "::1"}
        host_mismatch = bool(
            request_host
            and oauth_host
            and request_host != oauth_host
            and not (request_host in loopback and oauth_host in loopback)
        )
        context.setdefault("request", request)
        context.setdefault("session", getattr(request.state, "session", None))
        context.setdefault("settings", settings)
        context.setdefault("bot_ready", runtime.bot_ready)
        context.setdefault("ok", request.query_params.get("ok"))
        context.setdefault("err", request.query_params.get("err"))
        context.setdefault("invite_url", bot_invite_url(settings.client_id))
        context.setdefault("oauth_redirect_uri", settings.oauth_redirect_uri)
        context.setdefault("request_host", request_host)
        context.setdefault("oauth_host", oauth_host)
        context.setdefault("oauth_host_mismatch", host_mismatch)
        context.setdefault(
            "oauth_uses_http",
            settings.dashboard_url.startswith("http://") and oauth_host not in loopback,
        )
        return templates.TemplateResponse(request, template, context, status_code=status_code)

    def redirect(path: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
        params = {}
        if ok:
            params["ok"] = ok
        if err:
            params["err"] = err
        if params:
            path = f"{path}?{urlencode(params)}"
        return RedirectResponse(path, status_code=303)

    def guild_context(page: GuildPage, active: str) -> dict[str, Any]:
        guild = page.guild
        return {
            "guild": guild,
            "cfg": page.config,
            "session": page.session,
            "active": active,
            "channels": text_channels(guild),
            "all_channels": all_channels(guild),
            "roles": assignable_roles(guild),
            "all_roles": all_roles(guild),
            "event_groups": EVENT_GROUPS,
            "invite_url": bot_invite_url(runtime.settings.client_id),
            "panel_limit": 25,
        }

    def resolve_channel(
        guild: discord.Guild, raw: str, *, label: str = "Канал"
    ) -> discord.abc.GuildChannel | None:
        if not raw:
            return None
        try:
            channel_id = int(raw)
        except ValueError as exc:
            raise FormError(f"«{label}»: неверный ID.") from exc
        channel = guild.get_channel(channel_id)
        if channel is None:
            raise FormError(f"«{label}»: канал не найден на сервере.")
        return channel

    def resolve_role(
        guild: discord.Guild, raw: str, *, label: str = "Роль", assignable: bool = True
    ) -> discord.Role | None:
        if not raw:
            return None
        try:
            role_id = int(raw)
        except ValueError as exc:
            raise FormError(f"«{label}»: неверный ID.") from exc
        role = guild.get_role(role_id)
        if role is None:
            raise FormError(f"«{label}»: роль не найдена.")
        if assignable and role not in assignable_roles(guild):
            raise FormError(
                f"«{label}»: роль должна быть ниже роли бота и не управляться интеграцией."
            )
        return role

    def resolve_text_channel(
        guild: discord.Guild, raw: str, *, label: str = "Канал"
    ) -> discord.TextChannel | None:
        channel = resolve_channel(guild, raw, label=label)
        if channel is not None and not isinstance(channel, discord.TextChannel):
            raise FormError(f"«{label}»: нужен текстовый канал.")
        return channel

    def parse_escalations(form: dict[str, list[str]]) -> list[dict[str, Any]]:
        counts = form.get("esc_count", [])
        actions = form.get("esc_action", [])
        durations = form.get("esc_duration", [])
        rules: dict[int, dict[str, Any]] = {}
        for count_raw, action, duration_raw in zip_longest(
            counts, actions, durations, fillvalue=""
        ):
            count_raw = count_raw.strip()
            action = action.strip()
            duration_raw = duration_raw.strip()
            if not count_raw:
                continue
            try:
                count = int(count_raw)
            except ValueError as exc:
                raise FormError("Порог предупреждений должен быть числом.") from exc
            if not 1 <= count <= 100:
                raise FormError("Порог предупреждений должен быть от 1 до 100.")
            action = action.lower()
            if action not in {"timeout", "mute", "kick", "ban"}:
                raise FormError("Неизвестное действие автонаказания.")
            seconds = 0
            if action in {"timeout", "mute"}:
                if not duration_raw:
                    raise FormError("Для тайм-аута и мута укажите длительность, например 1h.")
                try:
                    parsed = parse_duration(duration_raw)
                except DurationError as exc:
                    raise FormError(str(exc)) from exc
                if parsed is None:
                    raise FormError("Тайм-аут и мут не могут быть бессрочными.")
                seconds = parsed
            elif action == "ban" and duration_raw:
                try:
                    parsed = parse_duration(duration_raw)
                except DurationError as exc:
                    raise FormError(str(exc)) from exc
                seconds = parsed or 0
            rules[count] = {"count": count, "action": action, "seconds": seconds}
        return [rules[key] for key in sorted(rules)]

    def parse_level_roles(
        guild: discord.Guild, form: dict[str, list[str]]
    ) -> list[dict[str, int]]:
        levels = form.get("lr_level", [])
        role_values = form.get("lr_role", [])
        result: dict[tuple[int, int], dict[str, int]] = {}
        for level_raw, role_raw in zip_longest(levels, role_values, fillvalue=""):
            level_raw = level_raw.strip()
            role_raw = role_raw.strip()
            if not level_raw and not role_raw:
                continue
            try:
                level = int(level_raw)
            except ValueError as exc:
                raise FormError("Уровень награды должен быть числом.") from exc
            if not 1 <= level <= 500:
                raise FormError("Уровень награды должен быть от 1 до 500.")
            role = resolve_role(guild, role_raw, label="Роль за уровень")
            if role is None:
                raise FormError("Выберите роль для каждой строки награды.")
            result[(level, role.id)] = {"level": level, "role_id": role.id}
        return [result[key] for key in sorted(result)]

    def parse_ignore_users(form: dict[str, list[str]]) -> list[int]:
        return sorted(set(parse_id_text(one(form, "ignore_users"))))

    # ── Аутентификация ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        session: WebSession | None = getattr(request.state, "session", None)
        if session is None:
            return render(request, "login.html", oauth_configured=oauth.configured)
        guilds = []
        for item in session.guilds:
            try:
                guild_id = int(item.get("id", 0))
            except (TypeError, ValueError):
                continue
            bot_guild = runtime.bot.get_guild(guild_id) if runtime.bot_ready and runtime.bot else None
            guilds.append(
                {
                    "id": guild_id,
                    "name": item.get("name") or "Сервер",
                    "icon": item.get("icon"),
                    "owner": bool(item.get("owner")),
                    "bot_present": bot_guild is not None,
                    "member_count": bot_guild.member_count if bot_guild else None,
                }
            )
        return render(request, "guilds.html", guilds=guilds)

    @app.get("/login")
    async def login(request: Request):
        if not oauth.configured:
            return render(
                request,
                "login.html",
                oauth_configured=False,
                err="Укажите DISCORD_CLIENT_ID и DISCORD_CLIENT_SECRET в .env.",
            )
        state = secrets.token_urlsafe(24)
        response = RedirectResponse(oauth.authorize_url(state), status_code=302)
        response.set_cookie(
            STATE_COOKIE,
            state,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=runtime.settings.secure_cookies,
        )
        return response

    @app.get("/auth/callback")
    async def auth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ):
        if error:
            return render(request, "login.html", oauth_configured=oauth.configured, err="Вход отменён.")
        expected = request.cookies.get(STATE_COOKIE)
        if not code or not state or not expected or state != expected:
            return render(
                request,
                "login.html",
                oauth_configured=oauth.configured,
                err="Сессия входа истекла. Попробуйте снова.",
            )
        try:
            token_data = await oauth.exchange_code(code)
            access_token = token_data.get("access_token")
            if not access_token:
                raise OAuthError("Discord не выдал токен доступа.")
            user = await oauth.fetch_user(access_token)
            guilds = managed_guilds(await oauth.fetch_guilds(access_token))
            session = await runtime.repo.create_session(
                user_id=int(user["id"]),
                username=user.get("global_name") or user.get("username") or "пользователь",
                avatar=user.get("avatar"),
                guilds=guilds,
                access_token=access_token,
                refresh_token=token_data.get("refresh_token"),
                ttl_days=runtime.settings.session_ttl_days,
            )
        except OAuthError as exc:
            return render(request, "login.html", oauth_configured=oauth.configured, err=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка OAuth-колбэка")
            return render(
                request,
                "login.html",
                oauth_configured=oauth.configured,
                err="Не удалось завершить вход. Попробуйте ещё раз.",
            )

        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session.token,
            max_age=runtime.settings.session_ttl_days * 86400,
            httponly=True,
            samesite="lax",
            secure=runtime.settings.secure_cookies,
        )
        response.delete_cookie(STATE_COOKIE)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        session = session_of(request)
        form = await read_form(request)
        check_csrf(session, form)
        await runtime.repo.delete_session(session.token)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    # ── Обзор ────────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}", response_class=HTMLResponse)
    async def overview(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        try:
            await reconcile_guild(runtime, page.guild, check_bans=False)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось сверить наказания для обзора")
        counters = await runtime.repo.guild_counters(guild_id)
        cases = await runtime.repo.list_cases(guild_id, limit=6)
        warnings = await runtime.repo.list_warnings(guild_id, active_only=True, limit=6)
        top = await runtime.repo.leaderboard(guild_id, limit=5)
        context = guild_context(page, "overview")
        context.update(
            {
                "counters": counters,
                "cases": cases,
                "warnings": warnings,
                "top": top,
                "member_count": page.guild.member_count or len(page.guild.members),
                "latency": round(runtime.bot.latency * 1000) if runtime.bot else 0,
                "uptime": format_duration(runtime.uptime_seconds),
                "page_title": "Обзор",
            }
        )
        return render(request, "overview.html", **context)

    # ── Логи ─────────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/logs", response_class=HTMLResponse)
    async def logs_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        context = guild_context(page, "logs")
        context.update({"page_title": "Логи", "channels": text_channels(page.guild)})
        return render(request, "logs.html", **context)

    @app.post("/g/{guild_id}/logs")
    async def save_logs(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            log_channel = resolve_text_channel(
                page.guild, one(form, "log_channel_id"), label="Канал логов"
            )
            mod_channel = resolve_text_channel(
                page.guild, one(form, "mod_log_channel_id"), label="Канал модерации"
            )
            events = {key: one(form, key) == "1" for key in ALL_EVENT_KEYS}
            ignore_channels = [
                channel_id
                for channel_id in as_id_list(form, "ignore_channels")
                if page.guild.get_channel(channel_id) is not None
            ]
            await runtime.repo.update_settings(
                guild_id,
                log_channel_id=log_channel.id if log_channel else None,
                mod_log_channel_id=mod_channel.id if mod_channel else None,
                events=events,
                ignore_channels=ignore_channels,
                ignore_users=parse_ignore_users(form),
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/logs", err=str(exc))
        runtime.invalidate_config(guild_id)
        return redirect(f"/g/{guild_id}/logs", ok="Настройки логов сохранены.")

    @app.post("/g/{guild_id}/test-log")
    async def test_log(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        channel_id = page.config.log_channel_id
        if not channel_id:
            return redirect(f"/g/{guild_id}/logs", err="Сначала выберите канал логов.")
        channel = page.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return redirect(f"/g/{guild_id}/logs", err="Канал логов не найден.")
        try:
            await channel.send(
                embed=embeds.base(
                    "Тестовое сообщение",
                    "Логи настроены правильно. Это сообщение отправлено из дашборда.",
                    color=0x3BA55D,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            return redirect(f"/g/{guild_id}/logs", err="Не удалось отправить сообщение в канал.")
        return redirect(f"/g/{guild_id}/logs", ok="Тестовый лог отправлен.")

    # ── Автороли ─────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/autoroles", response_class=HTMLResponse)
    async def autoroles_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        context = guild_context(page, "autoroles")
        context["page_title"] = "Автороли"
        return render(request, "autoroles.html", **context)

    @app.post("/g/{guild_id}/autoroles")
    async def save_autoroles(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            role_ids: list[int] = []
            for role_id in as_id_list(form, "autorole_ids"):
                role = resolve_role(page.guild, str(role_id), label="Автороль")
                if role and role.id not in role_ids:
                    role_ids.append(role.id)
            await runtime.repo.update_settings(
                guild_id,
                autorole_ids=role_ids,
                autorole_bots=as_bool(form, "autorole_bots"),
                restore_roles=as_bool(form, "restore_roles"),
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/autoroles", err=str(exc))
        runtime.invalidate_config(guild_id)
        return redirect(f"/g/{guild_id}/autoroles", ok="Автороли сохранены.")

    # ── Модерация ────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/moderation", response_class=HTMLResponse)
    async def moderation_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        try:
            await reconcile_guild(runtime, page.guild, check_bans=False)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось сверить наказания для дашборда")
        context = guild_context(page, "moderation")
        context.update(
            {
                "page_title": "Модерация",
                "active_cases": await runtime.repo.list_cases(guild_id, active=True, limit=15),
                "recent_warnings": await runtime.repo.list_warnings(
                    guild_id, active_only=True, limit=15
                ),
            }
        )
        return render(request, "moderation.html", **context)

    @app.post("/g/{guild_id}/moderation")
    async def save_moderation(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            mute_role = resolve_role(
                page.guild, one(form, "mute_role_id"), label="Роль мута"
            )
            escalations = parse_escalations(form)
            await runtime.repo.update_settings(
                guild_id,
                mute_role_id=mute_role.id if mute_role else None,
                escalations=escalations,
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/moderation", err=str(exc))
        runtime.invalidate_config(guild_id)
        return redirect(f"/g/{guild_id}/moderation", ok="Правила модерации сохранены.")

    # ── Опыт ─────────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/xp", response_class=HTMLResponse)
    async def xp_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        context = guild_context(page, "xp")
        context.update(
            {
                "page_title": "Опыт",
                "leaderboard": await runtime.repo.leaderboard(guild_id, limit=15),
                "level_roles": page.config.level_roles,
            }
        )
        return render(request, "xp.html", **context)

    @app.post("/g/{guild_id}/xp")
    async def save_xp(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            xp_min = as_int(form, "xp_min", default=15, minimum=0, maximum=1000, label="Мин. опыт")
            xp_max = as_int(form, "xp_max", default=25, minimum=0, maximum=1000, label="Макс. опыт")
            if xp_min is not None and xp_max is not None and xp_min > xp_max:
                raise FormError("Минимальный опыт не может быть больше максимального.")
            level_channel = resolve_text_channel(
                page.guild, one(form, "level_up_channel_id"), label="Канал уровней"
            )
            ignore_channels = [
                channel_id
                for channel_id in as_id_list(form, "xp_ignore_channels")
                if page.guild.get_channel(channel_id) is not None
            ]
            ignore_roles = []
            for role_id in as_id_list(form, "xp_ignore_roles"):
                role = page.guild.get_role(role_id)
                if role is not None:
                    ignore_roles.append(role.id)
            await runtime.repo.update_settings(
                guild_id,
                xp_enabled=as_bool(form, "xp_enabled"),
                xp_min=xp_min or 0,
                xp_max=xp_max or 0,
                xp_cooldown=as_int(
                    form, "xp_cooldown", default=60, minimum=0, maximum=86400, label="Кулдаун"
                )
                or 0,
                xp_voice_per_min=as_int(
                    form, "xp_voice_per_min", default=5, minimum=0, maximum=1000, label="Опыт за голос"
                )
                or 0,
                loyalty_enabled=as_bool(form, "loyalty_enabled"),
                loyalty_per_message=as_int(
                    form, "loyalty_per_message", default=1, minimum=0, maximum=1000, label="Баллы за сообщение"
                )
                or 0,
                loyalty_per_voice_min=as_int(
                    form, "loyalty_per_voice_min", default=2, minimum=0, maximum=1000, label="Баллы за голос"
                )
                or 0,
                level_up_channel_id=level_channel.id if level_channel else None,
                level_up_message=one(form, "level_up_message")[:500]
                or "🎉 {user}, новый уровень — **{level}**!",
                xp_ignore_channels=ignore_channels,
                xp_ignore_roles=ignore_roles,
                level_roles=parse_level_roles(page.guild, form),
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/xp", err=str(exc))
        runtime.invalidate_config(guild_id)
        return redirect(f"/g/{guild_id}/xp", ok="Настройки опыта сохранены.")

    # ── Панели ролей ─────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/panels", response_class=HTMLResponse)
    async def panels_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        panels = []
        for panel in await runtime.repo.list_panels(guild_id):
            panels.append(
                {
                    "panel": panel,
                    "options": await runtime.repo.list_panel_options(panel.id),
                    "channel": page.guild.get_channel(panel.channel_id),
                }
            )
        context = guild_context(page, "panels")
        context.update({"page_title": "Панели ролей", "panels": panels})
        return render(request, "panels.html", **context)

    @app.post("/g/{guild_id}/panels")
    async def create_panel(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            channel = resolve_channel(page.guild, one(form, "channel_id"), label="Канал панели")
            if not isinstance(channel, discord.TextChannel):
                raise FormError("Панель можно опубликовать только в текстовом канале.")
            title = one(form, "title")[:100] or "Роли"
            description = one(form, "description")[:1000]
            mode = one(form, "mode") or "toggle"
            if mode not in {"toggle", "unique"}:
                raise FormError("Неверный режим панели.")
            role_ids = list(dict.fromkeys(as_id_list(form, "role_ids")))
            if not role_ids:
                raise FormError("Выберите хотя бы одну роль для панели.")
            if len(role_ids) > 25:
                raise FormError("В одной панели может быть не больше 25 ролей.")
            options = []
            for position, role_id in enumerate(role_ids):
                role = resolve_role(page.guild, str(role_id), label="Роль панели")
                if role is None:
                    continue
                options.append((role.id, role.name[:80], None, 2))
            if not options:
                raise FormError("Не удалось подготовить роли панели.")
            panel = await runtime.repo.create_panel(
                guild_id,
                channel.id,
                title,
                description,
                mode,
                page.session.user_id,
                options,
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/panels", err=str(exc))

        published, message = await publish_panel(runtime, panel.id)
        if published:
            return redirect(f"/g/{guild_id}/panels", ok="Панель создана и опубликована.")
        return redirect(
            f"/g/{guild_id}/panels",
            err=f"Панель сохранена, но не опубликована: {message}",
        )

    @app.post("/g/{guild_id}/panels/{panel_id}/publish")
    async def republish_panel(request: Request, guild_id: int, panel_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        panel = await runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/panels", err="Панель не найдена.")
        published, message = await publish_panel(runtime, panel_id)
        return redirect(
            f"/g/{guild_id}/panels",
            ok=message if published else None,
            err=None if published else message,
        )

    @app.post("/g/{guild_id}/panels/{panel_id}/delete")
    async def delete_panel(request: Request, guild_id: int, panel_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        panel = await runtime.repo.get_panel(panel_id)
        if panel is None or panel.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/panels", err="Панель не найдена.")
        if panel.message_id:
            channel = page.guild.get_channel(panel.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(panel.message_id)
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        await runtime.repo.delete_panel(panel_id)
        return redirect(f"/g/{guild_id}/panels", ok="Панель удалена.")

    # ── Достижения ───────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/achievements", response_class=HTMLResponse)
    async def achievements_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        context = guild_context(page, "achievements")
        context.update(
            {
                "page_title": "Достижения",
                "achievements": await runtime.repo.list_achievements(guild_id),
            }
        )
        return render(request, "achievements.html", **context)

    @app.post("/g/{guild_id}/achievements")
    async def save_achievement_settings(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            channel = resolve_channel(
                page.guild, one(form, "achievements_channel_id"), label="Канал достижений"
            )
            if channel is not None and not isinstance(channel, discord.TextChannel):
                raise FormError("«Канал достижений»: нужен текстовый канал.")
            await runtime.repo.update_settings(
                guild_id,
                achievements_enabled=as_bool(form, "achievements_enabled"),
                achievements_channel_id=channel.id if channel else None,
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/achievements", err=str(exc))
        runtime.invalidate_config(guild_id)
        return redirect(f"/g/{guild_id}/achievements", ok="Настройки достижений сохранены.")

    @app.post("/g/{guild_id}/achievements/create")
    async def create_achievement(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            title = one(form, "title")[:80]
            if not title:
                raise FormError("Укажите название достижения.")
            condition_type = one(form, "condition_type")
            if condition_type not in CONDITION_LABELS:
                raise FormError("Неверное условие достижения.")
            threshold = as_int(
                form, "threshold", minimum=1, maximum=10_000_000, label="Порог"
            ) or 1
            reward_role = resolve_role(
                page.guild, one(form, "reward_role_id"), label="Роль за достижение"
            )
            reward_loyalty = as_int(
                form, "reward_loyalty", default=0, minimum=0, maximum=1_000_000, label="Награда баллами"
            ) or 0
            await runtime.repo.create_achievement(
                guild_id,
                title=title,
                description=one(form, "description")[:300],
                emoji=(one(form, "emoji") or "🏆")[:8],
                condition_type=condition_type,
                threshold=threshold,
                reward_role_id=reward_role.id if reward_role else None,
                reward_loyalty=reward_loyalty,
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/achievements", err=str(exc))
        runtime.invalidate_achievements(guild_id)
        return redirect(f"/g/{guild_id}/achievements", ok="Достижение создано.")

    @app.post("/g/{guild_id}/achievements/{achievement_id}/toggle")
    async def toggle_achievement(request: Request, guild_id: int, achievement_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        achievement = await runtime.repo.get_achievement(achievement_id)
        if achievement is None or achievement.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/achievements", err="Достижение не найдено.")
        await runtime.repo.set_achievement_enabled(achievement_id, not achievement.enabled)
        runtime.invalidate_achievements(guild_id)
        return redirect(f"/g/{guild_id}/achievements", ok="Статус достижения изменён.")

    @app.post("/g/{guild_id}/achievements/{achievement_id}/delete")
    async def delete_achievement(request: Request, guild_id: int, achievement_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        achievement = await runtime.repo.get_achievement(achievement_id)
        if achievement is None or achievement.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/achievements", err="Достижение не найдено.")
        await runtime.repo.delete_achievement(achievement_id)
        runtime.invalidate_achievements(guild_id)
        return redirect(f"/g/{guild_id}/achievements", ok="Достижение удалено.")

    # ── Магазин ──────────────────────────────────────────────────────────────

    @app.get("/g/{guild_id}/shop", response_class=HTMLResponse)
    async def shop_page(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        context = guild_context(page, "shop")
        items = await runtime.repo.list_shop_items(guild_id)
        context.update(
            {
                "page_title": "Магазин",
                "items": items,
                "items_by_id": {item.id: item for item in items},
                "purchases": await runtime.repo.list_purchases(guild_id, limit=10),
            }
        )
        return render(request, "shop.html", **context)

    @app.post("/g/{guild_id}/shop")
    async def create_shop_item(request: Request, guild_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        try:
            role = resolve_role(page.guild, one(form, "role_id"), label="Роль товара")
            if role is None:
                raise FormError("Выберите роль для товара.")
            name = one(form, "name")[:80] or role.name
            price = as_int(form, "price", minimum=1, maximum=1_000_000, label="Цена") or 1
            stock = as_int(
                form, "stock", default=-1, minimum=-1, maximum=1_000_000, label="Количество"
            )
            await runtime.repo.create_shop_item(
                guild_id,
                role_id=role.id,
                name=name,
                description=one(form, "description")[:300],
                price=price,
                stock=stock if stock is not None else -1,
            )
        except FormError as exc:
            return redirect(f"/g/{guild_id}/shop", err=str(exc))
        return redirect(f"/g/{guild_id}/shop", ok="Товар добавлен в магазин.")

    @app.post("/g/{guild_id}/shop/{item_id}/toggle")
    async def toggle_shop_item(request: Request, guild_id: int, item_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        item = await runtime.repo.get_shop_item(item_id)
        if item is None or item.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/shop", err="Товар не найден.")
        await runtime.repo.set_shop_item_enabled(item_id, not item.enabled)
        return redirect(f"/g/{guild_id}/shop", ok="Статус товара изменён.")

    @app.post("/g/{guild_id}/shop/{item_id}/delete")
    async def delete_shop_item(request: Request, guild_id: int, item_id: int):
        page = await require_guild(request, guild_id)
        form = await read_form(request)
        check_csrf(page.session, form)
        item = await runtime.repo.get_shop_item(item_id)
        if item is None or item.guild_id != guild_id:
            return redirect(f"/g/{guild_id}/shop", err="Товар не найден.")
        await runtime.repo.delete_shop_item(item_id)
        return redirect(f"/g/{guild_id}/shop", ok="Товар удалён.")

    # ── Служебное ────────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz():
        return JSONResponse(
            {
                "status": "ok",
                "bot_ready": runtime.bot_ready,
                "guilds": len(runtime.bot.guilds) if runtime.bot else 0,
            }
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        return render(
            request,
            "error.html",
            status=exc.status_code,
            message=exc.detail if isinstance(exc.detail, str) else "Ошибка запроса.",
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Необработанная ошибка дашборда")
        return render(
            request,
            "error.html",
            status=500,
            message="Внутренняя ошибка дашборда. Подробности в журнале.",
            status_code=500,
        )

    return app
