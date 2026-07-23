from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from .keycloak_client import KeycloakService
from .settings import SettingsStore
from .storage import LoginPollState, SeenUsersStore

logger = logging.getLogger(__name__)


async def poll_new_users(
    bot: Bot,
    kc: KeycloakService,
    store: SeenUsersStore,
    settings: SettingsStore,
    admin_ids: set[int],
    interval_seconds: int,
) -> None:
    if not store.baseline_done:
        existing = await kc.list_users(max_results=10000)
        store.seed_baseline(user["id"] for user in existing)
        logger.info("Seeded baseline with %d existing users, notifications start from now on", len(existing))

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            users = await kc.list_users(max_results=10000)
        except Exception:
            logger.exception("Failed to poll Keycloak for new users")
            continue

        for user in users:
            if store.is_new(user["id"]):
                store.mark_seen(user["id"])
                if settings.get("notify_new_users"):
                    await _notify_new_user(bot, admin_ids, user)


async def poll_login_events(
    bot: Bot,
    kc: KeycloakService,
    state: LoginPollState,
    settings: SettingsStore,
    admin_ids: set[int],
    interval_seconds: int,
) -> None:
    if state.last_time == 0:
        try:
            recent = await kc.get_login_events(max_results=1)
        except Exception:
            logger.exception("Failed to fetch initial Keycloak login events")
            recent = []
        state.advance(recent[0]["time"] if recent else 1)
        logger.info("Seeded login event baseline, notifications start from now on")

    while True:
        await asyncio.sleep(interval_seconds)
        if not settings.get("notify_logins"):
            continue
        try:
            events = await kc.get_login_events(max_results=200)
        except Exception:
            logger.exception("Failed to poll Keycloak for login events")
            continue

        new_events = sorted(
            (e for e in events if e.get("time", 0) > state.last_time),
            key=lambda e: e["time"],
        )
        if not new_events:
            continue

        for event in new_events:
            await _notify_login(bot, kc, admin_ids, event)
        state.advance(new_events[-1]["time"])


async def _notify_new_user(bot: Bot, admin_ids: set[int], user: dict) -> None:
    username = user.get("username", "—")
    email = user.get("email", "—")
    text = (
        "🆕 <b>Новый пользователь в Keycloak</b>\n"
        f"Username: {username}\n"
        f"Email: {email}\n"
        f"ID: <code>{user['id']}</code>"
    )
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to notify chat %s about new user", chat_id)


async def _notify_login(bot: Bot, kc: KeycloakService, admin_ids: set[int], event: dict) -> None:
    user_id = event.get("userId")
    username = user_id
    if user_id:
        try:
            user = await kc.get_user(user_id)
            username = user.get("username") or user.get("email") or user_id
        except Exception:
            logger.warning("Could not resolve username for login event, user_id=%s", user_id)

    when = datetime.fromtimestamp(event["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ip = event.get("ipAddress", "—")
    text = (
        "🔐 <b>Вход в Keycloak</b>\n"
        f"Пользователь: {username}\n"
        f"IP: {ip}\n"
        f"Время: {when}"
    )
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to notify chat %s about login event", chat_id)
