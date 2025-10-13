from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from users.models import Profile
from .models import Service, Stylist, WorkingHour, Appointment, StylistService, Category, BreakPeriod, Salon, City, \
    SalonService, User, Review, StylistLevel, StylistDayOff, AppointmentService


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Профиль'
    fk_name = 'user'


class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInline,)

    # Это нужно, чтобы фильтрация и поиск по профилю работали
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        return super().get_inline_instances(request, obj)

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name',)

class SalonAdminForm(forms.ModelForm):
    class Meta:
        model = Salon
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('photo'):
            raise forms.ValidationError('Добавьте хотя бы одно основное фото салона.')
        return cleaned_data


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    form = SalonAdminForm
    list_display = ('name', 'city', 'status', 'position')
    list_filter = ('city', 'status')
    search_fields = ('name', 'address')
    fieldsets = (
        (None, {
            'fields': (
                'city',
                'name',
                'description',
                'address',
                'latitude',
                'longitude',
                'phone',
                'status',
                'position',
                'type',
            )
        }),
        ('Фото салона', {
            'fields': ('photo', 'photo_2', 'photo_3', 'photo_4', 'photo_5')
        }),
    )

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

@admin.register(SalonService)
class SalonServiceAdmin(admin.ModelAdmin):
    list_display = ('salon', 'service',)
    list_filter = ('salon', 'service')
    search_fields = ('salon__name', 'service__name')

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Stylist)
class StylistAdmin(admin.ModelAdmin):
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    list_display = ('user', 'salon')  # 👈 Добавили салон


class BreakPeriodInline(admin.TabularInline):
    model = BreakPeriod
    extra = 1


@admin.register(WorkingHour)
class WorkingHourAdmin(admin.ModelAdmin):
    inlines = [BreakPeriodInline]
    list_display = ('stylist', 'weekday', 'start_time', 'end_time')
    list_filter = ('stylist', 'weekday')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('get_client_name', 'stylist', 'get_service_name', 'start_time', 'end_time', 'status')
    list_filter = ('stylist', 'status', 'start_time')
    search_fields = ('customer__username', 'stylist__user__username')

    def get_client_name(self, obj):
        if obj.customer:
            full_name = obj.customer.get_full_name()
            return full_name.strip() if full_name.strip() else obj.customer.username
        return f"{obj.guest_name} ({obj.guest_phone})"
    get_client_name.short_description = 'Клиент'

    def get_service_name(self, obj):
        services = []
        queryset = obj.services.select_related(
            'stylist_service__salon_service__service'
        )
        for appointment_service in queryset:
            stylist_service = appointment_service.stylist_service
            if not stylist_service:
                continue
            salon_service = stylist_service.salon_service
            if not salon_service or not salon_service.service:
                continue
            services.append(salon_service.service.name)

        return ', '.join(services) if services else '—'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        elif hasattr(user, 'profile') and user.profile.is_salon_admin:
            return qs.filter(stylist__salon=user.profile.salon)
        return qs.none()

@admin.register(StylistService)
class StylistServiceAdmin(admin.ModelAdmin):
    list_display = ('stylist', 'get_salon', 'get_service', 'price')
    list_filter = ('stylist__salon', 'salon_service__service')
    search_fields = ('stylist__name', 'salon_service__service__name')
    autocomplete_fields = ['stylist', 'salon_service']

    def get_salon(self, obj):
        return obj.stylist.salon  # если у мастера есть связь с салоном
    get_salon.short_description = 'Салон'

    def get_service(self, obj):
        return obj.salon_service.service
    get_service.short_description = 'Услуга'


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('salon', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('user__username', 'salon__name', 'comment')


@admin.register(StylistLevel)
class StylistLevelAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    ordering = ['order']

@admin.register(StylistDayOff)
class StylistDayOffAdmin(admin.ModelAdmin):
    list_display = ('stylist', 'date', 'from_time', 'to_time')  # что показывать в таблице
    list_filter = ('stylist', 'date')  # фильтры справа
    search_fields = ('stylist__name',)  # поиск по имени стилиста, если у тебя есть поле name

    def has_add_permission(self, request):
        return True  # можно добавить из админки

    def has_change_permission(self, request, obj=None):
        return True  # можно редактировать

    def has_delete_permission(self, request, obj=None):
        return True  # можно удалять

@admin.register(AppointmentService)
class AppointmentServiceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'appointment',
        'service_name',
        'stylist_name',
        'get_price',
        'get_duration',
    )
    list_select_related = ('appointment', 'stylist_service', 'stylist_service__salon_service', 'stylist_service__stylist')

    def service_name(self, obj):
        stylist_service = obj.stylist_service
        if (
            stylist_service and
            stylist_service.salon_service and
            stylist_service.salon_service.service
        ):
            return stylist_service.salon_service.service.name
        return '—'
    service_name.short_description = 'Услуга'

    def stylist_name(self, obj):
        stylist_service = obj.stylist_service
        if stylist_service and stylist_service.stylist:
            user = stylist_service.stylist.user
            return user.get_full_name() or user.username
        return '—'

    def get_price(self, obj):
        if not obj.stylist_service:
            return '—'
        return f"{obj.get_price()} сум"
    get_price.short_description = 'Цена'

    def get_duration(self, obj):
        if not obj.stylist_service or not obj.stylist_service.salon_service:
            return '—'
        duration = obj.get_duration()
        total_minutes = int(duration.total_seconds() // 60)
        return f"{total_minutes} мин"
    get_duration.short_description = 'Длительность'

