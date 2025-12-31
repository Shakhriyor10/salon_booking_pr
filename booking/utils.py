import requests
from django.conf import settings

TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

def send_telegram_by_username(username, text):
    if not username.startswith('@'):
        username = '@' + username

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': username,
        'text': text,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, data=data)
        print('Telegram response:', response.status_code, response.text)  # ⬅️ добавили
        return response.ok
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False