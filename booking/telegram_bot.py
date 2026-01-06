"""
Телеграм-бот на aiogram v3 для работы с API записи в салоны.

Команды:
- /start — приветствие и подсказки
- /register — регистрация и получение токена
- /login — вход по логину и паролю
- /salons — список салонов
- /services <salon_id> — услуги салона
- /stylists <salon_id> — мастера салона
- /book — пошаговая запись
- /appointments — просмотр своих записей
"""
from __future__ import annotations

import asyncio
import os
import json
import calendar
from datetime import date, datetime, timedelta
import html
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL", "https://subcommissarial-paris-untensely.ngrok-free.dev/api/")
_parsed_base = urlparse(API_BASE_URL)
API_ROOT = f"{_parsed_base.scheme}://{_parsed_base.netloc}" if _parsed_base.netloc else ""
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7916518008:AAEULpvz8GS9mYnWsO_FWOXEXv6qzSxTcts")

router = Router()
auth_tokens: Dict[int, str] = {}
salon_cache: Dict[int, Dict[str, Any]] = {}
admin_profiles: Dict[int, Dict[str, Any]] = {}
salon_admin_chats: Dict[int, set[int]] = {}


def normalize_media_url(url: str) -> str:
    """Return a Telegram-safe absolute media URL or empty string if invalid."""

    if not url:
        return ""

    cleaned = str(url).strip()
    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned

    base_parsed = urlparse(API_BASE_URL)
    if base_parsed.scheme in {"http", "https"} and base_parsed.netloc:
        candidate = urljoin(API_BASE_URL, cleaned)
        joined = urlparse(candidate)
        if joined.scheme in {"http", "https"} and joined.netloc:
            return candidate

    return ""


class RegisterStates(StatesGroup):
    username = State()
    first_name = State()
    last_name = State()
    phone = State()
    password = State()


class LoginStates(StatesGroup):
    username = State()
    password = State()


class BookingStates(StatesGroup):
    salon = State()
    stylist = State()
    services = State()
    date = State()
    slot = State()


async def api_request(
    method: str,
    endpoint: str,
    token: Optional[str] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
):
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=json, params=params, headers=headers) as resp:
            try:
                data = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                data = await resp.text()
            return resp.status, data


def get_status_label(status_code: str) -> str:
    return {
        "P": "Ожидает подтверждения",
        "C": "Подтверждена",
        "X": "Отменена",
        "D": "Выполнена",
    }.get(status_code, status_code or "—")


def add_months(base_date: date, delta: int) -> date:
    month = base_date.month - 1 + delta
    year = base_date.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def build_month_keyboard(target_date: date) -> InlineKeyboardMarkup:
    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(target_date.year, target_date.month)
    month_title = target_date.strftime("%B %Y")

    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=month_title, callback_data="noop")],
        [InlineKeyboardButton(text=day, callback_data="noop") for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]],
    ]

    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                day_date = date(target_date.year, target_date.month, day)
                row.append(
                    InlineKeyboardButton(
                        text=str(day), callback_data=f"admin_day:{day_date.isoformat()}"
                    )
                )
        keyboard.append(row)

    prev_month = add_months(target_date, -1)
    next_month = add_months(target_date, 1)
    keyboard.append(
        [
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_month:{prev_month.isoformat()}"),
            InlineKeyboardButton(text="Сегодня", callback_data="admin_today"),
            InlineKeyboardButton(text="➡️", callback_data=f"admin_month:{next_month.isoformat()}"),
        ]
    )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _detach_admin_chat(user_id: int) -> None:
    admin_profiles.pop(user_id, None)
    to_remove = []
    for salon_id, chats in salon_admin_chats.items():
        chats.discard(user_id)
        if not chats:
            to_remove.append(salon_id)
    for salon_id in to_remove:
        salon_admin_chats.pop(salon_id, None)


