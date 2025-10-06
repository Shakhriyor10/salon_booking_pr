# booking/bot_instance.py

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "7539711094:AAFhfqw5i8kLrGZoMlpiAYQM4JS5XMn9Cys"

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
