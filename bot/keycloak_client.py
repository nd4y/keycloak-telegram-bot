from __future__ import annotations

import asyncio

from keycloak import KeycloakAdmin, KeycloakOpenIDConnection

from .config import Config


class KeycloakService:
    """Async wrapper around python-keycloak's blocking admin client."""

    def __init__(self, config: Config) -> None:
        connection = KeycloakOpenIDConnection(
            server_url=config.keycloak_url,
            realm_name=config.keycloak_realm,
            client_id=config.keycloak_client_id,
            client_secret_key=config.keycloak_client_secret,
            verify=config.verify_ssl,
        )
        self._admin = KeycloakAdmin(connection=connection)

    async def list_users(self, search: str | None = None, max_results: int = 1000) -> list[dict]:
        return await asyncio.to_thread(self._list_users_sync, search, max_results)

    def _list_users_sync(self, search: str | None, max_results: int) -> list[dict]:
        users: list[dict] = []
        first = 0
        page_size = 100
        while len(users) < max_results:
            query = {"first": first, "max": page_size}
            if search:
                query["search"] = search
            page = self._admin.get_users(query=query)
            if not page:
                break
            users.extend(page)
            if len(page) < page_size:
                break
            first += page_size
        return users[:max_results]

    async def list_users_page(self, first: int, max_results: int = 20) -> list[dict]:
        return await asyncio.to_thread(self._admin.get_users, {"first": first, "max": max_results})

    async def count_users(self) -> int:
        return await asyncio.to_thread(self._admin.users_count)

    async def get_user(self, user_id: str) -> dict:
        return await asyncio.to_thread(self._admin.get_user, user_id)

    async def get_user_groups(self, user_id: str) -> list[dict]:
        return await asyncio.to_thread(self._admin.get_user_groups, user_id)

    async def set_user_enabled(self, user_id: str, enabled: bool) -> None:
        await asyncio.to_thread(self._admin.update_user, user_id, {"enabled": enabled})

    async def get_login_events(self, max_results: int = 200) -> list[dict]:
        return await asyncio.to_thread(self._admin.get_events, {"type": "LOGIN", "max": max_results})

    async def list_groups(self) -> list[dict]:
        return await asyncio.to_thread(self._admin.get_groups)

    async def get_group(self, group_id: str) -> dict:
        return await asyncio.to_thread(self._admin.get_group, group_id)

    async def get_group_members(self, group_id: str, max_results: int = 500) -> list[dict]:
        return await asyncio.to_thread(self._admin.get_group_members, group_id, {"max": max_results})

    async def create_group(self, name: str) -> str:
        return await asyncio.to_thread(self._admin.create_group, {"name": name})

    async def delete_group(self, group_id: str) -> None:
        await asyncio.to_thread(self._admin.delete_group, group_id)

    async def add_user_to_group(self, user_id: str, group_id: str) -> None:
        await asyncio.to_thread(self._admin.group_user_add, user_id, group_id)

    async def remove_user_from_group(self, user_id: str, group_id: str) -> None:
        await asyncio.to_thread(self._admin.group_user_remove, user_id, group_id)
