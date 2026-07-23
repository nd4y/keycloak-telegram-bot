from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from .callback_cache import CallbackCache
from .config import load_config
from .handlers import BOT_COMMANDS, build_router
from .keycloak_client import KeycloakService
from .middleware import AdminOnlyMiddleware
from .notifier import poll_login_events, poll_new_users
from .settings import SettingsStore
from .storage import LoginPollState, SeenUsersStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    load_dotenv()
    config = load_config()

    bot = Bot(config.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    kc = KeycloakService(config)
    cache = CallbackCache()
    store = SeenUsersStore(Path("data/seen_users.json"))
    login_state = LoginPollState(Path("data/last_login_event.json"))
    settings = SettingsStore(
        Path("data/settings.json"),
        persist=config.persist_settings,
        defaults={
            "notify_new_users": config.notify_new_users_default,
            "notify_logins": config.notify_logins_default,
        },
    )

    dp["kc"] = kc
    dp["cache"] = cache
    dp["settings"] = settings

    dp.message.middleware(AdminOnlyMiddleware(config.admin_ids))
    dp.callback_query.middleware(AdminOnlyMiddleware(config.admin_ids))

    dp.include_router(build_router())

    poll_tasks = [
        asyncio.create_task(
            poll_new_users(bot, kc, store, settings, config.admin_ids, config.poll_interval)
        ),
        asyncio.create_task(
            poll_login_events(bot, kc, login_state, settings, config.admin_ids, config.poll_interval)
        ),
    ]

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(BOT_COMMANDS)
        await dp.start_polling(bot)
    finally:
        for task in poll_tasks:
            task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
