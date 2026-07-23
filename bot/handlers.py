from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .callback_cache import CallbackCache
from .keycloak_client import KeycloakService
from .settings import SettingsStore

MAX_LIST = 30
PAGE_SIZE = 20

SETTINGS_LABELS = {
    "notify_new_users": "Новые пользователи",
    "notify_logins": "Входы пользователей",
}


class AddUserState(StatesGroup):
    waiting_query = State()


def build_router() -> Router:
    router = Router()

    @router.message(Command("start", "help"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Бот управления группами Keycloak.\n\n"
            "/groups — список групп и участников\n"
            "/users — список всех пользователей\n"
            "/newgroup Название — создать группу\n"
            "/settings — включить/выключить уведомления\n"
            "/cancel — отменить текущее действие"
        )

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Отменено.")

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
            await query.answer("Устарело, откройте /users заново.", show_alert=True)
            return
        user_id, first = pair
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("urg:"))
    async def cb_user_remove_group(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        triple = cache.get(query.data.split(":", 1)[1])
        if triple is None:
            await query.answer("Устарело, откройте пользователя заново.", show_alert=True)
            return
        user_id, group_id, first = triple
        await kc.remove_user_from_group(user_id, group_id)
        await query.answer("Удалён из группы.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.callback_query(F.data.startswith("uag:"))
    async def cb_user_add_group_start(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Устарело.", show_alert=True)
            return
        user_id, first = pair
        await _send_group_picker(query.message, kc, cache, user_id, first, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("uagpick:"))
    async def cb_user_add_group_pick(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        triple = cache.get(query.data.split(":", 1)[1])
        if triple is None:
            await query.answer("Устарело.", show_alert=True)
            return
        user_id, group_id, first = triple
        await kc.add_user_to_group(user_id, group_id)
        await query.answer("Добавлен в группу.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.callback_query(F.data.startswith("ue:"))
    async def cb_user_toggle_enabled(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Устарело.", show_alert=True)
            return
        user_id, first = pair
        user = await kc.get_user(user_id)
        new_enabled = not user.get("enabled", True)
        await kc.set_user_enabled(user_id, new_enabled)
        await query.answer("Пользователь включён." if new_enabled else "Пользователь отключён.")
        await _send_user_view(query.message, kc, cache, user_id, first, edit=True)

    @router.message(Command("settings"))
    async def cmd_settings(message: Message, settings: SettingsStore) -> None:
        await _send_settings(message, settings)

    @router.callback_query(F.data.startswith("st:"))
    async def cb_toggle_setting(query: CallbackQuery, settings: SettingsStore) -> None:
        key = query.data.split(":", 1)[1]
        settings.set(key, not settings.get(key))
        await query.answer("Сохранено." if settings.persist else "Изменено (сбросится при рестарте контейнера).")
        await _send_settings(query.message, settings, edit=True)

    @router.message(Command("newgroup"))
    async def cmd_newgroup(message: Message, command: CommandObject, kc: KeycloakService) -> None:
        name = (command.args or "").strip()
        if not name:
            await message.answer("Использование: /newgroup Название группы")
            return
        await kc.create_group(name)
        await message.answer(f"Группа «{name}» создана.")

    @router.callback_query(F.data == "groups")
    async def cb_groups(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        await _send_groups_list(query.message, kc, cache, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("g:"))
    async def cb_open_group(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("Список устарел, откройте /groups заново.", show_alert=True)
            return
        await _send_group_view(query.message, kc, cache, group_id, edit=True)
        await query.answer()

    @router.callback_query(F.data.startswith("mr:"))
    async def cb_remove_member(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Устарело, откройте группу заново.", show_alert=True)
            return
        group_id, user_id = pair
        await kc.remove_user_from_group(user_id, group_id)
        await query.answer("Удалён из группы.")
        await _send_group_view(query.message, kc, cache, group_id, edit=True)

    @router.callback_query(F.data.startswith("gd:"))
    async def cb_delete_group_ask(query: CallbackQuery, cache: CallbackCache) -> None:
        token = query.data.split(":", 1)[1]
        group_id = cache.get(token)
        if group_id is None:
            await query.answer("Устарело.", show_alert=True)
            return
        confirm_token = cache.put(group_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"gdc:{confirm_token}"),
            InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"g:{token}"),
        ]])
        await query.message.edit_text("Удалить эту группу без возможности восстановления?", reply_markup=kb)
        await query.answer()

    @router.callback_query(F.data.startswith("gdc:"))
    async def cb_delete_group_confirm(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("Устарело.", show_alert=True)
            return
        await kc.delete_group(group_id)
        await query.answer("Группа удалена.")
        await _send_groups_list(query.message, kc, cache, edit=True)

    @router.callback_query(F.data.startswith("ga:"))
    async def cb_add_user_start(query: CallbackQuery, cache: CallbackCache, state: FSMContext) -> None:
        group_id = cache.get(query.data.split(":", 1)[1])
        if group_id is None:
            await query.answer("Устарело.", show_alert=True)
            return
        await state.update_data(group_id=group_id)
        await state.set_state(AddUserState.waiting_query)
        await query.message.answer(
            "Введите часть username или email пользователя для поиска (/cancel — отмена)."
        )
        await query.answer()

    @router.message(AddUserState.waiting_query)
    async def on_search_query(message: Message, state: FSMContext, kc: KeycloakService, cache: CallbackCache) -> None:
        data = await state.get_data()
        group_id = data.get("group_id")
        search = (message.text or "").strip()
        if not search:
            await message.answer("Пустой запрос, попробуйте ещё раз.")
            return
        users = await kc.list_users(search=search, max_results=MAX_LIST)
        if not users:
            await message.answer("Никого не нашлось. Попробуйте другой запрос или /cancel.")
            return
        buttons = []
        for user in users[:MAX_LIST]:
            token = cache.put((group_id, user["id"]))
            label = user.get("username") or user.get("email") or user["id"]
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"up:{token}")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите пользователя:", reply_markup=kb)

    @router.callback_query(F.data.startswith("up:"))
    async def cb_pick_user(query: CallbackQuery, kc: KeycloakService, cache: CallbackCache, state: FSMContext) -> None:
        pair = cache.get(query.data.split(":", 1)[1])
        if pair is None:
            await query.answer("Устарело.", show_alert=True)
            return
        group_id, user_id = pair
        await kc.add_user_to_group(user_id, group_id)
        await state.clear()
        await query.answer("Добавлен в группу.")
        await _send_group_view(query.message, kc, cache, group_id, edit=False)

    return router


async def _send_users_list(
    message: Message, kc: KeycloakService, cache: CallbackCache, first: int, edit: bool = False
) -> None:
    total = await kc.count_users()
    page = await kc.list_users_page(first, PAGE_SIZE)

    if not page:
        text = "Пользователей нет." if first == 0 else "Дальше пользователей нет."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for user in page:
        token = cache.put((user["id"], first))
        label = user.get("username") or user.get("email") or user["id"]
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"u:{token}")])

    nav_row = []
    if first > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"ul:{max(0, first - PAGE_SIZE)}"))
    if first + len(page) < total:
        nav_row.append(InlineKeyboardButton(text="Дальше ▶️", callback_data=f"ul:{first + PAGE_SIZE}"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Пользователи {first + 1}–{first + len(page)} из {total}:"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_user_view(
    message: Message, kc: KeycloakService, cache: CallbackCache, user_id: str, first: int, edit: bool
) -> None:
    user = await kc.get_user(user_id)
    groups = await kc.get_user_groups(user_id)

    username = user.get("username") or user.get("email") or user_id
    email = user.get("email", "—")
    status = "включён" if user.get("enabled", True) else "отключён"
    lines = [f"Пользователь: {username}", f"Email: {email}", f"Статус: {status}", "", "Группы:"]

    buttons = []
    if groups:
        for group in groups:
            lines.append(f"• {group['name']}")
            token = cache.put((user_id, group["id"], first))
            buttons.append([InlineKeyboardButton(text=f"❌ {group['name']}", callback_data=f"urg:{token}")])
    else:
        lines.append("(нет групп)")

    add_token = cache.put((user_id, first))
    toggle_token = cache.put((user_id, first))
    toggle_label = "🚫 Отключить" if user.get("enabled", True) else "✅ Включить"
    buttons.append([InlineKeyboardButton(text="➕ Добавить в группу", callback_data=f"uag:{add_token}")])
    buttons.append([InlineKeyboardButton(text=toggle_label, callback_data=f"ue:{toggle_token}")])
    buttons.append([InlineKeyboardButton(text="⬅️ К списку пользователей", callback_data=f"ul:{first}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_group_picker(
    message: Message, kc: KeycloakService, cache: CallbackCache, user_id: str, first: int, edit: bool
) -> None:
    groups = await kc.list_groups()
    if not groups:
        text = "Групп пока нет. Создайте через /newgroup <название>."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for group in groups[:MAX_LIST]:
        token = cache.put((user_id, group["id"], first))
        buttons.append([InlineKeyboardButton(text=group["name"], callback_data=f"uagpick:{token}")])

    back_token = cache.put((user_id, first))
    buttons.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"u:{back_token}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "Выберите группу:"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_groups_list(message: Message, kc: KeycloakService, cache: CallbackCache, edit: bool = False) -> None:
    groups = await kc.list_groups()
    if not groups:
        text = "Групп пока нет. Создайте через /newgroup <название>."
        await (message.edit_text(text) if edit else message.answer(text))
        return

    buttons = []
    for group in groups[:MAX_LIST]:
        token = cache.put(group["id"])
        buttons.append([InlineKeyboardButton(text=group["name"], callback_data=f"g:{token}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Группы ({len(groups)}):"
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_group_view(
    message: Message, kc: KeycloakService, cache: CallbackCache, group_id: str, edit: bool
) -> None:
    group = await kc.get_group(group_id)
    members = await kc.get_group_members(group_id)

    lines = [f"Группа: {group['name']}", f"Участников: {len(members)}", ""]
    buttons = []
    for member in members[:MAX_LIST]:
        label = member.get("username") or member.get("email") or member["id"]
        lines.append(f"• {label}")
        token = cache.put((group_id, member["id"]))
        buttons.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"mr:{token}")])
    if len(members) > MAX_LIST:
        lines.append(f"…и ещё {len(members) - MAX_LIST}")

    add_token = cache.put(group_id)
    del_token = cache.put(group_id)
    buttons.append([InlineKeyboardButton(text="➕ Добавить пользователя", callback_data=f"ga:{add_token}")])
    buttons.append([
        InlineKeyboardButton(text="🗑 Удалить группу", callback_data=f"gd:{del_token}"),
        InlineKeyboardButton(text="⬅️ К списку групп", callback_data="groups"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))


async def _send_settings(message: Message, settings: SettingsStore, edit: bool = False) -> None:
    lines = ["Настройки уведомлений:", ""]
    buttons = []
    for key, label in SETTINGS_LABELS.items():
        enabled = settings.get(key)
        lines.append(f"• {label}: {'✅ включено' if enabled else '🚫 выключено'}")
        toggle_label = f"🚫 Выключить: {label}" if enabled else f"✅ Включить: {label}"
        buttons.append([InlineKeyboardButton(text=toggle_label, callback_data=f"st:{key}")])

    lines.append("")
    lines.append(
        "Сохраняется между рестартами контейнера."
        if settings.persist
        else "Не сохраняется между рестартами контейнера (PERSIST_SETTINGS выключен)."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    await (message.edit_text(text, reply_markup=kb) if edit else message.answer(text, reply_markup=kb))
