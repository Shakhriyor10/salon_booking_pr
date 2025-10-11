from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, TemplateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.middleware.csrf import get_token
from users.models import Profile
from .form import (
    ReviewForm,
    StylistCreationForm,
    SalonServiceForm,
    SalonServiceUpdateForm,
    StylistUpdateForm,
)
from .models import Service, Stylist, Appointment, StylistService, Category, BreakPeriod, WorkingHour, Salon, \
    SalonService, City, AppointmentService, StylistDayOff, WEEKDAYS
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.timezone import make_aware
from django.contrib import messages
from booking.telebot import send_telegram
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.utils.timezone import now
from django.template.context_processors import csrf
from django.db.models import Count, Sum, DecimalField, Prefetch, F
from django.db.models.functions import Cast, TruncDate, Coalesce, Lower, Upper
from datetime import date, datetime
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import datetime as dt
from django.views import View
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
import re
from django.utils.timezone import now, localtime, make_aware, timedelta
from django.views.decorators.http import require_POST
from django.http import HttpResponseForbidden
import pytz
from django.db.models import Avg, Q
from django.db.models.deletion import ProtectedError

PHONE_RE = re.compile(r'^\+?\d{9,15}$')


def format_duration(duration):
    """Format a timedelta into a human-readable string."""
    if not duration:
        return "0 мин"

    total_minutes = int(duration.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)

    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes or not parts:
        parts.append(f"{minutes} мин")

    return " ".join(parts)

class HomePageView(ListView):
    model = Salon
    template_name = 'salon.html'
    context_object_name = 'salons'

    @staticmethod
    def _get_user_salon(user):
        if not getattr(user, 'is_authenticated', False):
            return None

        profile = getattr(user, 'profile', None)
        if profile and getattr(profile, 'is_salon_admin', False) and profile.salon:
            return profile.salon

        try:
            stylist_profile = user.stylist_profile
        except ObjectDoesNotExist:
            stylist_profile = None

        if stylist_profile and getattr(stylist_profile, 'salon', None):
            return stylist_profile.salon

        return None

    def get(self, request, *args, **kwargs):
        salon = self._get_user_salon(request.user)
        if salon:
            salon_url = salon.get_absolute_url()
            if request.path != salon_url:
                return redirect(salon_url)

        get_params = request.GET.copy()
        if 'services' in get_params:
            get_params.pop('services')
            return redirect(f"{request.path}?{get_params.urlencode()}" if get_params else request.path)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Salon.objects.filter(status=True).order_by('position')
        queryset = queryset.annotate(avg_rating=Avg('reviews__rating'))

        # Фильтр по типу (male, female, both)
        salon_type = self.request.GET.get('type')
        if salon_type in ['male', 'female', 'both']:
            queryset = queryset.filter(type=salon_type)

        # Фильтр по рейтингу
        rating = self.request.GET.get('rating')
        if rating:
            try:
                rating = float(rating)
                queryset = queryset.filter(avg_rating__gte=rating)
            except ValueError:
                pass

        # Поиск: сначала по точному совпадению услуги, потом по названию салона
        search_type = self.request.GET.get('search_type')
        search_value = self.request.GET.get('search_value', '').strip()

        if search_type == 'service' and search_value:
            queryset = queryset.filter(
                salon_services__service__name__iexact=search_value,
                salon_services__is_active=True,
                salon_services__service__is_active=True
            )
        elif search_type == 'salon' and search_value:
            queryset = queryset.filter(name__icontains=search_value)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        for salon in context['salons']:
            rating = salon.average_rating() or 0
            rounded_rating = round(rating * 2) / 2
            full = int(rounded_rating)
            half = (rounded_rating - full) == 0.5
            empty = 5 - full - (1 if half else 0)
            salon.stars = {'full': range(full), 'half': half, 'empty': range(empty)}
            salon.rating_value = round(rating, 1)

        context['types'] = ['male', 'female', 'both']
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_rating'] = self.request.GET.get('rating', '')
        context['selected_service'] = self.request.GET.get('service', '')
        return context


def autocomplete_search(request):
    q = request.GET.get('q', '').strip().lower()
    results = []

    if len(q) >= 2:
        salon_services = (
            SalonService.objects.select_related('service', 'salon')
            .filter(service__name__icontains=q)
        )

        seen_services = set()
        for ss in salon_services:
            label = ss.service.name
            gender = ss.salon.get_type_display()  # теперь работает правильно
            key = (label.lower(), gender)

            if key not in seen_services:
                results.append({
                    "type": "service",
                    "label": label,
                    "gender": gender.lower()  # чтобы отображалось как (муж), (жен) и т.д.
                })
                seen_services.add(key)

        # Салоны
        salons = Salon.objects.all().values_list('name', flat=True)
        filtered_salons = [s for s in salons if q in s.lower()]
        results += [{"type": "salon", "label": name} for name in filtered_salons]

    return JsonResponse(results[:30], safe=False)

# class ServiceSearchView(View):
#     def get(self, request):
#         q = request.GET.get('q', '').strip().lower()
#         if len(q) >= 2:
#             services = Service.objects.all().values_list('name', flat=True)
#             filtered_services = [s for s in services if q in s.lower()]
#             return JsonResponse(filtered_services[:30], safe=False)
#         return JsonResponse([], safe=False)


class SalonDetailView(DetailView):
    model = Salon
    template_name = 'salon_detail.html'
    context_object_name = 'salon'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        salon = self.object

        # Услуги по салону
        all_services = SalonService.objects.filter(
            salon=salon,
            is_active=True
        ).select_related('service', 'category').order_by('position')

        # Получаем категории, используемые в этом салоне
        category_ids = all_services.exclude(category__isnull=True).values_list('category_id', flat=True).distinct()
        categories = Category.objects.filter(id__in=category_ids)

        # Группировка по категориям
        for category in categories:
            category.services_in_category = [
                s for s in all_services if s.category_id == category.id
            ]

        # Услуги без категории
        uncategorized_services = [
            s for s in all_services if s.category_id is None
        ]

        # Рейтинг
        rating = salon.average_rating() or 0
        rounded_rating = round(rating * 2) / 2
        full_stars = int(rounded_rating)
        has_half_star = (rounded_rating - full_stars) == 0.5
        empty_stars = 5 - full_stars - (1 if has_half_star else 0)

        # Контекст
        context['stars'] = {
            'full': range(full_stars),
            'half': has_half_star,
            'empty': range(empty_stars)
        }
        context['reviews'] = salon.reviews.order_by('-created_at')[:10]
        context['review_form'] = ReviewForm()
        context['average_rating'] = rating
        context['categories'] = categories
        context['uncategorized_services'] = uncategorized_services
        stylists = (
            salon.stylists.select_related('user', 'level')
            .annotate(
                active_service_count=Count(
                    'stylist_services',
                    filter=Q(
                        stylist_services__salon_service__salon=salon,
                        stylist_services__salon_service__is_active=True,
                        stylist_services__salon_service__service__is_active=True,
                    ),
                    distinct=True,
                ),
                working_interval_count=Count('working_hours', distinct=True),
            )
            .filter(
                active_service_count__gt=0,
                working_interval_count__gt=0,
            )
            .prefetch_related(
                Prefetch(
                    'stylist_services',
                    queryset=StylistService.objects.filter(
                        salon_service__salon=salon,
                        salon_service__is_active=True,
                        salon_service__service__is_active=True,
                    ).select_related('salon_service__service'),
                    to_attr='salon_services_for_display'
                )
            )
            .order_by('user__first_name', 'user__last_name', 'user__username')
        )
        context['stylists'] = stylists
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")  # Перенаправление на логин

        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.salon = self.object
            review.user = request.user
            review.save()
            return redirect('salon_detail', pk=self.object.pk, slug=self.object.slug)

        return self.get(request, *args, **kwargs)

