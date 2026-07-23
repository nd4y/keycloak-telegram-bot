from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    telegram_token: str
    admin_ids: set[int]
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str
    poll_interval: int
    verify_ssl: bool
    notify_new_users_default: bool
    notify_logins_default: bool
    persist_settings: bool


def _parse_ids(raw: str) -> set[int]:
    return {int(x.strip()) for x in raw.split(",") if x.strip()}


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> Config:
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        admin_ids=_parse_ids(os.environ["ADMIN_CHAT_IDS"]),
        keycloak_url=os.environ["KEYCLOAK_URL"].rstrip("/"),
        keycloak_realm=os.environ["KEYCLOAK_REALM"],
        keycloak_client_id=os.environ["KEYCLOAK_CLIENT_ID"],
        keycloak_client_secret=os.environ["KEYCLOAK_CLIENT_SECRET"],
        poll_interval=int(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
        verify_ssl=os.environ.get("KEYCLOAK_VERIFY_SSL", "true").lower() != "false",
        notify_new_users_default=_parse_bool(os.environ.get("NOTIFY_NEW_USERS", "true")),
        notify_logins_default=_parse_bool(os.environ.get("NOTIFY_LOGINS", "false")),
        persist_settings=_parse_bool(os.environ.get("PERSIST_SETTINGS", "false")),
    )
