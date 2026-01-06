from datetime import timedelta
import re

from django.contrib.auth import get_user_model
from django.utils.timezone import localtime
from rest_framework import serializers

from booking.models import (
    Appointment,
    AppointmentService,
    City,
    Salon,
    SalonService,
    Service,
    Stylist,
    StylistService,
)
from users.models import Profile

User = get_user_model()


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["id", "name"]


class SalonSerializer(serializers.ModelSerializer):
    city = CitySerializer()

    class Meta:
        model = Salon
        fields = [
            "id",
            "name",
            "description",
            "address",
            "phone",
            "city",
            "type",
            "slug",
        ]


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "name", "description"]


class SalonServiceSerializer(serializers.ModelSerializer):
    service = ServiceSerializer()

    class Meta:
        model = SalonService
        fields = ["id", "service", "duration", "category", "is_active", "position"]


class StylistSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    level = serializers.StringRelatedField()

    class Meta:
        model = Stylist
        fields = ["id", "full_name", "salon", "level"]

    def get_full_name(self, obj: Stylist) -> str:
        return obj.user.get_full_name() or obj.user.username


class AppointmentServiceSerializer(serializers.ModelSerializer):
    service_name = serializers.SerializerMethodField()

    class Meta:
        model = AppointmentService
        fields = ["id", "service_name", "stylist_service"]

    def get_service_name(self, obj: AppointmentService) -> str:
        if obj.stylist_service and obj.stylist_service.salon_service:
            return obj.stylist_service.salon_service.service.name
        return ""


class AppointmentSerializer(serializers.ModelSerializer):
    services = AppointmentServiceSerializer(many=True, read_only=True)
    stylist = StylistSerializer()
    start_time_local = serializers.SerializerMethodField()
    end_time_local = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "customer",
            "guest_name",
            "guest_phone",
            "stylist",
            "start_time",
            "end_time",
            "start_time_local",
            "end_time_local",
            "status",
            "payment_method",
            "payment_status",
            "notes",
            "services",
            "created_at",
        ]
        read_only_fields = fields

    def get_start_time_local(self, obj: Appointment):
        return localtime(obj.start_time)

    def get_end_time_local(self, obj: Appointment):
        return localtime(obj.end_time)


class RegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, min_length=3)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Пользователь с таким логином уже существует.")
        return value

    def validate_phone(self, value: str) -> str:
        digits = re.sub(r"\D", "", value or "")
        if len(digits) < 9:
            raise serializers.ValidationError("Укажите номер телефона в формате 93-123-45-67.")
        return f"+998{digits[-9:]}"

    def create(self, validated_data):
        phone = validated_data.pop("phone", "")
        user = User.objects.create_user(**validated_data)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.save(update_fields=["phone"])
        return user


class AppointmentCreateSerializer(serializers.Serializer):
    stylist_id = serializers.PrimaryKeyRelatedField(queryset=Stylist.objects.select_related("salon"), source="stylist")
    salon_service_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    start_time = serializers.DateTimeField()
    guest_name = serializers.CharField(required=False, allow_blank=True)
    guest_phone = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=Appointment.PaymentMethod.choices,
        default=Appointment.PaymentMethod.CASH,
    )

    def validate(self, attrs):
        stylist: Stylist = attrs["stylist"]
        salon_service_ids = attrs["salon_service_ids"]
        stylist_services = (
            StylistService.objects
            .filter(stylist=stylist, salon_service_id__in=salon_service_ids)
            .select_related("salon_service", "salon_service__service")
        )

        missing = set(salon_service_ids) - {ss.salon_service_id for ss in stylist_services}
        if missing:
            raise serializers.ValidationError({
                "salon_service_ids": f"Мастер не оказывает услуги с ID: {', '.join(map(str, missing))}",
            })

        total_duration = sum((ss.salon_service.duration for ss in stylist_services), timedelta())
        attrs["stylist_services"] = list(stylist_services)
        attrs["total_duration"] = total_duration
        return attrs