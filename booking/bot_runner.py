import os
import sys
import asyncio
from pathlib import Path

import django
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from asgiref.sync import sync_to_async

# --- добавляем корень проекта в PYTHONPATH и инициализируем Django ---
BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR_STR = str(BASE_DIR)
if BASE_DIR_STR not in sys.path:
    sys.path.insert(0, BASE_DIR_STR)
os.chdir(BASE_DIR_STR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salon_booking.settings")
django.setup()

from django.conf import settings  # noqa: E402
from booking.models import Stylist  # noqa: E402  (после django.setup)

BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
router = Router()
dp.include_router(router)


@sync_to_async
def _get_stylist_by_username(username: str):
    return Stylist.objects.filter(telegram_username=username).first()


@sync_to_async
def _save_stylist_chat(stylist: Stylist, chat_id: int):
    stylist.telegram_chat_id = chat_id
    stylist.save(update_fields=["telegram_chat_id"])


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    tg_user = message.from_user
    username = tg_user.username
    chat_id = tg_user.id

    text_ok = (
        "👋 Спасибо! Теперь вы будете получать уведомления "
        "о новых записях прямо здесь."
    )
    text_fail = (
        "🤔 Я не нашёл вас в базе мастеров.\n"
        "Обратитесь к администратору и убедитесь, "
        "что ваш username указан в профиле."
    )

    stylist = await _get_stylist_by_username(username)
    if stylist:
        await _save_stylist_chat(stylist, chat_id)
        await message.answer(text_ok)
    else:
        await message.answer(text_fail)


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
