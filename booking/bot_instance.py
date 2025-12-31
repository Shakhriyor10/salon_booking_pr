# booking/bot_instance.py

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from django.conf import settings

BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
