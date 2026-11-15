"""Запуск бота и дашборда в одном процессе."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from urllib.parse import urlparse

import uvicorn

from app.bot.client import ModerationBot
from app.bot.runtime import Runtime
from app.dashboard.server import create_app
from app.settings import Settings

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guardian — Discord-бот модерации с дашбордом")
    parser.add_argument("--dashboard-only", action="store_true", help="запустить только веб-дашборд")
    parser.add_argument("--bot-only", action="store_true", help="запустить только Discord-бота")
    parser.add_argument("--host", help="адрес дашборда (переопределяет DASHBOARD_HOST)")
    parser.add_argument("--port", type=int, help="порт дашборда (переопределяет DASHBOARD_PORT)")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR")
    return parser


async def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    setup_logging(args.log_level or settings.log_level)
    settings = replace(
        settings,
        host=args.host or settings.host,
        port=args.port or settings.port,
    )

    if args.dashboard_only and args.bot_only:
        logger.error("Нельзя одновременно указать --dashboard-only и --bot-only")
        return 2
    if not args.dashboard_only and not settings.token:
        logger.error(
            "Не задан DISCORD_TOKEN. Скопируйте .env.example в .env и заполните токен, "
            "либо запустите дашборд командой: python run.py --dashboard-only"
        )
        return 2
    if not settings.dashboard_configured and not args.bot_only:
        logger.warning(
            "DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET не заданы — вход в дашборд не будет работать."
        )

    oauth_host = (urlparse(settings.dashboard_url).hostname or "").lower()
    if (
        settings.dashboard_url.startswith("http://")
        and oauth_host not in {"localhost", "127.0.0.1", "::1"}
    ):
        logger.warning(
            "DASHBOARD_URL использует HTTP для внешнего адреса (%s). "
            "Discord OAuth принимает только HTTPS (кроме localhost).",
            settings.dashboard_url,
        )
    logger.info("OAuth redirect URI: %s", settings.oauth_redirect_uri)

    runtime = Runtime(settings)
    await runtime.db.connect()
    await runtime.repo.purge_expired_sessions()
    logger.info("База данных: %s", settings.db_path)

    app = create_app(runtime)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            log_level="info",
            log_config=None,
            access_log=args.log_level not in {"WARNING", "ERROR"},
        )
    )

    tasks: list[asyncio.Task] = []
    bot: ModerationBot | None = None

    if not args.dashboard_only:
        bot = ModerationBot(runtime)
        runtime.bot = bot
        tasks.append(asyncio.create_task(bot.start(settings.token), name="discord-bot"))

    if not args.bot_only:
        tasks.append(asyncio.create_task(server.serve(), name="dashboard"))

    logger.info(
        "Запуск: %s",
        "дашборд на %s:%s" % (settings.host, settings.port)
        if not args.bot_only
        else "только бот (без дашборда)",
    )

    exit_code = 0
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Критическая ошибка запуска")
        exit_code = 1
    finally:
        server.should_exit = True
        try:
            await runtime.shutdown_tasks()
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось корректно завершить фоновые задачи")
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if bot is not None and not bot.is_closed():
            try:
                await bot.close()
            except Exception:  # noqa: BLE001
                logger.debug("Ошибка при закрытии бота", exc_info=True)
        await runtime.db.close()
        logger.info("Остановлено")
    return exit_code


def main() -> None:
    args = build_parser().parse_args()
    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        code = 0
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Не удалось запустить приложение")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
