from datetime import datetime, timedelta
from typing import List, Tuple
from decimal import Decimal

import pytz
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.models import (
    Appointment,
    AppointmentService,
    BreakPeriod,
    Stylist,
    StylistDayOff,
    StylistService,
    WorkingHour,
)
from booking.api.serializers import (
    AppointmentCreateSerializer,
    AppointmentSerializer,
    CitySerializer,
    RegistrationSerializer,
    SalonSerializer,
    SalonServiceSerializer,
    StylistSerializer,
)
from booking.models import City, Salon, SalonService
from booking.views import ensure_guest_account, normalize_uzbek_phone
from users.models import Profile

User = get_user_model()


def _normalize_start_time(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value))
    if dt is None:
        raise ValueError("Укажите дату и время начала в формате ISO 8601")

    if timezone.is_naive(dt):
        tz = pytz.timezone(settings.TIME_ZONE)
        dt = tz.localize(dt)
    return dt


def _collect_stylist_services(
    stylist: Stylist, salon_service_ids: List[int]
) -> Tuple[List[StylistService], timedelta, Decimal]:
    stylist_services = (
        StylistService.objects
        .filter(stylist=stylist, salon_service_id__in=salon_service_ids)
        .select_related("salon_service", "salon_service__service")
    )
    missing = set(salon_service_ids) - {ss.salon_service_id for ss in stylist_services}
    if missing:
        raise ValueError(f"Мастер не оказывает услуги с ID: {', '.join(map(str, missing))}")

    total_duration = sum((ss.salon_service.duration for ss in stylist_services), timedelta())
    total_price = sum((ss.price for ss in stylist_services), Decimal("0"))
    return list(stylist_services), total_duration, total_price