def _track_admin_chat(user_id: int, profile: Dict[str, Any]) -> None:
    salon = profile.get("salon") or {}
    salon_id = salon.get("id")
    if not salon_id:
        _detach_admin_chat(user_id)
        return

    for chats in salon_admin_chats.values():
        chats.discard(user_id)
    salon_admin_chats.setdefault(salon_id, set()).add(user_id)


async def refresh_admin_profile(user_id: int, token: str) -> None:
    status, data = await api_request("GET", "admin/profile/", token=token)
    if status == 200 and isinstance(data, dict) and data.get("is_salon_admin"):
        admin_profiles[user_id] = data
        _track_admin_chat(user_id, data)
    else:
        _detach_admin_chat(user_id)


def get_admin_profile(user_id: int) -> Optional[Dict[str, Any]]:
    return admin_profiles.get(user_id)


async def send_admin_panel(message: Message):
    profile = get_admin_profile(message.from_user.id)
    if not profile:
        await message.answer("Админ-панель доступна только салон-админам.")
        return

    salon_name = profile.get("salon", {}).get("name", "салон")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗓 Записи салона")],
            [KeyboardButton(text="📊 Отчёты")],
        ],
        resize_keyboard=True,
    )
    await message.answer(
        f"Вы вошли как админ салона «{salon_name}». Выберите раздел:", reply_markup=keyboard
    )


def format_admin_appointment(appointment: Dict[str, Any]) -> str:
    services = ", ".join(appointment.get("services") or []) or "—"
    phone = appointment.get("client_phone") or "—"
    start_time_local = appointment.get("start_time_local") or appointment.get("start_time")
    return (
        f"#{appointment.get('id')} — {start_time_local}\n"
        f"Клиент: {appointment.get('client_name') or '—'} ({phone})\n"
        f"Мастер: {appointment.get('stylist_name') or '—'}\n"
        f"Услуги: {services}\n"
        f"Статус: {get_status_label(appointment.get('status'))}"
    )


def admin_status_keyboard(appointment: Dict[str, Any]) -> InlineKeyboardMarkup | None:
    status_code = str(appointment.get("status") or "").upper()
    appointment_id = appointment.get("id")
    if not appointment_id:
        return None

    if status_code in {"D", "X"}:  # DONE or CANCELLED
        return None

    buttons: List[List[InlineKeyboardButton]] = []
    if status_code == "P":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=f"admin_status:{appointment_id}:confirm"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ Выполнено", callback_data=f"admin_status:{appointment_id}:done"
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Отменить", callback_data=f"admin_status:{appointment_id}:cancel"
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_new_appointment_notice(appointment: Dict[str, Any]) -> str:
    stylist = appointment.get("stylist") or {}
    services = ", ".join(
        s.get("service_name")
        for s in appointment.get("services") or []
        if isinstance(s, dict)
    )
    client = appointment.get("guest_name") or "Клиент"
    start_time_local = appointment.get("start_time_local") or appointment.get("start_time")
    phone = appointment.get("guest_phone") or "—"
    return (
        "<b>📝 Новая запись в салоне</b>\n"
        f"Клиент: {client} ({phone})\n"
        f"Мастер: {stylist.get('full_name') or '—'}\n"
        f"Услуги: {services or '—'}\n"
        f"Время: {start_time_local}"
    )


