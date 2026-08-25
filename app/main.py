from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.health import HealthcheckError, check_database

if TYPE_CHECKING:
    from aiogram import Dispatcher

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def build_dispatcher() -> Dispatcher:
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from app.bot.handlers import admin, contact, errors, language, start, subscription
    from app.bot.middleware import UserLanguageMiddleware

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.errors.register(errors.handle_update_error)
    language_middleware = UserLanguageMiddleware()
    dispatcher.message.outer_middleware(language_middleware)
    dispatcher.callback_query.outer_middleware(language_middleware)
    dispatcher.include_router(language.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(subscription.router)
    dispatcher.include_router(contact.router)
    dispatcher.include_router(start.router)
    return dispatcher


def load_settings_or_exit() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False, include_context=False, include_input=False):
            field = ".".join(str(part) for part in error["loc"])
            details.append(f"{field}: {error['msg']}")
        logger.error("Invalid configuration:\n%s", "\n".join(details))
        raise SystemExit(2) from None


def healthcheck_or_exit(settings: Settings) -> None:
    try:
        check_database(settings.database_path)
    except HealthcheckError as exc:
        logger.error("Health check failed: %s", exc)
        raise SystemExit(1) from None
    logger.info("Health check succeeded")


async def run(*, check_only: bool = False) -> None:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from app.db.migrations import SchemaMigrationError
    from app.db.session import create_database
    from app.services.broadcasts import BroadcastWorker
    from app.services.channels import ChannelBootstrapError, bootstrap_initial_channel

    settings = load_settings_or_exit()
    settings.media_root.resolve().mkdir(parents=True, exist_ok=True)
    database = create_database(settings.database_path)
    try:
        await database.initialize()
    except SchemaMigrationError as exc:
        await database.close()
        logger.error("Database migration failed: %s", exc)
        raise SystemExit(2) from None

    if check_only:
        await database.close()
        logger.info("Configuration and database initialization check succeeded")
        return

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    broadcast_worker: BroadcastWorker | None = None
    try:
        try:
            await bootstrap_initial_channel(bot, settings, database.session_factory)
        except ChannelBootstrapError as exc:
            logger.error("Channel bootstrap failed: %s", exc)
            raise SystemExit(2) from None
        broadcast_worker = BroadcastWorker(bot, database.session_factory)
        await broadcast_worker.start()
        dispatcher = build_dispatcher()
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(
            bot,
            settings=settings,
            session_factory=database.session_factory,
            broadcast_worker=broadcast_worker,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        if broadcast_worker is not None:
            await broadcast_worker.stop()
        await bot.session.close()
        await database.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram registration bot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and initialize the database without contacting Telegram",
    )
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help="validate configuration and check the existing database without contacting Telegram",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    if args.healthcheck:
        healthcheck_or_exit(load_settings_or_exit())
        return
    asyncio.run(run(check_only=args.check))


if __name__ == "__main__":
    main()
