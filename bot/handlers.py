from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .callback_cache import CallbackCache
from .keycloak_client import KeycloakService
from .settings import SettingsStore

MAX_LIST = 30
PAGE_SIZE = 20

SETTINGS_LABELS = {
    "notify_new_users": "New users",
    "notify_logins": "User logins",
}

BOT_COMMANDS = [
    BotCommand(command="groups", description="List groups and members"),
    BotCommand(command="users", description="List all users"),
    BotCommand(command="newgroup", description="Create a group"),
    BotCommand(command="settings", description="Toggle notifications"),
    BotCommand(command="cancel", description="Cancel the current action"),
    BotCommand(command="help", description="Show help"),
]

BTN_GROUPS = "📋 Groups"
BTN_USERS = "👥 Users"
BTN_SETTINGS = "⚙️ Settings"
BTN_HELP = "❓ Help"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_GROUPS), KeyboardButton(text=BTN_USERS)],
        [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_HELP)],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


class AddUserState(StatesGroup):
    waiting_query = State()


def build_router() -> Router:
    router = Router()

    @router.message(Command("start", "help"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Keycloak group management bot.\n\n"
            "/groups — list groups and members\n"
            "/users — list all users\n"
            "/newgroup Name — create a group\n"
            "/settings — toggle notifications\n"
            "/cancel — cancel the current action",
            reply_markup=MAIN_KEYBOARD,
        )

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled.")

    @router.message(F.text == BTN_GROUPS)
    async def btn_groups(message: Message, kc: KeycloakService, cache: CallbackCache, state: FSMContext) -> None:
        await state.clear()
        await _send_groups_list(message, kc, cache)

    @router.message(F.text == BTN_USERS)
    async def btn_users(message: Message, kc: KeycloakService, cache: CallbackCache, state: FSMContext) -> None:
        await state.clear()
        await _send_users_list(message, kc, cache, first=0)

    @router.message(F.text == BTN_SETTINGS)
    async def btn_settings(message: Message, settings: SettingsStore, state: FSMContext) -> None:
        await state.clear()
        await _send_settings(message, settings)

    @router.message(F.text == BTN_HELP)
    async def btn_help(message: Message, state: FSMContext) -> None:
        await state.clear()
        await cmd_start(message)

    @router.message(Command("groups"))
    async def cmd_groups(message: Message, kc: KeycloakService, cache: CallbackCache) -> None:
        await _send_groups_list(message, kc, cache)

    @router.message(Command("users"))
    async def cmd_users(message: Message, kc: KeycloakService, cache: CallbackCache) -> None:
        await _send_users_list(message, kc, cache, first=0)

    @router.callback_query(F.data.startswith("ul:"))
    async def cb_users_page(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        first = int(query.data.split(":", 1)[1])
        await _send_users_list(query.message, kc, cache, first=first, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("u:"))
    async def cb_open_user(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Expired, reopen /users.", show_alert=True)
            return
        user_id, first = pair
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("urg:"))
    async def cb_user_remove_group(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        triple = cache.get(query.data.split(":", 1)[1])
        if triple is None:
            await query.answer("Expired, reopen the user.", show_alert=True)
            return
        user_id, group_id, first = triple
        await kc.remove_user_from_group(user_id, group_id)
        await query.answer("Removed from group.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.callback_query(F.data.startswith("uag:"))
    async def cb_user_add_group_start(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Expired.", show_alert=True)
            return
        user_id, first = pair
        await _send_group_picker(query.message, kc, cache, user_id, first, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("uagpick:"))
    async def cb_user_add_group_pick(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        triple = cache.get(query.data.split(":", 1)[1])
        if triple is None:
            await query.answer("Expired.", show_alert=True)
            return
        user_id, group_id, first = triple
        await kc.add_user_to_group(user_id, group_id)
        await query.answer("Added to group.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.callback_query(F.data.startswith("ue:"))
    async def cb_user_toggle_enabled(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Expired.", show_alert=True)
            return
        user_id, first = pair
        user = await kc.get_user(user_id)
        new_enabled = not user.get("enabled", True)
        await kc.set_user_enabled(user_id, new_enabled)
        await query.answer("User enabled." if new_enabled else "User disabled.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.message(Command("settings"))
    async def cmd_settings(message: Message, settings: SettingsStore) -> None:
        await _send_settings(message, settings)

    @router.callback_query(F.data.startswith("st:"))
    async def cb_toggle_setting(query: CallbackQuery, settings: SettingsStore) -> None:
        key = query.data.split(":", 1)[1]
        settings.set(key, not settings.get(key))
        await query.answer("Saved." if settings.persist else "Changed (resets on container restart).")
        await _send_settings(query.message, settings, edit=True)

    @router.message(Command("newgroup"))
    async def cmd_newgroup(message: Message, command: CommandObject, kc: KeycloakService) -> None:
        name = (command.args or "").strip()
        if not name:
            await message.answer("Usage: /newgroup Group name")
            return
        await kc.create_group(name)
        await message.answer(f'Group "{name}" created.')

    @router.callback_query(F.data == "groups")
    async def cb_groups(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        await _send_groups_list(query.message, kc, cache, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("g:"))
    async def cb_open_group(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("List expired, reopen /groups.", show_alert=True)
            return
        await _send_group_view(query.message, kc, cache, group_id, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("mr:"))
    async def cb_remove_member(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Expired, reopen the group.", show_alert=True)
            return
        group_id, user_id = pair
        await kc.remove_user_from_group(user_id, group_id)
        await query.answer("Removed from group.")
        await _send_group_view(query.message, kc, cache, group_id, edit=True)

    @router.callback_query(F.data.startswith("gd:"))
    async def cb_delete_group_ask(query: CallbackQuery, cache: CallbackCache) -> None:
        token = query.data.split(":", 1)[1]
        group_id = cache.get(token)
        if group_id is None:
            await query.answer("Expired.", show_alert=True)
            return
        confirm_token = cache.put(group_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yes, delete", callback_data=f"gdc:{confirm_token}"),
            InlineKeyboardButton(text="⬅️ Cancel", callback_data=f"g:{token}"),
        ]])
        await query.message.edit_text("Delete this group permanently?", reply_markup=kb)
        await query.answer()

    @router.callback_query(F.data.startswith("gdc:"))
    async def cb_delete_group_confirm(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("Expired.", show_alert=True)
            return
        await kc.delete_group(group_id)
        await query.answer("Group deleted.")
        await _send_groups_list(query.message, kc, cache, edit=True)

    @router.callback_query(F.data.startswith("ga:"))
    async def cb_add_user_start(query: CallbackQuery, cache: CallbackCache, state: FSMContext) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("Expired.", show_alert=True)
            return
        await state.update_data(group_id=group_id)
        await state.set_state(AddUserState.waiting_query)
        await query.message.answer(
            "Type part of a username or email to search (/cancel to abort)."
        )
        await query.answer()

    @router.message(AddUserState.waiting_query)
    async def on_search_query(message: Message, state: FSMContext, kc: KeycloakService, cache: CallbackCache) -> None:
        data = await state.get_data()
        group_id = data.get("group_id")
        search = (message.text or "").strip()
        if not search:
            await message.answer("Empty query, try again.")
            return
        users = await kc.list_users(search=search, max_results=MAX_LIST)
        if not users:
            await message.answer("No matches. Try a different query or /cancel.")
            return
        buttons = []
        for user in users[:MAX_LIST]:
            token = cache.put((group_id, user["id"]))
            label = user.get("username") or user.get("email") or user["id"]
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"up:{token}")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Pick a user:", reply_markup=kb)

    @router.callback_query(F.data.startswith("up:"))
    async def cb_pick_user(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache, state: FSMContext) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Expired.", show_alert=True)
            return
        group_id, user_id = pair
        await kc.add_user_to_group(user_id, group_id)
        await state.clear()
        await query.answer("Added to group.")
        await _send_group_view(query.message, kc, cache, group_id, edit=False)

    return router


async def _send_users_list(
    message: Message, kc: KeycloakService, cache: CallbackCache, first: int, edit: bool = False
) -> None:
    total = await kc.count_users()
    page = await kc.list_users_page(first, PAGE_SIZE)

    if not page:
        text = "No users." if first == 0 else "No more users."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for user in page:
        token = cache.put((user["id"], first))
        label = user.get("username") or user.get("email") or user["id"]
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"u:{token}")])

    nav_row = []
    if first > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Back", callback_data=f"ul:{max(0, first - PAGE_SIZE)}"))
    if first + len(page) < total:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"ul:{first + PAGE_SIZE}"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Users {first + 1}–{first + len(page)} of {total}:"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_user_view(
    message: Message, kc: KeycloakService, cache: CallbackCache, user_id: str, first: int, edit: bool
) -> None:
    user = await kc.get_user(user_id)
    groups = await kc.get_user_groups(user_id)

    username = user.get("username") or user.get("email") or user_id
    email = user.get("email", "—")
    status = "enabled" if user.get("enabled", True) else "disabled"
    lines = [f"User: {username}", f"Email: {email}", f"Status: {status}", "", "Groups:"]

    buttons = []
    if groups:
        for group in groups:
            lines.append(f"• {group['name']}")
            token = cache.put((user_id, group["id"], first))
            buttons.append([InlineKeyboardButton(text=f"❌ {group['name']}", callback_data=f"urg:{token}")])
    else:
        lines.append("(no groups)")

    add_token = cache.put((user_id, first))
    toggle_token = cache.put((user_id, first))
    toggle_label = "🚫 Disable" if user.get("enabled", True) else "✅ Enable"
    buttons.append([InlineKeyboardButton(text="➕ Add to group", callback_data=f"uag:{add_token}")])
    buttons.append([InlineKeyboardButton(text=toggle_label, callback_data=f"ue:{toggle_token}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back to user list", callback_data=f"ul:{first}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_group_picker(
    message: Message, kc: KeycloakService, cache: CallbackCache, user_id: str, first: int, edit: bool
) -> None:
    groups = await kc.list_groups()
    if not groups:
        text = "No groups yet. Create one with /newgroup <name>."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for group in groups[:MAX_LIST]:
        token = cache.put((user_id, group["id"], first))
        buttons.append([InlineKeyboardButton(text=group["name"], callback_data=f"uagpick:{token}")])

    back_token = cache.put((user_id, first))
    buttons.append([InlineKeyboardButton(text="⬅️ Cancel", callback_data=f"u:{back_token}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "Pick a group:"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_groups_list(message: Message, kc: KeycloakService, cache: CallbackCache, edit: bool = False) -> None:
    groups = await kc.list_groups()
    if not groups:
        text = "No groups yet. Create one with /newgroup <name>."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for group in groups[:MAX_LIST]:
        token = cache.put(group["id"])
        buttons.append([InlineKeyboardButton(text=group["name"], callback_data=f"g:{token}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Groups ({len(groups)}):"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_group_view(
    message: Message, kc: KeycloakService, cache: CallbackCache, group_id: str, edit: bool
) -> None:
    group = await kc.get_group(group_id)
    members = await kc.get_group_members(group_id)

    lines = [f"Group: {group['name']}", f"Members: {len(members)}", ""]
    buttons = []
    for member in members[:MAX_LIST]:
        label = member.get("username") or member.get("email") or member["id"]
        lines.append(f"• {label}")
        token = cache.put((group_id, member["id"]))
        buttons.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"mr:{token}")])
    if len(members) > MAX_LIST:
        lines.append(f"…and {len(members) - MAX_LIST} more")

    add_token = cache.put(group_id)
    del_token = cache.put(group_id)
    buttons.append([InlineKeyboardButton(text="➕ Add user", callback_data=f"ga:{add_token}")])
    buttons.append([
        InlineKeyboardButton(text="🗑 Delete group", callback_data=f"gd:{del_token}"),
        InlineKeyboardButton(text="⬅️ Back to groups", callback_data="groups"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_settings(message: Message, settings: SettingsStore, edit: bool = False) -> None:
    lines = ["Notification settings:", ""]
    buttons = []
    for key, label in SETTINGS_LABELS.items():
        enabled = settings.get(key)
        lines.append(f"• {label}: {'✅ on' if enabled else '🚫 off'}")
        toggle_label = f"🚫 Turn off: {label}" if enabled else f"✅ Turn on: {label}"
        buttons.append([InlineKeyboardButton(text=toggle_label, callback_data=f"st:{key}")])

    lines.append("")
    lines.append(
        "Persists across container restarts."
        if settings.persist
        else "Does not persist across container restarts (PERSIST_SETTINGS is off)."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))