def _available_slots_for_stylist(stylist: Stylist, target_date: datetime.date, salon_service_ids: List[int]):
    stylist_services, total_duration, total_price = _collect_stylist_services(stylist, salon_service_ids)

    tz = pytz.timezone(settings.TIME_ZONE)
    working_hours = WorkingHour.objects.filter(stylist=stylist, weekday=target_date.weekday())
    slots = []
    step = timedelta(minutes=15)

    for wh in working_hours:
        start_dt = datetime.combine(target_date, wh.start_time)
        end_dt = datetime.combine(target_date, wh.end_time)
        breaks = BreakPeriod.objects.filter(working_hour=wh)

        while start_dt + total_duration <= end_dt:
            aware_start = tz.localize(start_dt)
            aware_end = aware_start + total_duration

            overlap = (
                Appointment.objects
                .filter(stylist=stylist, start_time__lt=aware_end, end_time__gt=aware_start)
                .exclude(status=Appointment.Status.CANCELLED)
                .exists()
            )

            in_break = any(
                datetime.combine(target_date, b.start_time) < start_dt + total_duration
                and datetime.combine(target_date, b.end_time) > start_dt
                for b in breaks
            )

            in_dayoff = StylistDayOff.objects.filter(
                stylist=stylist,
                date=target_date,
            ).filter(
                Q(from_time__isnull=True, to_time__isnull=True)
                | Q(from_time__lt=(start_dt + total_duration).time(), to_time__gt=start_dt.time())
            ).exists()

            if not overlap and not in_break and not in_dayoff:
                slots.append(
                    {
                        "start": aware_start.isoformat(),
                        "end": aware_end.isoformat(),
                        "duration_minutes": int(total_duration.total_seconds() // 60),
                        "total_price": float(total_price),
                        "services": [ss.salon_service_id for ss in stylist_services],
                    }
                )

            start_dt += step

    return slots


def _validate_slot_constraints(stylist: Stylist, start_time: datetime, total_duration: timedelta) -> None:
    tz = pytz.timezone(settings.TIME_ZONE)
    local_start = start_time.astimezone(tz)
    local_end = local_start + total_duration

    working_hours = list(WorkingHour.objects.filter(stylist=stylist, weekday=local_start.weekday()))
    window = next(
        (
            wh for wh in working_hours
            if wh.start_time <= local_start.time() and wh.end_time >= local_end.time()
        ),
        None,
    )
    if not window:
        raise ValueError("Выбранное время вне рабочего графика мастера.")

    breaks = BreakPeriod.objects.filter(working_hour=window)
    in_break = any(
        datetime.combine(local_start.date(), b.start_time) < local_start.replace(tzinfo=None) + total_duration
        and datetime.combine(local_start.date(), b.end_time) > local_start.replace(tzinfo=None)
        for b in breaks
    )
    if in_break:
        raise ValueError("Это время попадает в перерыв мастера.")

    in_dayoff = StylistDayOff.objects.filter(
        stylist=stylist,
        date=local_start.date(),
    ).filter(
        Q(from_time__isnull=True, to_time__isnull=True)
        | Q(from_time__lt=local_end.time(), to_time__gt=local_start.time())
    ).exists()
    if in_dayoff:
        raise ValueError("Мастер недоступен в выбранное время.")

    overlap = (
        Appointment.objects
        .filter(stylist=stylist, start_time__lt=local_end.astimezone(pytz.UTC), end_time__gt=local_start.astimezone(pytz.UTC))
        .exclude(status=Appointment.Status.CANCELLED)
        .exists()
    )
    if overlap:
        raise ValueError("На это время уже есть запись.")


class RegistrationView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        headers = self.get_success_headers(serializer.data)
        return Response({"token": token.key}, status=status.HTTP_201_CREATED, headers=headers)


class CustomObtainAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        token = Token.objects.get(key=response.data['token'])
        return Response({"token": token.key})


class CityListView(generics.ListAPIView):
    queryset = City.objects.all()
    serializer_class = CitySerializer


class SalonListView(generics.ListAPIView):
    queryset = Salon.objects.active().select_related("city")
    serializer_class = SalonSerializer


class SalonServiceListView(generics.ListAPIView):
    serializer_class = SalonServiceSerializer

    def get_queryset(self):
        salon_id = self.kwargs.get("pk")
        return (
            SalonService.objects
            .filter(salon_id=salon_id, is_active=True, service__is_active=True)
            .select_related("service", "category")
            .order_by("position")
        )


class StylistListView(generics.ListAPIView):
    serializer_class = StylistSerializer

    def get_queryset(self):
        qs = Stylist.objects.select_related("user", "salon", "level")
        salon_id = self.request.query_params.get("salon")
        if salon_id:
            qs = qs.filter(salon_id=salon_id)
        return qs


class AvailableSlotsView(APIView):
    def get(self, request, stylist_id: int):
        try:
            stylist = Stylist.objects.get(pk=stylist_id)
        except Stylist.DoesNotExist:
            return Response({"detail": "Мастер не найден."}, status=status.HTTP_404_NOT_FOUND)

        date_str = request.query_params.get("date")
        services_param = request.query_params.get("services")

        if not date_str or not services_param:
            return Response({"detail": "Укажите дату и список услуг."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response({"detail": "Неверный формат даты. Используйте YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            salon_service_ids = [int(part) for part in services_param.split(",") if part]
        except ValueError:
            return Response({"detail": "Список услуг должен содержать ID через запятую."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            slots = _available_slots_for_stylist(stylist, target_date, salon_service_ids)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"stylist": stylist_id, "date": target_date.isoformat(), "slots": slots})


class AppointmentListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Требуется аутентификация."}, status=status.HTTP_401_UNAUTHORIZED)

        appointments = (
            Appointment.objects
            .filter(customer=request.user)
            .select_related("stylist", "stylist__user", "stylist__level")
            .prefetch_related("services", "services__stylist_service", "services__stylist_service__salon_service")
            .order_by("-start_time")
        )
        data = AppointmentSerializer(appointments, many=True).data
        return Response(data)

    def post(self, request):
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stylist: Stylist = serializer.validated_data["stylist"]
        stylist_services: List[StylistService] = serializer.validated_data["stylist_services"]
        total_duration: timedelta = serializer.validated_data["total_duration"]
        start_time_value = serializer.validated_data["start_time"]

        try:
            start_time = _normalize_start_time(start_time_value)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        end_time = start_time + total_duration

        try:
            _validate_slot_constraints(stylist, start_time, total_duration)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        guest_name = serializer.validated_data.get("guest_name", "").strip()
        guest_phone_raw = serializer.validated_data.get("guest_phone", "").strip()
        notes = serializer.validated_data.get("notes", "")
        payment_method = serializer.validated_data.get("payment_method")

        customer = request.user if request.user.is_authenticated else None
        credentials_data = None

        if customer:
            if guest_phone_raw:
                normalized_phone = normalize_uzbek_phone(guest_phone_raw)
                profile, _ = Profile.objects.get_or_create(user=customer)
                profile.phone = normalized_phone
                profile.save(update_fields=["phone"])
        else:
            if not guest_name or not guest_phone_raw:
                return Response(
                    {"detail": "Укажите имя и телефон для гостевой записи или выполните вход."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            normalized_phone = normalize_uzbek_phone(guest_phone_raw)
            customer, credentials_data = ensure_guest_account(guest_name, normalized_phone)
            guest_name = ""
            guest_phone_raw = ""

        with transaction.atomic():
            appointment = Appointment.objects.create(
                customer=customer,
                guest_name=guest_name,
                guest_phone=guest_phone_raw,
                stylist=stylist,
                start_time=start_time,
                end_time=end_time,
                notes=notes,
                payment_method=payment_method,
            )

            for ss in stylist_services:
                AppointmentService.objects.create(
                    appointment=appointment,
                    stylist_service=ss,
                )

        return Response(
            {
                "appointment": AppointmentSerializer(appointment).data,
                "guest_credentials": credentials_data,
            },
            status=status.HTTP_201_CREATED,
        )