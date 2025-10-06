import os
import django
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties

# --- инициализируем Django ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salon_booking.settings")
django.setup()

from booking.models import Stylist  # noqa: E402  (после django.setup)

BOT_TOKEN = "7539711094:AAFhfqw5i8kLrGZoMlpiAYQM4JS5XMn9Cys"

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()


@dp.message(commands=["start"])
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

    stylist = Stylist.objects.filter(telegram_username=username).first()
    if stylist:
        stylist.telegram_chat_id = chat_id
        stylist.save(update_fields=["telegram_chat_id"])
        await message.answer(text_ok)
    else:
        await message.answer(text_fail)


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
