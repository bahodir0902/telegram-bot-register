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

    from app.bot.handlers import admin, contact, errors, start, subscription

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.errors.register(errors.handle_update_error)
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

    from app.db.session import create_database

    settings = load_settings_or_exit()
    settings.media_root.resolve().mkdir(parents=True, exist_ok=True)
    database = create_database(settings.database_path)
    await database.initialize()

    if check_only:
        await database.close()
        logger.info("Configuration and database initialization check succeeded")
        return

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(
            bot,
            settings=settings,
            session_factory=database.session_factory,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
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
