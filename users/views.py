import hashlib
import hmac
import json
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from users.forms import SignUpForm
from users.models import Profile


def _get_next_url(request):
    return request.GET.get('next') or request.POST.get('next') or reverse('home')


def _build_username(base_username):
    base = base_username or 'tg_user'
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}_{suffix}"
        suffix += 1
    return username


def _get_telegram_token():
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or getattr(settings, 'TELEGRAM_LOGIN_BOT_TOKEN', '')
    if token and isinstance(token, str):
        return token.strip()
    return ''


def _get_telegram_bot_name():
    value = (
        getattr(settings, 'TELEGRAM_BOT_NAME', '')
        or getattr(settings, 'TELEGRAM_LOGIN_BOT', '')
        or getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
    )
    if not isinstance(value, str):
        return ''
    return value.strip().lstrip('@')


def _get_telegram_context():
    bot_name = _get_telegram_bot_name()
    token = _get_telegram_token()
    return {
        'telegram_bot_name': bot_name,
        'telegram_login_enabled': bool(bot_name and token),
    }


def _verify_telegram_payload(payload):
    token = _get_telegram_token()
    if not token:
        return False

    check_hash = payload.get('hash')
    if not check_hash:
        return False

    data_check_arr = []
    for key in sorted(k for k in payload.keys() if k != 'hash'):
        data_check_arr.append(f"{key}={payload[key]}")
    data_check_string = '\n'.join(data_check_arr)

    secret_key = hashlib.sha256(token.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if calculated_hash != check_hash:
        return False

    auth_date = payload.get('auth_date')
    try:
        auth_timestamp = int(auth_date)
    except (TypeError, ValueError):
        return False

    if time.time() - auth_timestamp > 86400:
        return False

    return True


def _get_or_create_user_from_telegram(payload):
    telegram_id = str(payload.get('id'))
    if not telegram_id:
        return None

    profile = Profile.objects.filter(telegram_id=telegram_id).select_related('user').first()
    if profile:
        user = profile.user
        updated = False
        username = payload.get('username')
        if username and profile.telegram_username != username:
            profile.telegram_username = username
            updated = True
        if updated:
            profile.save(update_fields=['telegram_username'])
        return user

    username_base = payload.get('username')
    username = _build_username(username_base or f"tg_{telegram_id}")

    first_name = payload.get('first_name', '') or ''
    last_name = payload.get('last_name', '') or ''

    with transaction.atomic():
        user = User.objects.create(username=username, first_name=first_name, last_name=last_name)
        user.set_unusable_password()
        user.save(update_fields=['password', 'first_name', 'last_name'])

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.telegram_id = telegram_id
        profile.telegram_username = payload.get('username', '') or ''
        profile.save(update_fields=['telegram_id', 'telegram_username'])

    return user


def register_view(request):
    next_url = _get_next_url(request)

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Регистрация прошла успешно!')
            return redirect(next_url)
    else:
        form = SignUpForm()
    context = {
        'form': form,
        'next_url': next_url,
        'telegram_redirect_url': next_url,
    }
    context.update(_get_telegram_context())
    return render(request, 'users/register.html', context)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    next_url = _get_next_url(request)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, 'Вы вошли в систему!')
            return redirect(next_url)
        else:
            messages.error(request, 'Неверный логин или пароль')
    else:
        form = AuthenticationForm()
    context = {
        'form': form,
        'next_url': next_url,
        'telegram_redirect_url': next_url,
    }
    context.update(_get_telegram_context())
    return render(request, 'users/login.html', context)


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'Вы вышли из системы.')
    return redirect('home')


@csrf_exempt
@require_POST
def telegram_login_view(request):
    context = _get_telegram_context()
    if not context['telegram_login_enabled']:
        return JsonResponse({'ok': False, 'error': 'Telegram авторизация не настроена.'}, status=503)

    try:
        raw_payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Неверный формат данных.'}, status=400)

    next_url = raw_payload.pop('next', None)
    payload = {key: str(value) for key, value in raw_payload.items()}

    if not _verify_telegram_payload(payload):
        return JsonResponse({'ok': False, 'error': 'Не удалось подтвердить данные Telegram.'}, status=403)

    user = _get_or_create_user_from_telegram(payload)
    if not user:
        return JsonResponse({'ok': False, 'error': 'Не удалось создать пользователя.'}, status=400)

    login(request, user)

    redirect_url = next_url or request.GET.get('next') or request.POST.get('next') or reverse('home')
    return JsonResponse({'ok': True, 'redirect_url': redirect_url})
