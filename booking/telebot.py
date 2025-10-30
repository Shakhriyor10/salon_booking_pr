# booking/telebot.py
import asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "7539711094:AAFhfqw5i8kLrGZoMlpiAYQM4JS5XMn9Cys"

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
    Сначала пытаемся отправить сообщение по @username, если он указан.
    Если username отсутствует или отправка не удалась, пробуем chat_id.
    """

    targets = []

    if username:
        targets.append(f"@{username.lstrip('@')}")

    if chat_id is not None:
        targets.append(chat_id)

    if not targets:
        return False

    for target in targets:
        try:
            asyncio.run(_send(target, text))
            return True
        except Exception as e:
            print(f"Telegram send error for {target}:", e)

    return False
