# booking/telebot.py
import asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from django.conf import settings

BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

async def _send(chat_id_or_username: str, text: str):
    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    try:
        await bot.send_message(chat_id_or_username, text)
    finally:
        await bot.session.close()

def send_telegram(chat_id: int = None, username: str = None, text: str = ""):
    """
    Сначала пытаемся слать по chat_id, если есть.
    Иначе ‑ по @username (только если пользователь писал боту).
    """
    if chat_id:
        target = chat_id
    elif username:
        target = f"@{username.lstrip('@')}"
    else:
        return False

    try:
        asyncio.run(_send(target, text))
        return True
    except Exception as e:
        print("Telegram send error:", e)
        return False