async def notify_admins_about_new_booking(bot: Bot, appointment: Dict[str, Any]) -> None:
    stylist = appointment.get("stylist") or {}
    salon_id = stylist.get("salon")
    if not salon_id:
        return

    chat_ids = list(salon_admin_chats.get(salon_id, set()))
    if not chat_ids:
        return

    message_text = format_new_appointment_notice(appointment)
    keyboard = admin_status_keyboard(appointment)

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, message_text, reply_markup=keyboard)
        except Exception:
            continue


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Приветствие и выбор между входом и регистрацией."""

    await state.clear()

    token = auth_tokens.get(message.from_user.id)
    if token:
        await refresh_admin_profile(message.from_user.id, token)
        if get_admin_profile(message.from_user.id):
            await send_admin_panel(message)
            return

        await message.answer(
            "Привет! Я помогу записаться в салон. Ниже подборка доступных салонов:"
        )
        await send_salons_overview(message)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти", callback_data="start_login")],
            [InlineKeyboardButton(text="🆕 Регистрация", callback_data="start_register")],
        ]
    )
    await message.answer(
        "Привет! Для записи через бот войдите в свой аккаунт или создайте новый.",
        reply_markup=keyboard,
    )


@router.message(Command("register"))
async def start_register(message: Message, state: FSMContext):
    await state.set_state(RegisterStates.username)
    await message.answer("Введите логин для нового аккаунта:")


@router.callback_query(F.data == "start_register")
async def callback_start_register(callback: CallbackQuery, state: FSMContext):
    await start_register(callback.message, state)
    await callback.answer()


@router.message(RegisterStates.username)
async def register_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(RegisterStates.first_name)
    await message.answer("Имя (можно пропустить):")


@router.message(RegisterStates.first_name)
async def register_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip())
    await state.set_state(RegisterStates.last_name)
    await message.answer("Фамилия (можно пропустить):")


@router.message(RegisterStates.last_name)
async def register_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text.strip())
    await state.set_state(RegisterStates.phone)
    await message.answer("Телефон в формате 93-123-45-67:")


@router.message(RegisterStates.phone)
async def register_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(RegisterStates.password)
    await message.answer("Пароль (не короче 3 символов):")


@router.message(RegisterStates.password)
async def register_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    payload = await state.get_data()

    status, data = await api_request("POST", "auth/register/", json=payload)
    if status == 201 and "token" in data:
        auth_tokens[message.from_user.id] = data["token"]
        await refresh_admin_profile(message.from_user.id, data["token"])
        await message.answer(
            "🎉 Регистрация успешна! Токен сохранён. Давай сразу посмотрим, какие салоны есть рядом:"
        )
        if get_admin_profile(message.from_user.id):
            await send_admin_panel(message)
        else:
            await send_salons_overview(message)
    else:
        error_text = data.get("detail") if isinstance(data, dict) else "Неизвестная ошибка"
        await message.answer(f"Не удалось зарегистрироваться: {error_text}")
    await state.clear()


@router.message(Command("login"))
async def start_login(message: Message, state: FSMContext):
    await state.set_state(LoginStates.username)
    await message.answer("Введите логин:")


@router.callback_query(F.data == "start_login")
async def callback_start_login(callback: CallbackQuery, state: FSMContext):
    await start_login(callback.message, state)
    await callback.answer()


@router.message(LoginStates.username)
async def login_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(LoginStates.password)
    await message.answer("Введите пароль:")


@router.message(LoginStates.password)
async def login_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    payload = await state.get_data()
    status, data = await api_request("POST", "auth/token/", json=payload)
    if status == 200 and "token" in data:
        auth_tokens[message.from_user.id] = data["token"]
        await refresh_admin_profile(message.from_user.id, data["token"])
        await message.answer(
            "Успешный вход. Доступные салоны ниже — выберите подходящий:"
        )
        if get_admin_profile(message.from_user.id):
            await send_admin_panel(message)
        else:
            await send_salons_overview(message)
    else:
        await message.answer("Неверные данные или сервер недоступен.")
    await state.clear()


@router.message(Command("salons"))
async def list_salons(message: Message):
    await send_salons_overview(message)


@router.message(F.text == "🗓 Записи салона")
async def admin_appointments_entry(message: Message):
    await send_admin_appointments(message)


@router.message(F.text == "📊 Отчёты")
async def admin_reports_entry(message: Message):
    await admin_reports_message(message)


@router.message(Command("services"))
async def list_services(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Укажите ID салона: /services 1")
        return

    salon_id = parts[1]
    await send_services_keyboard(message, salon_id)


@router.message(Command("stylists"))
async def list_stylists(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Укажите ID салона: /stylists 1")
        return

    salon_id = parts[1]
    await send_stylists_cards(message, salon_id)


async def send_salons_overview(message: Message):
    if get_admin_profile(message.from_user.id):
        await message.answer(
            "Вы авторизованы как админ салона. Управляйте записями и отчётами через меню ниже."
        )
        await send_admin_panel(message)
        return

    status, data = await api_request("GET", "salons/")
    if status != 200:
        await message.answer("Не удалось получить список салонов.")
        return

    salons = data or []
    if not salons:
        await message.answer("Салоны не найдены.")
        return

    salon_cache.clear()
    salon_cache.update({item["id"]: item for item in salons})

    for item in salons:
        photos: List[str] = []
        for photo in item.get("photos") or []:
            normalized = normalize_media_url(photo)
            if normalized.startswith("http"):
                photos.append(normalized)
        city = html.escape(item.get("city", {}).get("name", ""))
        description = html.escape(item.get("description") or "")
        caption = (
            f"<b>{html.escape(item['name'])}</b> (#{item['id']})\n"
            f"📍 {city}, {html.escape(item.get('address') or '—')}\n"
            f"☎️ {html.escape(item.get('phone') or '—')}\n\n"
            f"{description}".strip()
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="ℹ️ Подробнее", callback_data=f"salon_info:{item['id']}")],
                [InlineKeyboardButton(text="🧑‍🎨 Мастера", callback_data=f"show_stylists:{item['id']}")],
                [InlineKeyboardButton(text="💇‍♀️ Услуги", callback_data=f"show_services:{item['id']}")],
            ]
        )

        if photos:
            await message.answer_photo(photos[0], caption=caption, reply_markup=keyboard)
        else:
            await message.answer(caption, reply_markup=keyboard)


async def send_stylists_cards(target_message: Message, salon_id: str):
    status, data = await api_request("GET", "stylists/", params={"salon": salon_id})
    if status != 200:
        await target_message.answer("Не удалось получить список мастеров.")
        return
    if not data:
        await target_message.answer("В салоне пока нет мастеров.")
        return

    for stylist in data:
        caption = (
            f"<b>{html.escape(stylist['full_name'])}</b> (#{stylist['id']})\n"
            f"Уровень: {html.escape(stylist.get('level') or '—')}\n"
            f"{html.escape(stylist.get('bio') or 'Без описания')}"
        )
        avatar = stylist.get("avatar")
        avatar_url = normalize_media_url(avatar) if avatar else ""
        if avatar_url:
            await target_message.answer_photo(avatar_url, caption=caption)
        else:
            await target_message.answer(caption)


@router.callback_query(F.data.startswith("show_stylists:"))
async def callback_show_stylists(callback: CallbackQuery):
    salon_id = callback.data.split(":", 1)[1]
    await send_stylists_cards(callback.message, salon_id)
    await callback.answer()


@router.callback_query(F.data.startswith("salon_info:"))
async def callback_salon_info(callback: CallbackQuery):
    salon_id = int(callback.data.split(":", 1)[1])
    salon = salon_cache.get(salon_id)

    if salon is None:
        status, data = await api_request("GET", "salons/")
        if status == 200:
            salon_cache.update({item["id"]: item for item in data or []})
            salon = salon_cache.get(salon_id)

    if salon is None:
        await callback.message.answer("Не удалось найти информацию о салоне.")
        await callback.answer()
        return

    city = html.escape(salon.get("city", {}).get("name", ""))
    caption = (
        f"<b>{html.escape(salon['name'])}</b> (#{salon['id']})\n"
        f"📍 {city}, {html.escape(salon.get('address') or 'Адрес не указан')}\n"
        f"☎️ {html.escape(salon.get('phone') or '—')}\n\n"
        f"{html.escape(salon.get('description') or 'Описание скоро появится.')}"
    )
    await callback.message.answer(caption)

    latitude = salon.get("latitude")
    longitude = salon.get("longitude")
    if latitude is not None and longitude is not None:
        try:
            await callback.message.answer_location(float(latitude), float(longitude))
        except (TypeError, ValueError):
            pass

    await send_services_keyboard(
        callback.message,
        str(salon_id),
        heading="Выберите услугу и запишитесь:",
    )
    await callback.answer()


async def send_services_keyboard(target_message: Message, salon_id: str, heading: str | None = None):
    status, data = await api_request("GET", f"salons/{salon_id}/services/")
    if status != 200:
        await target_message.answer("Не удалось получить услуги.")
        return

    if not data:
        await target_message.answer("В этом салоне пока нет активных услуг.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{item['service']['name']} — {item['duration']} мин",
                    callback_data=f"service_select:{salon_id}:{item['id']}",
                )
            ]
            for item in data[:10]
        ]
    )

    title = heading if heading is not None else "Выберите услугу:"
    lines = [
        f"#{item['id']}: {item['service']['name']} — {item['duration']} мин"
        for item in data
    ]
    await target_message.answer("\n".join([title] + lines), reply_markup=keyboard)


@router.callback_query(F.data.startswith("show_services:"))
async def callback_show_services(callback: CallbackQuery):
    salon_id = callback.data.split(":", 1)[1]
    await send_services_keyboard(callback.message, salon_id, heading="Список услуг:")
    await callback.answer()


@router.callback_query(F.data.startswith("service_select:"))
async def callback_service_select(callback: CallbackQuery, state: FSMContext):
    _, salon_id, service_id = callback.data.split(":", 2)
    token = auth_tokens.get(callback.from_user.id)
    if not token:
        await callback.message.answer("Сначала войдите через /login или зарегистрируйтесь через /register.")
        await callback.answer()
        return

    status, data = await api_request("GET", "stylists/", params={"salon": salon_id})
    if status != 200 or not data:
        await callback.message.answer("Для салона не найдено мастеров.")
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{item['full_name']} ({item['level']})", callback_data=f"stylist:{item['id']}")]
            for item in data
        ]
    )

    await state.update_data(salon_id=int(salon_id), services=[int(service_id)])
    await state.set_state(BookingStates.stylist)
    await callback.message.answer(
        "Выберите мастера для выбранной услуги:", reply_markup=keyboard
    )
    await callback.answer()


@router.message(Command("appointments"))
async def my_appointments(message: Message):
    token = auth_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала выполните /login или /register.")
        return

    status, data = await api_request("GET", "appointments/", token=token)
    if status != 200:
        await message.answer("Не удалось получить ваши записи.")
        return

    if not data:
        await message.answer("Записей пока нет.")
        return

    lines: List[str] = []
    for item in data:
        stylist = item.get("stylist", {})
        services = ", ".join(s.get("service_name") for s in item.get("services", []))
        start_local = item.get("start_time_local")
        lines.append(
            f"#{item['id']} — {stylist.get('full_name')}\n"
            f"Когда: {start_local}\n"
            f"Услуги: {services or '—'}"
        )
    await message.answer("\n\n".join(lines))


@router.message(Command("book"))
async def start_booking(message: Message, state: FSMContext):
    token = auth_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала выполните /login или /register, чтобы создать запись.")
        return

    status, data = await api_request("GET", "salons/")
    if status != 200 or not data:
        await message.answer("Салоны недоступны для записи сейчас.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{item['name']} ({item['city']['name']})", callback_data=f"salon:{item['id']}")]
            for item in data
        ]
    )
    await state.set_state(BookingStates.salon)
    await message.answer("Выберите салон:", reply_markup=keyboard)


@router.callback_query(BookingStates.salon, F.data.startswith("salon:"))
async def booking_choose_salon(callback: CallbackQuery, state: FSMContext):
    salon_id = int(callback.data.split(":", 1)[1])
    await state.update_data(salon_id=salon_id)

    status, data = await api_request("GET", "stylists/", params={"salon": salon_id})
    if status != 200 or not data:
        await callback.message.edit_text("Мастера не найдены для этого салона.")
        await state.clear()
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{item['full_name']} ({item['level']})", callback_data=f"stylist:{item['id']}")]
            for item in data
        ]
    )
    await state.set_state(BookingStates.stylist)
    await callback.message.edit_text("Выберите мастера:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(BookingStates.stylist, F.data.startswith("stylist:"))
async def booking_choose_stylist(callback: CallbackQuery, state: FSMContext):
    stylist_id = int(callback.data.split(":", 1)[1])
    await state.update_data(stylist_id=stylist_id)

    status, data = await api_request("GET", f"stylists/{stylist_id}/services/")
    if status != 200 or not data:
        await callback.message.edit_text("Для мастера не настроены услуги.")
        await state.clear()
        await callback.answer()
        return

    selected_services = (await state.get_data()).get("services") or []
    available_ids = {item["salon_service"]["id"] for item in data}

    if selected_services and set(selected_services).issubset(available_ids):
        await state.update_data(services=selected_services)
        await state.set_state(BookingStates.date)
        await callback.message.edit_text("Укажите дату в формате ГГГГ-ММ-ДД:")
    else:
        await state.update_data(services=[])
        lines = [
            f"#{item['salon_service']['id']}: {item['salon_service']['service']['name']} — {item['price']} сум, {item['salon_service']['duration']} мин"
            for item in data
        ]
        await state.set_state(BookingStates.services)
        await callback.message.edit_text(
            "Выберите услуги (перечислите ID через запятую):\n" + "\n".join(lines)
        )
    await callback.answer()


@router.message(BookingStates.services)
async def booking_choose_services(message: Message, state: FSMContext):
    try:
        services = [int(part) for part in message.text.replace(" ", "").split(",") if part]
    except ValueError:
        await message.answer("Нужно указать числа через запятую. Пример: 1,2")
        return

    if not services:
        await message.answer("Список услуг пуст. Укажите хотя бы одну услугу.")
        return

    await state.update_data(services=services)
    await state.set_state(BookingStates.date)
    await message.answer("Укажите дату в формате ГГГГ-ММ-ДД:")


@router.message(BookingStates.date)
async def booking_choose_date(message: Message, state: FSMContext):
    try:
        target_date = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Неверный формат даты. Используйте ГГГГ-ММ-ДД.")
        return

    data = await state.get_data()
    stylist_id = data.get("stylist_id")
    services = data.get("services", [])
    params = {"date": target_date.isoformat(), "services": ",".join(map(str, services))}

    status, slots_data = await api_request("GET", f"stylists/{stylist_id}/slots/", params=params)
    if status != 200 or not slots_data.get("slots"):
        await message.answer("Нет доступных слотов на выбранную дату.")
        await state.clear()
        return

    slots = slots_data["slots"][:10]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s["start"].replace("T", " "), callback_data=f"slot:{s['start']}")]
            for s in slots
        ]
    )
    await state.update_data(date=target_date.isoformat())
    await state.set_state(BookingStates.slot)
    await message.answer("Выберите время:", reply_markup=keyboard)


@router.callback_query(BookingStates.slot, F.data.startswith("slot:"))
async def booking_finalize(callback: CallbackQuery, state: FSMContext):
    token = auth_tokens.get(callback.from_user.id)
    if not token:
        await callback.message.edit_text("Токен утрачен, выполните /login заново.")
        await state.clear()
        await callback.answer()
        return

    start_time = callback.data.split(":", 1)[1]
    data = await state.get_data()

    payload = {
        "stylist_id": data.get("stylist_id"),
        "salon_service_ids": data.get("services", []),
        "start_time": start_time,
        "guest_name": "",
        "guest_phone": "",
    }

    status, resp = await api_request("POST", "appointments/", token=token, json=payload)
    if status == 201:
        appointment = resp.get("appointment", {})
        stylist = appointment.get("stylist", {})
        services = ", ".join(s.get("service_name") for s in appointment.get("services", []))
        await callback.message.edit_text(
            "Запись создана!\n"
            f"Мастер: {stylist.get('full_name')}\n"
            f"Время: {appointment.get('start_time_local')}\n"
            f"Услуги: {services or '—'}"
        )
        await notify_admins_about_new_booking(callback.message.bot, appointment)
    else:
        detail = resp.get("detail") if isinstance(resp, dict) else "Неизвестная ошибка"
        await callback.message.edit_text(f"Не удалось создать запись: {detail}")

    await state.clear()
    await callback.answer()


@router.message(Command("admin"))
async def admin_entry(message: Message):
    token = auth_tokens.get(message.from_user.id)
    if not token:
        await message.answer("Сначала выполните /login или /register.")
        return

    await refresh_admin_profile(message.from_user.id, token)
    if not get_admin_profile(message.from_user.id):
        await message.answer("Похоже, у вашего аккаунта нет прав салон-админа.")
        return

    await send_admin_panel(message)


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    await send_admin_panel(callback.message)
    await callback.answer()


async def send_admin_appointments(target_message: Message | CallbackQuery):
    user_id = (
        target_message.from_user.id
        if isinstance(target_message, (Message, CallbackQuery))
        else None
    )

    if user_id is None or not get_admin_profile(user_id):
        if isinstance(target_message, CallbackQuery):
            await target_message.message.answer("Админ-панель доступна только салон-админам.")
            await target_message.answer()
        else:
            await target_message.answer("Админ-панель доступна только салон-админам.")
        return

    message_obj = target_message if isinstance(target_message, Message) else target_message.message
    await message_obj.answer(
        "Выберите дату, чтобы увидеть записи этого дня:",
        reply_markup=build_month_keyboard(date.today()),
    )
    if isinstance(target_message, CallbackQuery):
        await target_message.answer()


@router.callback_query(F.data == "admin_appointments")
async def admin_appointments(callback: CallbackQuery):
    await send_admin_appointments(callback)


@router.callback_query(F.data == "admin_today")
async def admin_today(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=build_month_keyboard(date.today()))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_month:"))
async def admin_month(callback: CallbackQuery):
    try:
        target = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        target = date.today().replace(day=1)

    await callback.message.edit_reply_markup(reply_markup=build_month_keyboard(target))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_day:"))
async def admin_day(callback: CallbackQuery):
    token = auth_tokens.get(callback.from_user.id)
    if not token:
        await callback.message.answer("Сначала выполните вход через /login.")
        await callback.answer()
        return

    day_str = callback.data.split(":", 1)[1]
    status_code, payload = await api_request(
        "GET", "admin/appointments/", token=token, params={"date": day_str}
    )

    if status_code == 403:
        await callback.message.answer("У вашего аккаунта нет прав салон-админа.")
        await callback.answer()
        return

    if status_code != 200 or not isinstance(payload, dict):
        await callback.message.answer("Не удалось получить записи за выбранный день.")
        await callback.answer()
        return

    appointments = payload.get("appointments") or []
    if not appointments:
        await callback.message.answer(f"На {day_str} записей нет.")
        await callback.answer()
        return

    await callback.message.answer(f"Записи на {day_str}:")
    for appointment in appointments:
        keyboard = admin_status_keyboard(appointment)
        await callback.message.answer(format_admin_appointment(appointment), reply_markup=keyboard)

    await callback.answer()


@router.callback_query(F.data.startswith("admin_status:"))
async def admin_status_update(callback: CallbackQuery):
    token = auth_tokens.get(callback.from_user.id)
    if not token:
        await callback.message.answer("Сначала выполните вход через /login.")
        await callback.answer()
        return

    try:
        _, appointment_id, action = callback.data.split(":", 2)
    except ValueError:
        await callback.answer()
        return

    if action == "cancel":
        confirm_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да, отменить",
                        callback_data=f"admin_cancel_yes:{appointment_id}:{callback.message.message_id}",
                    )
                ],
                [InlineKeyboardButton(text="Нет", callback_data="admin_cancel_no")],
            ]
        )
        await callback.message.answer(
            f"Вы точно хотите отменить запись #{appointment_id}?", reply_markup=confirm_keyboard
        )
        await callback.answer()
        return

    status_code, data = await api_request(
        "POST",
        f"admin/appointments/{appointment_id}/status/",
        token=token,
        json={"status": action},
    )

    if status_code == 200 and isinstance(data, dict):
        keyboard = admin_status_keyboard(data)
        await callback.message.edit_text(format_admin_appointment(data), reply_markup=keyboard)
        await callback.answer("Статус обновлён")
        return

    detail = data.get("detail") if isinstance(data, dict) else "Не удалось изменить статус."
    await callback.message.answer(str(detail))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel_yes:"))
async def admin_cancel_yes(callback: CallbackQuery):
    token = auth_tokens.get(callback.from_user.id)
    if not token:
        await callback.message.answer("Сначала выполните вход через /login.")
        await callback.answer()
        return

    try:
        _, appointment_id, origin_message_id = callback.data.split(":", 2)
    except ValueError:
        await callback.answer()
        return

    status_code, data = await api_request(
        "POST",
        f"admin/appointments/{appointment_id}/status/",
        token=token,
        json={"status": "cancel"},
    )

    if status_code == 200 and isinstance(data, dict):
        keyboard = admin_status_keyboard(data)
        try:
            await callback.message.bot.edit_message_text(
                format_admin_appointment(data),
                chat_id=callback.message.chat.id,
                message_id=int(origin_message_id),
                reply_markup=keyboard,
            )
        except Exception:
            await callback.message.answer(format_admin_appointment(data), reply_markup=keyboard)

        await callback.message.edit_text("Запись отменена")
        await callback.answer("Запись отменена")
        return

    detail = data.get("detail") if isinstance(data, dict) else "Не удалось отменить запись."
    await callback.message.answer(str(detail))
    await callback.answer()


@router.callback_query(F.data == "admin_cancel_no")
async def admin_cancel_no(callback: CallbackQuery):
    await callback.message.edit_text("Отмена записи отменена.")
    await callback.answer("Оставляем без изменений")


async def admin_reports_message(target_message: Message | CallbackQuery):
    user_id = (
        target_message.from_user.id
        if isinstance(target_message, (Message, CallbackQuery))
        else None
    )
    profile = get_admin_profile(user_id) if user_id is not None else None
    if not profile:
        if isinstance(target_message, CallbackQuery):
            await target_message.message.answer("Раздел доступен только салон-админам.")
            await target_message.answer()
        else:
            await target_message.answer("Раздел доступен только салон-админам.")
        return

    message_obj = target_message if isinstance(target_message, Message) else target_message.message
    await message_obj.answer(
        "Отчёты по салону доступны в веб-кабинете. Мы сообщим, когда появится сводка прямо в боте."
    )
    if isinstance(target_message, CallbackQuery):
        await target_message.answer()


@router.callback_query(F.data == "admin_reports")
async def admin_reports(callback: CallbackQuery):
    await admin_reports_message(callback)


@router.callback_query(F.data == "noop")
async def ignore_noop(callback: CallbackQuery):
    await callback.answer()


async def main():
    if not BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN не задан в переменных окружения. "
            "Установите переменную или экспортируйте её перед запуском скрипта."
        )
        return

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())