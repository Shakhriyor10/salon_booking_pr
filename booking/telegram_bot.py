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
from datetime import datetime
import html
from typing import Any, Dict, List, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

API_BASE_URL = os.getenv("TELEGRAM_API_BASE_URL", "http://localhost:8000/api/")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7916518008:AAEULpvz8GS9mYnWsO_FWOXEXv6qzSxTcts")

router = Router()
auth_tokens: Dict[int, str] = {}
salon_cache: Dict[int, Dict[str, Any]] = {}


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
            data = await resp.json(content_type=None)
            return resp.status, data


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Приветствие и выбор между входом и регистрацией."""

    await state.clear()

    if auth_tokens.get(message.from_user.id):
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
        await message.answer(
            "🎉 Регистрация успешна! Токен сохранён. Давай сразу посмотрим, какие салоны есть рядом:"
        )
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
        await message.answer(
            "Успешный вход. Доступные салоны ниже — выберите подходящий:"
        )
        await send_salons_overview(message)
    else:
        await message.answer("Неверные данные или сервер недоступен.")
    await state.clear()


@router.message(Command("salons"))
async def list_salons(message: Message):
    await send_salons_overview(message)


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
        photos = item.get("photos") or []
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
        if avatar:
            await target_message.answer_photo(avatar, caption=caption)
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
    else:
        detail = resp.get("detail") if isinstance(resp, dict) else "Неизвестная ошибка"
        await callback.message.edit_text(f"Не удалось создать запись: {detail}")

    await state.clear()
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