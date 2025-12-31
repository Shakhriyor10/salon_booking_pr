import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timedelta

import pytz
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from booking.models import (
    Appointment,
    AppointmentService,
    Salon,
    BreakPeriod,
    StylistDayOff,
    WorkingHour,
    StylistService,
)
from booking.telebot import send_telegram
from booking.views import ensure_guest_account, normalize_uzbek_phone
from users.models import Profile


def _parse_init_data(raw_init_data: str):
    """Parse initData from Telegram WebApp and validate its signature."""
    if not raw_init_data:
        return None

    parsed = dict(urllib.parse.parse_qsl(raw_init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(
        b"WebAppData",
        settings.TELEGRAM_BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    user_payload = parsed.get("user")
    if user_payload:
        try:
            parsed["user"] = json.loads(user_payload)
        except json.JSONDecodeError:
            parsed["user"] = None

    return parsed


def _extract_init_data(request):
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.POST.get("init_data")
        or request.GET.get("init_data")
    )


def telegram_webapp_required(view_func):
    @csrf_exempt
    def wrapper(request, *args, **kwargs):
        parsed = _parse_init_data(_extract_init_data(request))
        if not parsed:
            return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

        request.telegram_init = parsed
        request.telegram_user = parsed.get("user") or {}
        return view_func(request, *args, **kwargs)

    return wrapper


def _absolute_media_url(request, image_field):
    if not image_field:
        return None
    return request.build_absolute_uri(image_field.url)


def _serialize_salon(salon, request):
    return {
        "id": salon.id,
        "name": salon.name,
        "address": salon.address,
        "city": salon.city.name,
        "slug": salon.slug,
        "rating": round(salon.average_rating(), 2) if hasattr(salon, "average_rating") else 0,
        "photo": _absolute_media_url(request, salon.photo),
    }


def _serialize_stylist(stylist, request):
    return {
        "id": stylist.id,
        "name": stylist.user.get_full_name() or stylist.user.username,
        "username": stylist.telegram_username,
        "avatar": _absolute_media_url(request, stylist.avatar),
    }


def _serialize_salon_service(salon_service):
    return {
        "id": salon_service.id,
        "name": salon_service.service.name,
        "category": salon_service.category.name if salon_service.category else None,
        "duration_minutes": int(salon_service.duration.total_seconds() // 60),
        "is_active": salon_service.is_active,
    }


@require_GET
@telegram_webapp_required
def telegram_bootstrap(request):
    salons = [
        _serialize_salon(salon, request)
        for salon in Salon.objects.select_related("city").filter(status=True)
        if salon.is_subscription_active
    ]

    return JsonResponse(
        {
            "ok": True,
            "salons": salons,
            "user": request.telegram_user,
        }
    )


@require_GET
@telegram_webapp_required
def telegram_salon_detail(request, salon_id: int):
    salon = (
        Salon.objects.select_related("city")
        .prefetch_related(
            "stylists__user",
            "salon_services__service",
            "salon_services__category",
            "stylists__stylist_services__salon_service__service",
        )
        .filter(id=salon_id, status=True)
        .first()
    )

    if not salon or not salon.is_subscription_active:
        return JsonResponse({"ok": False, "error": "salon_not_found"}, status=404)

    stylists = [_serialize_stylist(stylist, request) for stylist in salon.stylists.all()]
    services = [
        _serialize_salon_service(service)
        for service in salon.salon_services.all()
        if service.is_active
    ]

    return JsonResponse(
        {
            "ok": True,
            "salon": _serialize_salon(salon, request),
            "stylists": stylists,
            "services": services,
        }
    )


@require_GET
@telegram_webapp_required
def telegram_available_times(request):
    stylist_id = request.GET.get("stylist_id")
    salon_service_id = request.GET.get("salon_service_id")
    date_str = request.GET.get("date")

    if not (stylist_id and salon_service_id and date_str):
        return JsonResponse({"ok": False, "times": []})

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "times": []})

    stylist_service = (
        StylistService.objects
        .select_related("salon_service", "stylist")
        .filter(stylist_id=stylist_id, salon_service_id=salon_service_id)
        .first()
    )
    if not stylist_service or not stylist_service.salon_service.is_active:
        return JsonResponse({"ok": False, "times": []})

    stylist = stylist_service.stylist
    duration = stylist_service.salon_service.duration

    working_hours = WorkingHour.objects.filter(stylist=stylist, weekday=target_date.weekday())
    tz = pytz.timezone("Asia/Tashkent")
    slot = timedelta(minutes=15)
    available_slots = []

    for wh in working_hours:
        start_dt = datetime.combine(target_date, wh.start_time)
        end_dt = datetime.combine(target_date, wh.end_time)
        break_periods = BreakPeriod.objects.filter(working_hour=wh)

        while start_dt + duration <= end_dt:
            st_aware = tz.localize(start_dt)
            end_aware = st_aware + duration

            overlap = (
                Appointment.objects
                .filter(
                    stylist=stylist,
                    start_time__lt=end_aware,
                    end_time__gt=st_aware,
                )
                .exclude(status=Appointment.Status.CANCELLED)
                .exists()
            )

            in_break = any(
                start_dt < datetime.combine(target_date, bp.end_time)
                and start_dt + duration > datetime.combine(target_date, bp.start_time)
                for bp in break_periods
            )

            in_dayoff = StylistDayOff.objects.filter(
                stylist=stylist,
                date=target_date,
            ).filter(
                Q(from_time__isnull=True, to_time__isnull=True)
                | Q(from_time__lt=(start_dt + duration).time(), to_time__gt=start_dt.time())
            ).exists()

            if not overlap and not in_break and not in_dayoff:
                available_slots.append(start_dt.strftime("%H:%M"))

            start_dt += slot

    return JsonResponse({"ok": True, "times": available_slots})


@require_POST
@telegram_webapp_required
def telegram_create_appointment(request):
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        payload = {}

    stylist_id = payload.get("stylist_id")
    salon_service_id = payload.get("salon_service_id")
    date_str = payload.get("date")
    time_str = payload.get("time")
    guest_name = (payload.get("guest_name") or "").strip()
    guest_phone_raw = (payload.get("guest_phone") or "").strip()
    notes = payload.get("notes") or ""

    if not all([stylist_id, salon_service_id, date_str, time_str]):
        return JsonResponse({"ok": False, "error": "missing_fields"}, status=400)

    stylist_service = (
        StylistService.objects
        .select_related("salon_service", "salon_service__service", "stylist", "stylist__salon")
        .filter(stylist_id=stylist_id, salon_service_id=salon_service_id)
        .first()
    )

    if not stylist_service or not stylist_service.salon_service.is_active:
        return JsonResponse({"ok": False, "error": "service_not_available"}, status=404)

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid_datetime"}, status=400)

    tz = pytz.timezone("Asia/Tashkent")
    start_dt = tz.localize(start_dt)
    duration = stylist_service.salon_service.duration
    end_dt = start_dt + duration

    overlap = (
        Appointment.objects
        .filter(
            stylist_id=stylist_id,
            start_time__lt=end_dt,
            end_time__gt=start_dt,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .exists()
    )
    if overlap:
        return JsonResponse({"ok": False, "error": "time_busy"}, status=409)

    normalized_phone = normalize_uzbek_phone(guest_phone_raw)
    customer = None
    if normalized_phone:
        profile = Profile.objects.filter(phone=normalized_phone).select_related("user").first()
        if profile:
            customer = profile.user
        else:
            customer, _ = ensure_guest_account(guest_name or "Гость", normalized_phone)

    appointment_notes = notes.strip()
    if request.telegram_user:
        tg_info = request.telegram_user
        tg_name = tg_info.get("first_name") or ""
        if tg_info.get("last_name"):
            tg_name = f"{tg_name} {tg_info['last_name']}".strip()
        tg_username = tg_info.get("username")
        tg_signature = f"Telegram: {tg_name or tg_username or tg_info.get('id')}"
        appointment_notes = (appointment_notes + "\n\n" + tg_signature).strip()

    with transaction.atomic():
        appointment = Appointment.objects.create(
            stylist=stylist_service.stylist,
            start_time=start_dt,
            end_time=end_dt,
            status=Appointment.Status.PENDING,
            customer=customer,
            guest_name=guest_name,
            guest_phone=normalized_phone,
            notes=appointment_notes,
        )

        AppointmentService.objects.create(
            appointment=appointment,
            stylist_service=stylist_service,
        )

    send_telegram(
        chat_id=stylist_service.stylist.telegram_chat_id,
        username=stylist_service.stylist.telegram_username,
        text=(
            f"📅 Новая запись из Telegram\n"
            f"Клиент: {guest_name or 'Гость'}\n"
            f"Телефон: {normalized_phone or '—'}\n"
            f"Услуга: {stylist_service.salon_service.service.name}\n"
            f"Время: {start_dt.strftime('%d.%m %H:%M')}"
        ),
    )

    return JsonResponse(
        {
            "ok": True,
            "appointment_id": appointment.id,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "status": appointment.status,
        }
    )