class CategoryServicesView(View):
    def get(self, request, pk):
        salon_id = request.GET.get('salon')
        salon = get_object_or_404(Salon, id=salon_id)
        category = get_object_or_404(Category, id=pk)  # исправлено здесь

        services = SalonService.objects.filter(
            salon=salon,
            category=category,
            is_active=True
        ).order_by('position')  # сортировка по позиции

        return render(request, 'category_services.html', {
            'salon': salon,
            'category': category,
            'services': services
        })

class ServiceListView(ListView):
    model = Service
    template_name = 'services.html'
    context_object_name = 'services'

    def get_queryset(self):
        return Service.objects.filter(is_active=True, category__isnull=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        return context


# def services_by_category(request, category_id):
#     category = get_object_or_404(Category, id=category_id)
#     services = Service.objects.filter(category=category, is_active=True)
#     return render(request, 'services_by_category.html', {
#         'category': category,
#         'services': services
#     })


class StylistListView(ListView):
    model = Stylist
    template_name = 'stylists.html'
    context_object_name = 'stylists'


class StylistDetailView(DetailView):
    model = Stylist
    template_name = 'stylist_detail.html'
    context_object_name = 'stylist'
    pk_url_kwarg = 'stylist_id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stylist = self.get_object()

        date_str = self.request.GET.get('date')
        if date_str:
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                date = timezone.now().date()
        else:
            date = timezone.now().date()

        weekday = date.weekday()
        slots = []

        for wh in stylist.working_hours.filter(weekday=weekday):
            start = make_aware(datetime.combine(date, wh.start_time))
            end = make_aware(datetime.combine(date, wh.end_time))
            current = start

            while current + timedelta(minutes=15) <= end:
                overlap = Appointment.objects.filter(
                    stylist=stylist,
                    start_time__lt=current + timedelta(minutes=15),
                    end_time__gt=current
                ).exists()
                if not overlap and current >= timezone.now():
                    slots.append(current)
                current += timedelta(minutes=15)

        context['slots'] = slots
        context['selected_date'] = date
        return context



class AppointmentCreateView(View):
    success_url = reverse_lazy('home')

    def post(self, request, *args, **kwargs):
        stylist_id = request.POST.get('stylist_id')
        service_ids = request.POST.getlist('service_ids')  # список ID услуг из корзины
        time_str = request.POST.get('slot')

        if not (stylist_id and service_ids and time_str):
            messages.error(request, 'Не хватает данных для записи.')
            return redirect('home')

        stylist = get_object_or_404(Stylist, id=stylist_id)
        stylist_services = list(StylistService.objects.select_related('salon_service').filter(
            stylist=stylist,
            salon_service__service_id__in=service_ids
        ))

        if len(stylist_services) != len(service_ids):
            messages.error(request, 'Некоторые выбранные услуги не найдены у мастера.')
            return redirect('home')

        try:
            start_time = make_aware(datetime.strptime(time_str, "%Y-%m-%dT%H:%M"))
        except ValueError:
            messages.error(request, 'Неверный формат даты/времени.')
            return redirect('home')

        total_duration = sum((ss.salon_service.duration for ss in stylist_services), timedelta())
        end_time = start_time + total_duration

        # Проверка занятости
        if Appointment.objects.filter(
            stylist=stylist,
            start_time__lt=end_time,
            end_time__gt=start_time
        ).exists():
            messages.error(request, 'Извините, мастер уже занят в это время.')
            return redirect('home')

        # Проверка рабочего времени
        start_time_local = localtime(start_time)
        end_time_local = localtime(end_time)
        weekday = start_time_local.weekday()

        wh = WorkingHour.objects.filter(
            stylist=stylist,
            weekday=weekday,
            start_time__lte=start_time_local.time(),
            end_time__gte=end_time_local.time()
        ).first()

        if not wh:
            messages.error(request, 'Выбранное время не входит в рабочее время мастера.')
            return redirect('home')

        # Перерывы
        in_break = BreakPeriod.objects.filter(
            working_hour=wh,
            start_time__lt=end_time_local.time(),
            end_time__gt=start_time_local.time()
        ).exists()

        if in_break:
            messages.error(request, 'Это время попадает в перерыв мастера.')
            return redirect('home')

        # Клиент
        guest_name = ''
        guest_phone = ''
        customer = None

        if request.user.is_authenticated:
            customer = request.user
            if not hasattr(customer, 'profile') or not customer.profile.phone:
                guest_phone = request.POST.get('guest_phone', '').strip()
                if not PHONE_RE.match(guest_phone):
                    messages.error(request, 'Укажите корректный номер телефона.')
                    return redirect('home')

                if not hasattr(customer, 'profile'):
                    Profile.objects.create(user=customer, phone=guest_phone)
                else:
                    customer.profile.phone = guest_phone
                    customer.profile.save(update_fields=['phone'])
        else:
            guest_name = request.POST.get('guest_name', '').strip()
            guest_phone = request.POST.get('guest_phone', '').strip()

            if not guest_name or not PHONE_RE.match(guest_phone):
                messages.error(request, 'Укажите имя и корректный номер телефона.')
                return redirect('home')

        # Создаём запись
        appointment = Appointment.objects.create(
            customer=customer,
            guest_name=guest_name,
            guest_phone=guest_phone,
            stylist=stylist,
            start_time=start_time,
            end_time=end_time
        )

        for ss in stylist_services:
            AppointmentService.objects.create(
                appointment=appointment,
                stylist_service=ss
            )

        # Telegram уведомление мастеру
        phone_txt = (
            customer.profile.phone if customer and hasattr(customer, 'profile') else guest_phone
        )
        client_repr = (
            (customer.get_full_name() or customer.username) if customer else guest_name
        ) + f" ({phone_txt})"

        service_list = ", ".join(ss.salon_service.service.name for ss in stylist_services)

        msg = (
            f"<b>📝 Новая запись!</b>\n"
            f"👤 Клиент: {client_repr}\n"
            f"💇 Услуги: {service_list}\n"
            f"🕒 Время: {start_time.strftime('%d.%m.%Y %H:%M')}"
        )
        send_telegram(
            chat_id=stylist.telegram_chat_id,
            username=stylist.telegram_username,
            text=msg
        )

        messages.success(request, 'Запись успешно создана! ✂️')
        if request.user.is_authenticated:
            return redirect('my_appointments')
        return redirect(self.success_url)


def service_booking(request):
    raw_service_ids = request.GET.getlist("services")
    salon_id = request.GET.get('salon')
    stylist_id = request.GET.get('stylist')

    if not salon_id:
        return render(request, 'error.html', {"message": "Салон не указан."})

    salon = get_object_or_404(Salon, id=salon_id)

    today = now().date()
    max_date = today + timedelta(days=14)
    date_str = request.GET.get('date')
    find_next_requested = request.GET.get('find_next') == '1'
    next_slot_not_found = False

    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today
    except (ValueError, TypeError):
        selected_date = today

    selected_date = min(max(selected_date, today), max_date)
    try:
        selected_service_ids = list(dict.fromkeys(int(sid) for sid in raw_service_ids))
    except (TypeError, ValueError):
        return render(request, 'error.html', {"message": "Некорректные ID услуг."})

    services_qs = Service.objects.filter(id__in=selected_service_ids)
    services_map = {service.id: service for service in services_qs}
    if selected_service_ids and len(services_map) != len(selected_service_ids):
        return render(request, 'error.html', {"message": "Выбранные услуги не найдены."})

    ordered_services = [services_map[sid] for sid in selected_service_ids]

    services_with_actions = []
    for service in ordered_services:
        query_copy = request.GET.copy()
        current_services = [value for value in query_copy.getlist('services') if value]
        filtered_services = [sid for sid in current_services if sid != str(service.id)]

        if filtered_services:
            query_copy.setlist('services', filtered_services)
        else:
            try:
                del query_copy['services']
            except KeyError:
                pass

        services_with_actions.append({
            'service': service,
            'remove_query': query_copy.urlencode(),
        })

    salon_service_options = list(
        Service.objects.filter(
            salon_services__salon=salon,
            salon_services__is_active=True,
            is_active=True,
        )
        .order_by(Lower('name'))
        .distinct()
    )

    selected_stylist = None
    stylist_available_services = []
    removed_services = []

    if stylist_id:
        try:
            stylist_id = int(stylist_id)
        except (TypeError, ValueError):
            return render(request, 'error.html', {"message": "Некорректный идентификатор мастера."})

        selected_stylist = get_object_or_404(Stylist, id=stylist_id, salon=salon)
        stylist_available_services = (
            StylistService.objects.filter(
                stylist=selected_stylist,
                salon_service__salon=salon,
                salon_service__is_active=True,
                salon_service__service__is_active=True,
            )
            .select_related('salon_service__service')
            .order_by(Lower('salon_service__service__name'))
        )

        available_ids = {ss.salon_service.service_id for ss in stylist_available_services}
        removed_ids = [sid for sid in selected_service_ids if sid not in available_ids]

        if removed_ids:
            removed_services = [services_map[sid] for sid in removed_ids if sid in services_map]
            selected_service_ids = [sid for sid in selected_service_ids if sid in available_ids]
            ordered_services = [service for service in ordered_services if service.id in available_ids]

    total_price = Decimal('0')
    total_duration = timedelta()
    stylist_slots = []
    selected_stylist_slot = None
    next_available_slot = None
    auto_selected_slot = request.GET.get('auto_slot')
    auto_selected_slot_dt = None

    stylist_to_services = defaultdict(list)

    if selected_service_ids:
        filters = {
            'salon_service__salon': salon,
            'salon_service__service_id__in': selected_service_ids,
            'salon_service__is_active': True,
            'salon_service__service__is_active': True,
        }

        if selected_stylist:
            filters['stylist'] = selected_stylist

        all_stylist_services = (
            StylistService.objects.filter(**filters)
            .select_related('stylist', 'salon_service', 'salon_service__service')
        )

        for ss in all_stylist_services:
            stylist_to_services[ss.stylist_id].append(ss)

        def build_slot_entry(stylist_id, target_date):
            services_list = stylist_to_services.get(stylist_id)
            if not services_list:
                return None

            stylist = services_list[0].stylist
            matched_ids = {s.salon_service.service_id for s in services_list}
            if not set(selected_service_ids).issubset(matched_ids):
                return None

            relevant_services = [
                s for s in services_list if s.salon_service.service_id in selected_service_ids
            ]

            ss_price = sum((s.price for s in relevant_services), Decimal('0'))
            ss_duration = sum(
                (s.salon_service.duration for s in relevant_services), timedelta()
            )

            if ss_duration.total_seconds() <= 0:
                return None

            weekday_local = target_date.weekday()
            slots = []
            for wh in stylist.working_hours.filter(weekday=weekday_local):
                start = make_aware(datetime.combine(target_date, wh.start_time))
                end = make_aware(datetime.combine(target_date, wh.end_time))
                current = start

                while current + ss_duration <= end:
                    overlap = Appointment.objects.filter(
                        stylist=stylist,
                        start_time__lt=current + ss_duration,
                        end_time__gt=current
                    ).exists()

                    in_break = BreakPeriod.objects.filter(
                        working_hour=wh,
                        start_time__lt=(current + ss_duration).time(),
                        end_time__gt=current.time()
                    ).exists()

                    in_dayoff = StylistDayOff.objects.filter(
                        stylist=stylist,
                        date=target_date
                    ).filter(
                        Q(from_time__isnull=True, to_time__isnull=True)
                        | Q(from_time__lt=(current + ss_duration).time(), to_time__gt=current.time())
                    ).exists()

                    if not overlap and not in_break and not in_dayoff and current >= now():
                        slots.append(current)

                    current += timedelta(minutes=15)

            if not slots:
                return None

            return {
                'stylist': stylist,
                'services': relevant_services,
                'price': ss_price,
                'duration': ss_duration,
                'duration_display': format_duration(ss_duration),
                'slots': slots
            }

        for stylist_id in stylist_to_services:
            slot_entry = build_slot_entry(stylist_id, selected_date)
            if not slot_entry:
                continue

            stylist_slots.append(slot_entry)

            stylist = slot_entry['stylist']
            if (selected_stylist and stylist.id == selected_stylist.id) or not selected_stylist:
                total_price = slot_entry['price']
                total_duration = slot_entry['duration']

            if selected_stylist and stylist.id == selected_stylist.id:
                selected_stylist_slot = slot_entry

        if auto_selected_slot and selected_stylist_slot:
            for slot in selected_stylist_slot.get('slots', []):
                if slot.strftime('%Y-%m-%dT%H:%M') == auto_selected_slot:
                    auto_selected_slot_dt = slot
                    break

        if stylist_slots:
            stylist_slots.sort(key=lambda entry: entry['slots'][0])

        if selected_stylist and (not selected_stylist_slot or not selected_stylist_slot.get('slots')):
            search_date = selected_date + timedelta(days=1)
            while search_date <= max_date:
                slot_entry = build_slot_entry(selected_stylist.id, search_date)
                if slot_entry:
                    next_available_slot = {
                        'date': search_date,
                        'slot': slot_entry['slots'][0],
                        'price': slot_entry['price'],
                        'duration': slot_entry['duration'],
                    }
                    break

                search_date += timedelta(days=1)

        if find_next_requested and next_available_slot:
            query_params = request.GET.copy()
            if 'find_next' in query_params:
                del query_params['find_next']
            query_params['date'] = next_available_slot['date'].isoformat()
            query_params['auto_slot'] = next_available_slot['slot'].strftime('%Y-%m-%dT%H:%M')
            redirect_url = f"{reverse('service_booking')}?{query_params.urlencode()}"
            return redirect(redirect_url)
        elif find_next_requested and not next_available_slot:
            next_slot_not_found = True

    context = {
        'services': ordered_services,
        'salon': salon,
        'selected_date': selected_date,
        'stylist_slots': stylist_slots,
        'today': today,
        'max_date': max_date,
        'service_ids': selected_service_ids,
        'selected_service_ids': selected_service_ids,
        'services_list': selected_service_ids,
        'total_price': total_price,
        'total_duration': total_duration,
        'selected_stylist': selected_stylist,
        'stylist_available_services': stylist_available_services,
        'removed_services': removed_services,
        'selected_stylist_slot': selected_stylist_slot,
        'next_available_slot': next_available_slot,
        'auto_selected_slot': auto_selected_slot,
        'auto_selected_slot_dt': auto_selected_slot_dt,
        'next_slot_not_found': next_slot_not_found,
        'salon_service_options': salon_service_options,
        'services_with_actions': services_with_actions,
    }

    template_name = 'service_booking.html'
    if not selected_stylist:
        template_name = 'service_booking_services.html'

    return render(request, template_name, context)

def group_appointments_by_date(appointments):
    grouped = defaultdict(list)
    for a in appointments:
        date_key = a.start_time.date()  # ← сохраняем объект date, а не строку
        grouped[date_key].append(a)
    return dict(sorted(grouped.items(), reverse=True))  # свежие даты сверху

@login_required
def dashboard_view(request):
    today = now().date()
    yesterday = today - timedelta(days=1)
    user = request.user
    profile = getattr(user, 'profile', None)

    # 🔐 Проверка доступа
    if not user.is_superuser and not (profile and profile.is_salon_admin and profile.salon):
        return HttpResponseForbidden("Недостаточно прав для доступа к дашборду.")

    # 🔽 Базовый queryset
    appointments = (
        Appointment.objects
        .select_related("customer", "stylist")  # оставляем только существующие связи
        .filter(start_time__date__gte=yesterday)
        .order_by("-start_time")
    )

    # 🔽 Фильтрация по салону
    if not user.is_superuser:
        appointments = appointments.filter(stylist__salon=profile.salon)

    # 📊 Группировка и расчёты
    grouped_appointments = group_appointments_by_date(appointments)
    cash_total = sum(a.get_total_price() for a in appointments if a.status == Appointment.Status.DONE)

    cash_today = sum(
        a.get_total_price()
        for a in appointments
        if a.status == Appointment.Status.DONE and a.start_time.date() == today
    )

    context = {
        "grouped_appointments": grouped_appointments,
        "cash_total": cash_total,
        "cash_today": cash_today,
        "today": today,
    }

    return render(request, "dashboard.html", context)


@login_required
@require_GET
def dashboard_ajax(request):
    today = now().date()
    yesterday = today - timedelta(days=1)
    user = request.user
    profile = getattr(user, 'profile', None)

    # 🔒 Фильтрация по салону, как в основном dashboard_view
    appointments = (
        Appointment.objects
        .select_related("customer", "stylist")  # оставляем только существующие связи
        .filter(start_time__date__gte=yesterday)
        .order_by("-start_time")
    )

    if not user.is_superuser:
        if profile and profile.is_salon_admin and profile.salon:
            appointments = appointments.filter(stylist__salon=profile.salon)
        else:
            return JsonResponse({"html": ""})  # не показываем ничего

    grouped_appointments = group_appointments_by_date(appointments)

    context = {
        "grouped_appointments": grouped_appointments,
        "csrf_token": get_token(request),
    }

    html = render_to_string("partials/appointments_table_rows.html", context)
    return JsonResponse({"html": html})


@method_decorator(login_required, name="dispatch")
class AppointmentActionView(View):
    def post(self, request, pk):
        appointment = get_object_or_404(Appointment, pk=pk)
        user = request.user

        # 🔒 Проверка прав
        is_super = user.is_superuser
        is_salon_admin = hasattr(user, "profile") and user.profile.is_salon_admin
        owns_appointment = is_salon_admin and user.profile.salon == appointment.stylist.salon

        if not is_super and not owns_appointment:
            return HttpResponseForbidden("Недостаточно прав для изменения этой записи.")

        # Действия
        action = request.POST.get("action")

        if action == "confirm":
            appointment.status = Appointment.Status.CONFIRMED
            appointment.save(update_fields=["status"])
            messages.success(request, "Запись подтверждена ✅")

        elif action == "cancel":
            appointment.delete()
            messages.warning(request, "Запись отменена и удалена ❌")
            return redirect("dashboard")

        elif action == "done":
            appointment.status = Appointment.Status.DONE
            appointment.save(update_fields=["status"])
            messages.success(request, "Запись отмечена как выполненная ✂️")

        else:
            messages.error(request, "Недопустимое действие.")

        return redirect("dashboard")

@method_decorator(login_required, name="dispatch")
class ReportView(View):
    template_name = "reports.html"

    def get(self, request):
        tz = timezone.get_current_timezone()

        def parse_date(raw):
            try:
                return dt.datetime.strptime(raw, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                return None

        start_raw = request.GET.get("start")
        end_raw = request.GET.get("end")
        start_date = parse_date(start_raw)
        end_date = parse_date(end_raw)

        qs = Appointment.objects.select_related(
            "stylist", "stylist__user"
        ).prefetch_related(
            "services__stylist_service__salon_service__service"
        ).filter(status="D")

        profile = getattr(request.user, "profile", None)
        if not request.user.is_superuser:
            if not (profile and profile.is_salon_admin and profile.salon):
                return render(request, "403.html", status=403)
            qs = qs.filter(stylist__salon=profile.salon)

        if start_date:
            start_dt = dt.datetime.combine(start_date, dt.time.min).replace(tzinfo=tz)
            qs = qs.filter(start_time__gte=start_dt)
        if end_date:
            end_dt = dt.datetime.combine(end_date, dt.time.max).replace(tzinfo=tz)
            qs = qs.filter(start_time__lte=end_dt)

        # СБОР ЦЕН: пары (stylist_id, service_id)
        pairs = set()
        for a in qs:
            for s in a.services.all():
                ss = s.stylist_service
                if ss and ss.salon_service:
                    pairs.add((ss.stylist_id, ss.salon_service.service_id))

        price_map = {
            (s.stylist_id, s.salon_service.service_id): s.price
            for s in StylistService.objects.filter(
                stylist_id__in=[p[0] for p in pairs],
                salon_service__service_id__in=[p[1] for p in pairs]
            )
        }

        stats = defaultdict(lambda: {
            "clients": 0,
            "revenue": Decimal("0"),
            "stylists": defaultdict(lambda: Decimal("0"))
        })
        overall_stats = defaultdict(lambda: {"clients": 0, "revenue": Decimal("0")})

        for ap in qs:
            day = timezone.localtime(ap.start_time).date()
            for s in ap.services.all():
                ss = s.stylist_service
                if ss and ss.salon_service:
                    service_id = ss.salon_service.service_id
                    price = price_map.get((ss.stylist_id, service_id), Decimal("0"))
                    name = ap.stylist.user.get_full_name() or str(ap.stylist)

                    stats[day]["clients"] += 1
                    stats[day]["revenue"] += price
                    stats[day]["stylists"][name] += price

                    overall_stats[name]["clients"] += 1
                    overall_stats[name]["revenue"] += price

        daily_stats = [
            {
                "day": day,
                "clients": data["clients"],
                "revenue": data["revenue"],
                "stylists": dict(data["stylists"]),
            }
            for day, data in sorted(stats.items(), reverse=True)
        ]

        total_revenue = sum(d["revenue"] for d in daily_stats)
        total_clients = sum(d["clients"] for d in daily_stats)

        paginator = Paginator(daily_stats, 5)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        return render(request, self.template_name, {
            "page_obj": page_obj,
            "daily_stats": daily_stats,
            "total_revenue": total_revenue,
            "overall_stats": dict(overall_stats),
            "total_clients": total_clients,
        })

@login_required(login_url='login')
def my_appointments(request):
    appointments = (
        Appointment.objects
        .select_related("stylist")
        .prefetch_related("services__stylist_service__salon_service__service")  # подгружаем услуги
        .filter(customer=request.user)
        .order_by("-start_time")
    )
    return render(request, "my_appointments.html", {
        "appointments": appointments,
        "now": now(),
    })

@login_required
def cancel_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, customer=request.user)

    if appointment.status not in [Appointment.Status.DONE]:
        appointment.delete()
        messages.success(request, "Запись успешно отменена и удалена.")
    else:
        messages.error(request, "Нельзя отменить выполненную запись.")

    return redirect('my_appointments')



@login_required
def stylist_dashboard(request):
    try:
        stylist = request.user.stylist_profile
    except Stylist.DoesNotExist:
        return render(request, "no_stylist_profile.html")

    today = now().date()
    yesterday = today - timedelta(days=1)

    # Загружаем все записи этого мастера
    appointments = (
        Appointment.objects
        .filter(stylist=stylist, start_time__date__gte=yesterday)
        .select_related("customer")
        .prefetch_related(
            Prefetch(
                "services",  # <-- правильное имя связи
                queryset=AppointmentService.objects.select_related(
                    "stylist_service__salon_service__service"
                )
            )
        )
        .order_by("-start_time")
    )

    grouped_appointments = group_appointments_by_date(appointments)

    today_appointments = appointments.filter(start_time__date=today, status='D')
    total_cash = Decimal("0")

    for a in today_appointments:
        for service in a.services.all():
            try:
                total_cash += service.stylist_service.price
            except:
                continue

    context = {
        "grouped_appointments": grouped_appointments,
        "today": today,
        "total_cash": total_cash,
    }

    return render(request, "stylist_dashboard.html", context)


@require_POST
@login_required
def appointment_update_status(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    # Проверка, что текущий пользователь — это мастер этой записи
    if appointment.stylist.user != request.user:
        return HttpResponseForbidden("Вы не имеете доступа к этой записи")

    new_status = request.POST.get("status")

    if new_status == 'DELETE':
        appointment.delete()
    elif new_status in [s.value for s in Appointment.Status]:
        appointment.status = new_status
        appointment.save()

    return redirect("stylist_dashboard")


@method_decorator(login_required, name='dispatch')
class ManualAppointmentCreateView(View):
    def get(self, request):
        user = request.user
        profile = getattr(user, 'profile', None)

        if not user.is_superuser and not (profile and profile.is_salon_admin and profile.salon):
            return HttpResponseForbidden("Недостаточно прав")

        if user.is_superuser:
            stylists = Stylist.objects.all()
            services = Service.objects.all()
        else:
            stylists = Stylist.objects.filter(salon=profile.salon)
            # Показываем только услуги, предоставляемые в этом салоне
            services = Service.objects.filter(
                salon_services__salon=profile.salon
            ).distinct()

        return render(request, 'manual_appointment_form.html', {
            'stylists': stylists,
            'services': services
        })

    def post(self, request):
        user = request.user
        profile = getattr(user, 'profile', None)

        if not user.is_superuser and not (profile and profile.is_salon_admin and profile.salon):
            return HttpResponseForbidden("Недостаточно прав")

        stylist_id = request.POST.get('stylist_id')
        service_ids = request.POST.getlist('service_ids')  # Используем getlist для множественного выбора
        time_str = request.POST.get('start_time')
        guest_name = request.POST.get('guest_name', '').strip()
        guest_phone = request.POST.get('guest_phone', '').strip()

        stylist = get_object_or_404(Stylist, id=stylist_id)

        if not user.is_superuser and stylist.salon != profile.salon:
            return HttpResponseForbidden("Вы не можете записывать к этому мастеру.")

        if not service_ids:
            messages.error(request, "Выберите хотя бы одну услугу.")
            return redirect('manual_appointment')

        try:
            start_time = make_aware(datetime.strptime(time_str, "%Y-%m-%dT%H:%M"))
        except:
            messages.error(request, "Неверный формат даты/времени.")
            return redirect('manual_appointment')

        # Получаем все выбранные услуги, которые оказывает этот мастер
        stylist_services = StylistService.objects.filter(
            stylist=stylist,
            salon_service__service__id__in=service_ids
        ).select_related('salon_service')

        if stylist_services.count() != len(service_ids):
            messages.error(request, "Некоторые выбранные услуги не оказываются этим мастером.")
            return redirect('manual_appointment')

        # Суммируем общую длительность
        total_duration = sum((ss.salon_service.duration for ss in stylist_services), timedelta())
        end_time = start_time + total_duration

        # Проверка на пересечение по времени
        if Appointment.objects.filter(
            stylist=stylist,
            start_time__lt=end_time,
            end_time__gt=start_time
        ).exists():
            messages.error(request, "Мастер занят в это время.")
            return redirect('manual_appointment')

        # Создаём запись
        appointment = Appointment.objects.create(
            stylist=stylist,
            start_time=start_time,
            end_time=end_time,
            guest_name=guest_name,
            guest_phone=guest_phone,
            customer=None
        )

        # Привязываем все услуги
        for ss in stylist_services:
            AppointmentService.objects.create(
                appointment=appointment,
                stylist_service=ss
            )

        messages.success(request, "Запись успешно добавлена.")
        return redirect('dashboard')


@login_required
def get_stylists_by_service(request):
    service_id = request.GET.get('service_id')
    user = request.user
    profile = getattr(user, 'profile', None)

    # Если не суперадмин и нет прав — запрещаем
    if not user.is_superuser and not (profile and profile.is_salon_admin and profile.salon):
        return HttpResponseForbidden("Недостаточно прав")

    stylist_services = StylistService.objects.filter(
        salon_service__service_id=service_id
    ).select_related('stylist', 'stylist__user', 'stylist__salon')

    # 🔒 Фильтрация по салону, если это не суперпользователь
    if not user.is_superuser:
        stylist_services = stylist_services.filter(stylist__salon=profile.salon)

    data = [{
        'id': s.stylist.id,
        'name': s.stylist.user.get_full_name() or s.stylist.user.username
    } for s in stylist_services]

    return JsonResponse({'stylists': data})


@login_required
def get_available_times(request):
    stylist_id = request.GET.get('stylist_id')
    service_id = request.GET.get('service_id')
    date_str = request.GET.get('date')  # формат YYYY-MM-DD

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        return JsonResponse({'times': []})

    tz = pytz.timezone("Asia/Tashkent")

    stylist = get_object_or_404(Stylist, id=stylist_id)
    service = get_object_or_404(Service, id=service_id)

    # 🔒 Проверка доступа: только суперпользователь или админ своего салона
    user = request.user
    profile = getattr(user, 'profile', None)
    if not user.is_superuser and not (profile and profile.is_salon_admin and stylist.salon == profile.salon):
        return HttpResponseForbidden("Недостаточно прав")

    # Получаем длительность услуги от StylistService
    stylist_service = StylistService.objects.filter(
        stylist=stylist,
        salon_service__service=service
    ).first()

    if not stylist_service:
        return JsonResponse({'times': []})  # Мастер не оказывает услугу

    duration = stylist_service.salon_service.duration
    working_hours = WorkingHour.objects.filter(stylist=stylist, weekday=date.weekday())

    available_slots = []
    slot = timedelta(minutes=15)

    for wh in working_hours:
        start_dt = datetime.combine(date, wh.start_time)
        end_dt = datetime.combine(date, wh.end_time)

        break_periods = BreakPeriod.objects.filter(working_hour=wh)

        while start_dt + duration <= end_dt:
            st_aware = tz.localize(start_dt)
            end_aware = st_aware + duration

            # Проверка на пересечение с другими записями
            overlap = Appointment.objects.filter(
                stylist=stylist,
                start_time__lt=end_aware,
                end_time__gt=st_aware
            ).exists()

            # Проверка на пересечение с перерывами
            in_break = any(
                (start_dt < datetime.combine(date, bp.end_time) and
                 start_dt + duration > datetime.combine(date, bp.start_time))
                for bp in break_periods
            )

            # ✅ Проверка на блокировку времени стилистом
            in_dayoff = StylistDayOff.objects.filter(
                stylist=stylist,
                date=date
            ).filter(
                Q(from_time__isnull=True, to_time__isnull=True) |  # Весь день
                Q(from_time__lt=(start_dt + duration).time(), to_time__gt=start_dt.time())  # Частичная
            ).exists()

            if not overlap and not in_break and not in_dayoff:
                available_slots.append(start_dt.strftime("%H:%M"))

            start_dt += slot

    return JsonResponse({'times': available_slots})


def is_stylist_or_superuser(user):
    return user.is_superuser or hasattr(user, 'stylist_profile')

@method_decorator([login_required, user_passes_test(is_stylist_or_superuser)], name='dispatch')
class StylistManualAppointmentCreateView(View):
    def get(self, request):
        stylist = request.user.stylist_profile
        services = Service.objects.filter(
            id__in=StylistService.objects.filter(stylist=stylist).values_list('salon_service__service_id', flat=True)
        )  # если через ManyToManyField
        return render(request, 'stylist_manual_appointment_form.html', {
            'services': services
        })

    def post(self, request):
        stylist = request.user.stylist_profile
        service_ids = request.POST.getlist('service_ids') # теперь список
        date = request.POST.get('date')
        time = request.POST.get('time')
        guest_name = request.POST.get('guest_name', '').strip()
        guest_phone = request.POST.get('guest_phone', '').strip()

        if not all([service_ids, date, time]):
            messages.error(request, "Заполните все поля.")
            return redirect('stylist_manual_appointment')

        try:
            start_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            messages.error(request, "Неверная дата или время.")
            return redirect('stylist_manual_appointment')

        tz = pytz.timezone("Asia/Tashkent")
        start_time = tz.localize(start_time)

        # Получаем все StylistService-объекты
        stylist_services = StylistService.objects.filter(
            stylist=stylist,
            salon_service__service_id__in=service_ids
        ).select_related('salon_service')

        if stylist_services.count() != len(service_ids):
            messages.error(request, "Одна или несколько услуг не найдены.")
            return redirect('stylist_manual_appointment')

        # Общая длительность
        total_duration = sum((s.salon_service.duration for s in stylist_services), timedelta())
        end_time = start_time + total_duration

        overlap = Appointment.objects.filter(
            stylist=stylist,
            start_time__lt=end_time,
            end_time__gt=start_time
        ).exists()

        if overlap:
            messages.error(request, "Выбранное время занято.")
            return redirect('stylist_manual_appointment')

        # ✅ Создаём Appointment
        appointment = Appointment.objects.create(
            stylist=stylist,
            start_time=start_time,
            end_time=end_time,
            status='C',
            guest_name=guest_name,
            guest_phone=guest_phone,
            customer=None
        )

        # ✅ Привязываем все услуги
        for s in stylist_services:
            AppointmentService.objects.create(
                appointment=appointment,
                stylist_service=s
            )

        messages.success(request, "Запись успешно создана.")
        return redirect('stylist_dashboard')


def get_available_times_for_stylist(request):
    try:
        if not hasattr(request.user, 'stylist_profile'):
            return JsonResponse({'times': []})

        date_str = request.GET.get('date')
        service_id = request.GET.get('service_id')

        if not date_str or not service_id:
            return JsonResponse({'times': []})

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({'times': []})

        stylist = request.user.stylist_profile

        # 🔍 Получаем StylistService
        stylist_service = (
            StylistService.objects
            .filter(stylist=stylist, salon_service__service_id=service_id)
            .select_related('salon_service')
            .first()
        )

        if not stylist_service:
            return JsonResponse({'times': []})

        duration = stylist_service.salon_service.duration
        working_hours = WorkingHour.objects.filter(stylist=stylist, weekday=date.weekday())

        tz = pytz.timezone("Asia/Tashkent")
        slot = timedelta(minutes=15)
        available_slots = []

        for wh in working_hours:
            start_dt = datetime.combine(date, wh.start_time)
            end_dt = datetime.combine(date, wh.end_time)
            break_periods = BreakPeriod.objects.filter(working_hour=wh)

            while start_dt + duration <= end_dt:
                st_aware = tz.localize(start_dt)

                # Проверка на пересечение с другими записями
                overlap = Appointment.objects.filter(
                    stylist=stylist,
                    start_time__lt=st_aware + duration,
                    end_time__gt=st_aware
                ).exists()

                # Проверка на пересечение с перерывами
                in_break = any(
                    datetime.combine(date, bp.start_time) < start_dt + duration and
                    datetime.combine(date, bp.end_time) > start_dt
                    for bp in break_periods
                )

                # ✅ Проверка на блокировку времени стилистом
                in_dayoff = StylistDayOff.objects.filter(
                    stylist=stylist,
                    date=date
                ).filter(
                    Q(from_time__isnull=True, to_time__isnull=True) |  # Весь день
                    Q(from_time__lt=(start_dt + duration).time(), to_time__gt=start_dt.time())  # Частичная блокировка
                ).exists()

                if not overlap and not in_break and not in_dayoff:
                    available_slots.append(start_dt.strftime("%H:%M"))

                start_dt += slot

        return JsonResponse({'times': available_slots})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def stylist_reports(request):
    try:
        stylist = request.user.stylist_profile
    except Stylist.DoesNotExist:
        return render(request, "no_stylist_profile.html")

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    report_appointments = []
    total_cash = 0
    total_clients = 0

    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

            report_appointments = (
                Appointment.objects
                .filter(
                    stylist=stylist,
                    start_time__date__range=(start, end),
                    status=Appointment.Status.DONE
                )
                .prefetch_related(
                    Prefetch(
                        'services',
                        queryset=AppointmentService.objects.select_related('stylist_service__salon_service__service')
                    )
                )
            )

            total_clients = report_appointments.count()

            for a in report_appointments:
                total_cash += a.get_total_price()

        except ValueError:
            pass

    context = {
        "report_appointments": report_appointments,
        "total_cash": total_cash,
        "total_clients": total_clients,
        "start_date": start_date,
        "end_date": end_date,
    }

    return render(request, "stylist_reports.html", context)

@login_required
def stylist_dayoff_view(request):
    profile = request.user.profile

    stylist_creation_form = None
    salon_service_form = None
    salon_services = None
    selected_stylist = None
    selected_stylist_id = None

    stylists = []
    stylists_map = {}

    # Для администратора
    if profile.is_salon_admin:
        stylists_queryset = (
            Stylist.objects.filter(salon=profile.salon)
            .select_related('user', 'level')
            .order_by('user__first_name', 'user__last_name')
        )
        stylists = list(stylists_queryset)
        for stylist_obj in stylists:
            stylist_obj.update_form = StylistUpdateForm(stylist=stylist_obj)
            stylists_map[stylist_obj.id] = stylist_obj

        salon_services = list(
            SalonService.objects.filter(salon=profile.salon)
            .select_related('service', 'category')
            .order_by('position', 'service__name')
        )

        stylist_creation_form = StylistCreationForm()
        salon_service_form = SalonServiceForm(profile.salon)

        selected_stylist_id = request.POST.get('stylist_id') or request.GET.get('stylist_id')

        if selected_stylist_id:
            try:
                selected_stylist = stylists_map[int(selected_stylist_id)]
            except (KeyError, ValueError):
                selected_stylist = get_object_or_404(
                    Stylist, id=selected_stylist_id, salon=profile.salon
                )
                selected_stylist.update_form = StylistUpdateForm(stylist=selected_stylist)
                stylists.append(selected_stylist)
                stylists_map[selected_stylist.id] = selected_stylist
            selected_stylist_id = str(selected_stylist.id)
    else:
        stylists = None
        selected_stylist = request.user.stylist_profile
        selected_stylist_id = str(selected_stylist.id)

    stylist = selected_stylist

    # Обработка POST
    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if profile.is_salon_admin and form_type == 'stylist_add':
            stylist_creation_form = StylistCreationForm(request.POST, request.FILES)
            if stylist_creation_form.is_valid():
                stylist_creation_form.save(profile.salon)
                messages.success(request, 'Стилист добавлен в салон.')
                return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'salon_service_add':
            salon_service_form = SalonServiceForm(profile.salon, request.POST)
            if salon_service_form.is_valid():
                salon_service_form.save()
                messages.success(request, 'Услуга добавлена в салон.')
                return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'salon_service_delete':
            salon_service_id = request.POST.get('salon_service_id')
            salon_service = get_object_or_404(
                SalonService, id=salon_service_id, salon=profile.salon
            )
            try:
                salon_service.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'Невозможно удалить услугу, пока есть связанные записи (например, записи клиентов).'
                )
            else:
                messages.success(request, 'Услуга удалена из салона.')
            return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'salon_service_update':
            salon_service_id = request.POST.get('salon_service_id')
            salon_service = get_object_or_404(
                SalonService, id=salon_service_id, salon=profile.salon
            )

            update_form = SalonServiceUpdateForm(
                data=request.POST,
                instance=salon_service,
                auto_id=f'id_%s_{salon_service.id}',
            )

            if update_form.is_valid():
                update_form.save()
                messages.success(request, 'Настройки услуги обновлены.')
                return redirect(reverse('stylist_dayoff'))

            for service in salon_services or []:
                if service.id == salon_service.id:
                    service.update_form = update_form
                    break
            else:
                salon_service.update_form = update_form
                if isinstance(salon_services, list):
                    salon_services.append(salon_service)
        elif profile.is_salon_admin and form_type == 'stylist_update':
            target_id = request.POST.get('stylist_id')
            target = get_object_or_404(Stylist, id=target_id, salon=profile.salon)
            update_form = StylistUpdateForm(request.POST, request.FILES, stylist=target)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, 'Данные стилиста обновлены.')
                redirect_id = selected_stylist_id or str(target.id)
                redirect_url = reverse('stylist_dayoff')
                if redirect_id:
                    redirect_url = f'{redirect_url}?stylist_id={redirect_id}'
                return redirect(redirect_url)
            else:
                display_target = stylists_map.get(target.id)
                if display_target is not None:
                    display_target.update_form = update_form
                else:
                    target.update_form = update_form
                    if isinstance(stylists, list):
                        stylists.append(target)
                        stylists_map[target.id] = target
        elif profile.is_salon_admin and form_type == 'stylist_delete':
            target_id = request.POST.get('stylist_id')
            target = get_object_or_404(Stylist, id=target_id, salon=profile.salon)
            user = target.user
            try:
                user.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'Невозможно удалить мастера, пока есть связанные записи (например, прошлые записи клиентов).'
                )
            else:
                messages.success(request, 'Стилист удалён из салона.')
            return redirect(reverse('stylist_dayoff'))

        # Дальнейшие действия требуют выбранного стилиста
        if stylist is None and form_type not in {'stylist_add', 'salon_service_add', 'salon_service_delete', 'salon_service_update', 'stylist_update', 'stylist_delete'}:
            messages.error(request, 'Сначала выберите мастера.')
            return redirect(reverse('stylist_dayoff'))

        # Добавление блокировки
        if form_type == 'dayoff_add':
            date_str = request.POST.get('date')
            from_time_str = request.POST.get('from_time')
            to_time_str = request.POST.get('to_time')

            if date_str:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                from_time = (
                    datetime.strptime(from_time_str, '%H:%M').time()
                    if from_time_str
                    else None
                )
                to_time = (
                    datetime.strptime(to_time_str, '%H:%M').time()
                    if to_time_str
                    else None
                )

                StylistDayOff.objects.create(
                    stylist=stylist,
                    date=date,
                    from_time=from_time,
                    to_time=to_time,
                )

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        # Изменение блокировки
        elif form_type == 'dayoff_update':
            block_id = request.POST.get('dayoff_id')
            block = get_object_or_404(StylistDayOff, id=block_id, stylist=stylist)

            date_str = request.POST.get('date')
            from_time_str = request.POST.get('from_time')
            to_time_str = request.POST.get('to_time')

            try:
                block.date = datetime.strptime(date_str, '%Y-%m-%d').date()
                block.from_time = (
                    datetime.strptime(from_time_str, '%H:%M').time()
                    if from_time_str
                    else None
                )
                block.to_time = (
                    datetime.strptime(to_time_str, '%H:%M').time()
                    if to_time_str
                    else None
                )
                block.save()
                messages.success(request, 'Блокировка обновлена.')
            except (ValueError, TypeError):
                messages.error(request, 'Неверный формат даты или времени.')

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        # Добавление рабочего интервала
        elif form_type == 'workinghour_add':
            weekday = int(request.POST.get('weekday'))
            start_time = datetime.strptime(request.POST.get('start_time'), '%H:%M').time()
            end_time = datetime.strptime(request.POST.get('end_time'), '%H:%M').time()

            WorkingHour.objects.create(
                stylist=stylist,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        # Обновление рабочего интервала
        elif form_type == 'workinghour_update':
            wh_id = request.POST.get('workinghour_id')
            wh = get_object_or_404(WorkingHour, id=wh_id, stylist=stylist)

            try:
                wh.weekday = int(request.POST.get('weekday'))
                wh.start_time = datetime.strptime(request.POST.get('start_time'), '%H:%M').time()
                wh.end_time = datetime.strptime(request.POST.get('end_time'), '%H:%M').time()
                wh.full_clean()
                wh.save()
                messages.success(request, 'Рабочий интервал обновлён.')
            except (ValueError, TypeError):
                messages.error(request, 'Неверный формат времени.')
            except ValidationError as exc:
                messages.error(request, exc.messages[0])

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        elif form_type == 'break_add':
            wh_id = request.POST.get('workinghour_id')
            wh = get_object_or_404(WorkingHour, id=wh_id, stylist=stylist)

            start_time = datetime.strptime(request.POST.get('start_time'), '%H:%M').time()
            end_time = datetime.strptime(request.POST.get('end_time'), '%H:%M').time()

            BreakPeriod.objects.create(
                working_hour=wh,
                start_time=start_time,
                end_time=end_time,
            )

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        # Удаление рабочего интервала
        elif form_type == 'workinghour_delete':
            wh_id = request.POST.get('workinghour_id')
            wh = get_object_or_404(WorkingHour, id=wh_id, stylist=stylist)
            wh.delete()
            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        elif profile.is_salon_admin and form_type == 'stylist_price_update':
            salon_service_id = request.POST.get('salon_service_id')
            price_raw = (request.POST.get('price') or '').replace(',', '.').strip()

            if not salon_service_id:
                messages.error(request, 'Не выбрана услуга.')
                return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

            if price_raw == '':
                StylistService.objects.filter(
                    stylist=stylist, salon_service_id=salon_service_id
                ).delete()
                messages.success(request, 'Цена удалена для выбранной услуги.')
                return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

            try:
                price_value = Decimal(price_raw)
                if price_value < 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError):
                messages.error(request, 'Введите корректную цену.')
            else:
                StylistService.objects.update_or_create(
                    stylist=stylist,
                    salon_service_id=salon_service_id,
                    defaults={'price': price_value},
                )
                messages.success(request, 'Цена сохранена.')

            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

    # Получение данных для отображения
    if stylist:
        blocks = StylistDayOff.objects.filter(stylist=stylist).order_by('-date', '-from_time')
        working_hours = (
            WorkingHour.objects.filter(stylist=stylist)
            .select_related('stylist')
            .prefetch_related('breaks')
            .order_by('weekday', 'start_time')
        )
        stylist_price_map = {
            ss.salon_service_id: ss.price
            for ss in StylistService.objects.filter(stylist=stylist)
        }
    else:
        blocks = StylistDayOff.objects.none()
        working_hours = WorkingHour.objects.none()
        stylist_price_map = {}

    if salon_services is not None:
        for service in salon_services:
            service.current_price = stylist_price_map.get(service.id)
            if not hasattr(service, 'update_form'):
                service.update_form = SalonServiceUpdateForm(
                    instance=service,
                    auto_id=f'id_%s_{service.id}',
                )
            service.duration_minutes = int(service.duration.total_seconds() // 60)

    return render(
        request,
        'stylist_dayoff_form.html',
        {
            'blocks': blocks,
            'working_hours': working_hours,
            'stylists': stylists,
            'selected_stylist_id': selected_stylist_id,
            'selected_stylist': stylist,
            'WEEKDAYS': WEEKDAYS,
            'stylist_creation_form': stylist_creation_form,
            'salon_service_form': salon_service_form,
            'salon_services': salon_services,
        },
    )

@login_required
def delete_dayoff(request, pk):
    block = get_object_or_404(StylistDayOff, pk=pk)

    # Запомним стилиста до удаления
    stylist_id = block.stylist.id

    # Только админ салона или сам стилист может удалить
    if request.user == block.stylist.user or (
        request.user.profile.is_salon_admin and request.user.profile.salon == block.stylist.salon
    ):
        block.delete()

    return redirect(f'{reverse("stylist_dayoff")}?stylist_id={stylist_id}')