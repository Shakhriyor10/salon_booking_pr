from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, TemplateView, UpdateView
from django.urls import reverse_lazy, reverse
from django.middleware.csrf import get_token
from django.utils.html import format_html
from users.models import Profile
from .form import (
    ReviewForm,
    StylistCreationForm,
    SalonServiceForm,
    SalonServiceUpdateForm,
    StylistUpdateForm,
    SalonPaymentCardForm,
    AppointmentPaymentMethodForm,
    AppointmentReceiptForm,
    AppointmentRefundForm,
    AppointmentRefundCompleteForm,
    SalonProductForm,
    ProductOrderForm,
)
from .models import Service, Stylist, Appointment, StylistService, Category, BreakPeriod, WorkingHour, Salon, \
    SalonService, City, AppointmentService, StylistDayOff, WEEKDAYS, Review, SalonPaymentCard, FavoriteSalon, \
    SalonProduct, ProductCart, ProductCartItem, ProductOrder, ProductOrderItem
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.utils.timezone import make_aware, now, localtime, timedelta
from django.contrib import messages
from booking.telebot import send_telegram
from django.http import JsonResponse, HttpResponseForbidden
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST
from django.template.context_processors import csrf
from django.db.models import Count, Sum, DecimalField, Prefetch, F, Max, Avg, Q
from django.db.models.functions import Cast, TruncDate, Coalesce, Lower, Upper
from datetime import date, datetime
from calendar import monthrange
from collections import defaultdict, Counter
import json
from decimal import Decimal, InvalidOperation
import datetime as dt
import secrets
import time
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
import re
from django.utils.dateparse import parse_datetime
import pytz
from django.db.models.deletion import ProtectedError
from users.forms import ProfileUpdateForm

User = get_user_model()

PHONE_INPUT_RE = re.compile(r'^\d{2}-\d{3}-\d{2}-\d{2}$')


def add_months(source_date, months):
    """Return a date shifted forward by the given number of months."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def normalize_uzbek_phone(phone_value: str) -> str:
    """Convert a masked Uzbek phone (xx-xxx-xx-xx) to +998XXXXXXXXX format."""
    digits = re.sub(r"\D", "", phone_value or "")
    return f"+998{digits}" if digits else ""


def transliterate_to_latin(name: str) -> str:
    """Convert Cyrillic/Uzbek characters to a readable Latin variant."""
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 's',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya', 'қ': 'q', 'ғ': 'g', 'ў': 'o', 'ҳ': 'h', 'ң': 'ng',
    }

    result = []
    for ch in (name or '').strip():
        lower = ch.lower()
        latin = mapping.get(lower, ch)
        if ch.isupper():
            latin = latin.capitalize()
        result.append(latin)

    sanitized = ''.join(result)
    return re.sub(r'[^A-Za-z0-9]', '', sanitized) or 'user'


def build_username(name: str, phone_digits: str) -> str:
    base = transliterate_to_latin(name)
    last_digits = (phone_digits or '')[-4:] or secrets.token_hex(2)
    base_candidate = f"{base}{last_digits}"
    base_candidate = base_candidate[:140]
    candidate = base_candidate
    suffix = 1

    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{base_candidate}{suffix}"
        suffix += 1

        if suffix % 25 == 0:
            candidate = f"{base_candidate}{secrets.token_hex(1)}{suffix}"

        candidate = candidate[:150]

    return candidate


def build_password(phone_digits: str) -> str:
    return (phone_digits or '')[-7:] or secrets.token_hex(4)


def ensure_guest_account(full_name: str, normalized_phone: str):
    """Always create a new user for a guest booking and return credentials."""
    if not normalized_phone:
        return None, None

    phone_digits = re.sub(r"\D", "", normalized_phone)
    username = build_username(full_name, phone_digits)
    password = build_password(phone_digits)

    user = User.objects.create_user(
        username=username,
        password=password,
        first_name=full_name,
    )

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.phone = normalized_phone
    profile.save(update_fields=['phone'])

    return user, {'username': username, 'password': password}


def _get_product_cart_for_request(request, salon: Salon):
    if not request.session.session_key:
        request.session.save()

    session_key = request.session.session_key
    cart = None

    if request.user.is_authenticated:
        cart = (
            ProductCart.objects
            .filter(salon=salon, user=request.user, is_active=True)
            .first()
        )
        if cart is None:
            cart = ProductCart.objects.create(
                salon=salon,
                user=request.user,
                session_key=session_key,
            )
        if cart.session_key != session_key:
            cart.session_key = session_key
            cart.save(update_fields=['session_key'])

        anonymous_cart = (
            ProductCart.objects
            .filter(salon=salon, user__isnull=True, session_key=session_key, is_active=True)
            .first()
        )
        if anonymous_cart and anonymous_cart.items.exists():
            for item in anonymous_cart.items.select_related('product'):
                target_item, _ = ProductCartItem.objects.get_or_create(
                    cart=cart,
                    product=item.product,
                    defaults={'quantity': 0},
                )
                target_item.quantity = min(
                    item.product.quantity,
                    target_item.quantity + item.quantity,
                )
                target_item.save()
            anonymous_cart.items.all().delete()
            anonymous_cart.is_active = False
            anonymous_cart.save(update_fields=['is_active'])
    else:
        cart = (
            ProductCart.objects
            .filter(salon=salon, session_key=session_key, user__isnull=True, is_active=True)
            .first()
        )
        if cart is None:
            cart = ProductCart.objects.create(
                salon=salon,
                session_key=session_key,
            )

    return cart


def _available_product_payment_methods(salon: Salon):
    methods = [ProductOrder.PaymentMethod.CASH]
    if salon.get_active_payment_card():
        methods.insert(0, ProductOrder.PaymentMethod.CARD)
    return methods


def _serialize_cart(cart: ProductCart, as_strings: bool = False):
    items_data = []
    total = Decimal('0')
    if not cart:
        return {'items': items_data, 'total': str(total) if as_strings else total}

    for item in cart.items.select_related('product'):
        product = item.product
        final_price = product.get_final_price()
        subtotal = final_price * item.quantity
        total += subtotal
        items_data.append({
            'id': item.id,
            'product_id': product.id,
            'name': product.name,
            'quantity': item.quantity,
            'available': product.quantity,
            'photo': product.photo.url if product.photo else '',
            'final_price': str(final_price) if as_strings else final_price,
            'old_price': (
                str(product.get_display_old_price())
                if as_strings and product.get_display_old_price() is not None
                else product.get_display_old_price()
            ),
            'has_discount': product.has_discount(),
            'subtotal': str(subtotal) if as_strings else subtotal,
        })

    return {'items': items_data, 'total': str(total) if as_strings else total}


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
        if profile and getattr(profile, 'is_salon_admin', False):
            salon = getattr(profile, 'salon', None)
            if salon and salon.is_subscription_active:
                return salon

        try:
            stylist_profile = user.stylist_profile
        except ObjectDoesNotExist:
            stylist_profile = None

        if stylist_profile:
            salon = getattr(stylist_profile, 'salon', None)
            if salon and salon.is_subscription_active:
                return salon

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
        queryset = Salon.objects.active().order_by('position')
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

        favorite_salon_ids = set()
        if self.request.user.is_authenticated:
            favorite_salon_ids = set(
                FavoriteSalon.objects.filter(user=self.request.user).values_list('salon_id', flat=True)
            )

        for salon in context['salons']:
            rating = salon.average_rating() or 0
            rounded_rating = round(rating * 2) / 2
            full = int(rounded_rating)
            half = (rounded_rating - full) == 0.5
            empty = 5 - full - (1 if half else 0)
            salon.stars = {'full': range(full), 'half': half, 'empty': range(empty)}
            salon.rating_value = round(rating, 1)
            salon.is_favorite = salon.id in favorite_salon_ids

        context['types'] = ['male', 'female', 'both']
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_rating'] = self.request.GET.get('rating', '')
        context['selected_service'] = self.request.GET.get('service', '')
        context['favorite_salon_ids'] = list(favorite_salon_ids)
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
        salons = Salon.objects.active().values_list('name', flat=True)
        filtered_salons = [s for s in salons if q in s.lower()]
        results += [{"type": "salon", "label": name} for name in filtered_salons]

    return JsonResponse(results[:30], safe=False)


@login_required
@require_POST
def toggle_favorite_salon(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Некорректные данные"}, status=400)

    salon_id = payload.get('salon_id')
    if not salon_id:
        return JsonResponse({"error": "Не указан салон"}, status=400)

    salon = get_object_or_404(Salon.objects.active(), id=salon_id)
    favorite, created = FavoriteSalon.objects.get_or_create(user=request.user, salon=salon)
    if created:
        is_favorite = True
    else:
        favorite.delete()
        is_favorite = False

    return JsonResponse({"is_favorite": is_favorite})

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

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.active()

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
        context['reviews'] = salon.reviews.order_by('-created_at')
        context['review_form'] = ReviewForm()
        context['average_rating'] = rating
        context['categories'] = categories
        context['uncategorized_services'] = uncategorized_services
        stylist_services = (
            StylistService.objects.filter(
                salon_service__salon=salon,
                salon_service__is_active=True,
                salon_service__service__is_active=True,
            )
            .values_list('salon_service__service_id', 'stylist_id')
        )

        service_stylists_map = {}
        for service_id, stylist_id in stylist_services:
            service_stylists_map.setdefault(service_id, []).append(stylist_id)

        context['service_stylists_map'] = service_stylists_map
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
            .order_by(
                F('level__order').desc(nulls_last=True),
                'user__first_name',
                'user__last_name',
                'user__username',
            )
        )
        context['stylists'] = stylists
        products = SalonProduct.objects.filter(
            salon=salon,
            is_active=True,
            quantity__gt=0,
        ).order_by('-created_at')
        context['salon_products'] = products

        product_cart = _get_product_cart_for_request(self.request, salon)
        cart_data = _serialize_cart(product_cart)
        context['product_cart_items'] = cart_data['items']
        context['product_cart_total'] = cart_data['total']
        available_methods = _available_product_payment_methods(salon)
        context['product_order_form'] = ProductOrderForm(available_methods=available_methods)
        context['product_payment_methods'] = available_methods
        context['delivery_eta_days'] = 2
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


@require_POST
def add_product_to_cart(request, pk):
    salon = get_object_or_404(Salon.objects.active(), id=pk)
    product_id = request.POST.get('product_id')
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    product = get_object_or_404(SalonProduct, id=product_id, salon=salon)
    if not product.is_active or product.quantity <= 0:
        messages.error(request, 'Этот товар недоступен для заказа.')
        return redirect(salon.get_absolute_url())

    cart = _get_product_cart_for_request(request, salon)
    cart_item, _ = ProductCartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 0},
    )
    cart_item.quantity = min(product.quantity, cart_item.quantity + quantity)
    cart_item.save()

    cart_data = _serialize_cart(cart, as_strings=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'cart': cart_data})

    messages.success(request, f'Товар «{product.name}» добавлен в корзину.')
    return redirect(salon.get_absolute_url())


@require_POST
def update_product_cart_item(request, pk):
    salon = get_object_or_404(Salon.objects.active(), id=pk)
    cart = _get_product_cart_for_request(request, salon)
    item_id = request.POST.get('item_id')
    action = request.POST.get('action', 'update')
    quantity_raw = request.POST.get('quantity', 1)
    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        quantity = 1

    item = get_object_or_404(ProductCartItem, id=item_id, cart=cart)

    if action == 'remove' or quantity <= 0 or item.product.quantity == 0:
        item.delete()
    else:
        quantity = min(max(quantity, 1), item.product.quantity)
        item.quantity = quantity
        item.save()

    cart_data = _serialize_cart(cart, as_strings=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'cart': cart_data})

    messages.success(request, 'Корзина обновлена.')
    return redirect(salon.get_absolute_url())


@login_required
@require_POST
def checkout_salon_products(request, pk):
    salon = get_object_or_404(Salon.objects.active(), id=pk)
    cart = _get_product_cart_for_request(request, salon)
    cart_items = list(cart.items.select_related('product'))

    if not cart_items:
        messages.error(request, 'Добавьте товары в корзину, чтобы оформить заказ.')
        return redirect(salon.get_absolute_url())

    available_methods = _available_product_payment_methods(salon)
    order_form = ProductOrderForm(request.POST, available_methods=available_methods)
    if not order_form.is_valid():
        errors = []
        for error_list in order_form.errors.values():
            errors.extend([str(err) for err in error_list])
        messages.error(request, '; '.join(errors) or 'Проверьте форму заказа.')
        return redirect(salon.get_absolute_url())

    cleaned_items = []
    for item in cart_items:
        product = item.product
        if not product.is_active or product.quantity == 0:
            continue

        if item.quantity > product.quantity:
            item.quantity = product.quantity
            item.save(update_fields=['quantity'])

        if item.quantity > 0:
            cleaned_items.append(item)

    if not cleaned_items:
        cart.items.all().delete()
        messages.error(request, 'Выбранные товары сейчас недоступны.')
        return redirect(salon.get_absolute_url())

    total = Decimal('0')
    for item in cleaned_items:
        total += item.product.get_final_price() * item.quantity

    payment_method = order_form.cleaned_data['payment_method']
    payment_card = None
    if payment_method == ProductOrder.PaymentMethod.CARD:
        payment_card = salon.get_active_payment_card()
        if not payment_card:
            messages.error(request, 'У салона нет активной карты для оплаты.')
            return redirect(salon.get_absolute_url())

    order = ProductOrder.objects.create(
        salon=salon,
        user=request.user,
        total_amount=total,
        payment_method=payment_method,
        payment_card=payment_card,
    )

    for item in cleaned_items:
        product = item.product
        ProductOrderItem.objects.create(
            order=order,
            product_name=product.name,
            unit_price=product.get_final_price(),
            quantity=item.quantity,
            old_price=product.get_display_old_price(),
        )
        new_quantity = product.quantity - item.quantity
        product.quantity = max(0, new_quantity)
        if product.quantity == 0:
            product.is_active = False
        product.save(update_fields=['quantity', 'is_active', 'updated_at'])

    cart.items.all().delete()
    messages.success(
        request,
        'Заказ оформлен! Курьер доставит товары в течение 2 дней.',
    )
    return redirect(salon.get_absolute_url())


@login_required
@require_POST
def delete_review(request, pk):
    review = get_object_or_404(Review, pk=pk)

    if review.user_id != request.user.id:
        return JsonResponse({
            'success': False,
            'error': 'Вы не можете удалить этот отзыв.'
        }, status=403)

    salon = review.salon
    review.delete()

    average_rating = salon.average_rating() or 0
    rounded_rating = round(average_rating * 2) / 2
    full_stars = int(rounded_rating)
    has_half_star = (rounded_rating - full_stars) == 0.5
    empty_stars = 5 - full_stars - (1 if has_half_star else 0)
    review_count = salon.reviews.count()

    return JsonResponse({
        'success': True,
        'average_rating': float(average_rating),
        'average_rating_display': f'{average_rating:.1f}',
        'review_count': review_count,
        'stars': {
            'full': full_stars,
            'half': has_half_star,
            'empty': empty_stars,
        },
    })


class CategoryServicesView(View):
    def get(self, request, pk):
        salon_id = request.GET.get('salon')
        salon = get_object_or_404(Salon.objects.active(), id=salon_id)
        category = get_object_or_404(Category, id=pk)  # исправлено здесь

        services = SalonService.objects.filter(
            salon=salon,
            category=category,
            is_active=True
        ).order_by('position')  # сортировка по позиции

        stylist_services = (
            StylistService.objects.filter(
                salon_service__salon=salon,
                salon_service__is_active=True,
                salon_service__service__is_active=True,
            )
            .values_list('salon_service__service_id', 'stylist_id')
        )

        service_stylists_map = {}
        for service_id, stylist_id in stylist_services:
            service_stylists_map.setdefault(service_id, []).append(stylist_id)

        return render(request, 'category_services.html', {
            'salon': salon,
            'category': category,
            'services': services,
            'service_stylists_map': service_stylists_map,
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

    def get_queryset(self):
        return (
            Stylist.objects.select_related('user', 'level')
            .order_by(
                F('level__order').desc(nulls_last=True),
                'user__first_name',
                'user__last_name',
                'user__username',
            )
        )


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
                overlap = (
                    Appointment.objects
                    .filter(
                        stylist=stylist,
                        start_time__lt=current + timedelta(minutes=15),
                        end_time__gt=current,
                    )
                    .exclude(status=Appointment.Status.CANCELLED)
                    .exists()
                )
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
        credentials_data = None
        auto_login_user = None

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
        if (
            Appointment.objects
            .filter(
                stylist=stylist,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .exists()
        ):
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
                guest_phone_input = request.POST.get('guest_phone', '').strip()
                if not PHONE_INPUT_RE.match(guest_phone_input):
                    messages.error(request, 'Укажите корректный номер телефона в формате 93-123-45-67.')
                    return redirect('home')

                guest_phone = normalize_uzbek_phone(guest_phone_input)

                if not hasattr(customer, 'profile'):
                    Profile.objects.create(user=customer, phone=guest_phone)
                else:
                    customer.profile.phone = guest_phone
                    customer.profile.save(update_fields=['phone'])
        else:
            guest_name = request.POST.get('guest_name', '').strip()
            guest_phone_input = request.POST.get('guest_phone', '').strip()

            if not guest_name or not PHONE_INPUT_RE.match(guest_phone_input):
                messages.error(request, 'Укажите имя и корректный номер телефона в формате 93-123-45-67.')
                return redirect('home')

            guest_phone = normalize_uzbek_phone(guest_phone_input)
            customer, credentials_data = ensure_guest_account(guest_name, guest_phone)
            auto_login_user = customer

        # Создаём запись
        appointment = Appointment.objects.create(
            customer=customer,
            guest_name='' if customer else guest_name,
            guest_phone='' if customer else guest_phone,
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
        master_name = stylist.user.get_full_name().strip()
        if not master_name:
            master_name = stylist.user.username
        if stylist.level:
            master_name += f" ({stylist.level.name})"
        msg = (
            f"<b>📝 Новая запись!</b>\n"
            f"👤 Клиент: {client_repr}\n"
            f"✂️ Мастер: {master_name}\n"
            f"💇 Услуги: {service_list}\n"
            f"🕒 Время: {start_time.strftime('%d.%m.%Y %H:%M')}"
        )
        send_telegram(
            chat_id=stylist.telegram_chat_id,
            username=stylist.telegram_username,
            text=msg
        )

        if credentials_data:
            message_html = format_html(
                '<div class="d-flex flex-wrap align-items-center gap-3 booking-success-credentials" data-credential="Ваш логин: {0}, Ваш пароль: {1}">'
                '<span class="badge bg-light text-dark border small mb-0" data-credential="Ваш логин: {0}, Ваш пароль: {1}">Ваш логин: {0}, Ваш пароль: {1}</span>'
                '<button type="button" class="btn btn-sm btn-outline-secondary copy-credential" data-credential="Ваш логин: {0}, Ваш пароль: {1}">Скопировать</button>'
                '</div>'
                '</div>',
                credentials_data['username'],
                credentials_data['password'],
            )
            messages.success(
                request,
                message_html,
                extra_tags='booking-success-modal booking-credentials',
            )
        else:
            messages.success(
                request,
                'Запись успешно создана! ✂️',
                extra_tags='booking-success-modal',
            )

        if auto_login_user:
            login(request, auto_login_user, backend='django.contrib.auth.backends.ModelBackend')

        return redirect('my_appointments')


def service_booking(request):
    raw_service_ids = request.GET.getlist("services")
    salon_id = request.GET.get('salon')
    stylist_id = request.GET.get('stylist')

    if not salon_id:
        return render(request, 'error.html', {"message": "Салон не указан."})

    salon = get_object_or_404(Salon.objects.active(), id=salon_id)

    today = now().date()
    max_date = add_months(today, 2)
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
    next_available_slots = []
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
                    overlap = (
                        Appointment.objects
                        .filter(
                            stylist=stylist,
                            start_time__lt=current + ss_duration,
                            end_time__gt=current,
                        )
                        .exclude(status=Appointment.Status.CANCELLED)
                        .exists()
                    )

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
                        'stylist_id': selected_stylist.id,
                        'auto_slot_str': slot_entry['slots'][0].strftime('%Y-%m-%dT%H:%M'),
                    }
                    break

                search_date += timedelta(days=1)

        if not selected_stylist and not stylist_slots and stylist_to_services:
            pending_stylists = set(stylist_to_services.keys())
            search_date = selected_date + timedelta(days=1)

            while pending_stylists and search_date <= max_date:
                for stylist_id in list(pending_stylists):
                    slot_entry = build_slot_entry(stylist_id, search_date)
                    if not slot_entry:
                        continue

                    first_slot = slot_entry['slots'][0]
                    slot_payload = {
                        'date': search_date,
                        'slot': first_slot,
                        'price': slot_entry['price'],
                        'duration': slot_entry['duration'],
                        'duration_display': slot_entry.get('duration_display'),
                        'stylist': slot_entry['stylist'],
                        'stylist_id': stylist_id,
                        'services': slot_entry.get('services', []),
                        'auto_slot_str': first_slot.strftime('%Y-%m-%dT%H:%M'),
                    }

                    next_available_slots.append(slot_payload)

                    if not next_available_slot or first_slot < next_available_slot['slot']:
                        next_available_slot = slot_payload

                    pending_stylists.remove(stylist_id)

                search_date += timedelta(days=1)

            next_available_slots.sort(key=lambda entry: entry['slot'])

        if find_next_requested:
            target_slot = next_available_slot

            preferred_stylist_id = request.GET.get('next_stylist')
            preferred_slot_str = request.GET.get('next_slot')

            if preferred_stylist_id or preferred_slot_str:
                for slot_data in next_available_slots:
                    stylist_match = True
                    slot_match = True

                    if preferred_stylist_id:
                        stylist_match = str(slot_data.get('stylist_id')) == preferred_stylist_id

                    if preferred_slot_str:
                        slot_match = slot_data.get('auto_slot_str') == preferred_slot_str

                    if stylist_match and slot_match:
                        target_slot = slot_data
                        break

            if target_slot:
                query_params = request.GET.copy()
                if 'find_next' in query_params:
                    del query_params['find_next']
                query_params['date'] = target_slot['date'].isoformat()

                if target_slot.get('stylist_id'):
                    query_params['stylist'] = str(target_slot['stylist_id'])
                elif 'stylist' in query_params:
                    del query_params['stylist']

                auto_slot_value = target_slot.get('auto_slot_str')
                if auto_slot_value:
                    query_params['auto_slot'] = auto_slot_value
                elif 'auto_slot' in query_params:
                    del query_params['auto_slot']

                redirect_url = f"{reverse('service_booking')}?{query_params.urlencode()}"
                return redirect(redirect_url)
            else:
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
        'next_available_slots': next_available_slots,
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


def get_latest_activity_timestamp(appointments):
    timestamps = []
    for appointment in appointments:
        timestamps.extend(
            filter(
                None,
                (
                    appointment.created_at,
                    getattr(appointment, "receipt_uploaded_at", None),
                    getattr(appointment, "refund_receipt_uploaded_at", None),
                    getattr(appointment, "refund_requested_at", None),
                ),
            )
        )

    return max(timestamps) if timestamps else None


def build_calendar_summary(appointments):
    summary = defaultdict(lambda: {
        Appointment.Status.PENDING: 0,
        Appointment.Status.CONFIRMED: 0,
        Appointment.Status.DONE: 0,
    })

    for appointment in appointments:
        date_key = appointment.start_time.date().isoformat()
        if appointment.status in {
            Appointment.Status.PENDING,
            Appointment.Status.CONFIRMED,
            Appointment.Status.DONE,
        }:
            summary[date_key][appointment.status] += 1

    formatted = {}
    for date_key, counts in summary.items():
        # убираем статусы без записей, чтобы не загромождать JSON
        formatted[date_key] = {
            status: count for status, count in counts.items() if count
        }

    return formatted

@login_required
def dashboard_view(request):
    today = now().date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    user = request.user
    profile = getattr(user, 'profile', None)

    # 🔐 Проверка доступа
    if not user.is_superuser and not (profile and profile.is_salon_admin and profile.salon):
        return HttpResponseForbidden("Недостаточно прав для доступа к дашборду.")

    # 🔽 Базовый queryset
    appointments_qs = (
        Appointment.objects
        .select_related("customer", "stylist")  # оставляем только существующие связи
        .filter()
        .order_by("-start_time")
    )

    # 🔽 Фильтрация по салону
    if not user.is_superuser:
        appointments_qs = appointments_qs.filter(stylist__salon=profile.salon)

    appointments = list(appointments_qs)
    grouped_appointments = group_appointments_by_date(appointments)
    latest_activity = get_latest_activity_timestamp(appointments)
    latest_created_iso = latest_activity.isoformat() if latest_activity else ""

    # 📊 Группировка и расчёты
    visible_start = yesterday
    visible_end = tomorrow

    cash_total = sum(
        a.get_total_price() for a in appointments if a.status == Appointment.Status.DONE
    )

    cash_today = sum(
        a.get_total_price()
        for a in appointments
        if a.status == Appointment.Status.DONE and a.start_time.date() == today
    )

    default_visible_dates = [
        visible_start.isoformat(),
        today.isoformat(),
        visible_end.isoformat(),
    ]

    calendar_summary = build_calendar_summary(appointments)

    context = {
        "grouped_appointments": grouped_appointments,
        "appointments": appointments,
        "cash_total": cash_total,
        "cash_today": cash_today,
        "today": today,
        "default_visible_dates_json": json.dumps(default_visible_dates),
        "calendar_summary_json": json.dumps(calendar_summary),
        "latest_created_iso": latest_created_iso,
        "refund_card_type_choices": SalonPaymentCard.CARD_TYPE_CHOICES,
        "is_salon_admin": True,  # ← Админ салона всегда видит всё
        "viewer_stylist": None,
    }

    return render(request, "dashboard.html", context)


@login_required
@require_GET
def dashboard_ajax(request):
    today = now().date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    user = request.user
    profile = getattr(user, 'profile', None)

    # Базовый queryset
    appointments_qs = (
        Appointment.objects
        .select_related("customer", "stylist")
        .filter()
        .order_by("-start_time")
    )

    # Фильтрация по салону — только если не суперадмин
    if not user.is_superuser:
        appointments_qs = appointments_qs.filter(stylist__salon=profile.salon)  # ← БЕЗОПАСНО

    appointments = list(appointments_qs)
    grouped_appointments = group_appointments_by_date(appointments)
    latest_activity = get_latest_activity_timestamp(appointments)
    default_visible_dates = [
        yesterday.isoformat(),
        today.isoformat(),
        tomorrow.isoformat(),
    ]
    calendar_summary = build_calendar_summary(appointments)

    context = {
        "grouped_appointments": grouped_appointments,
        "csrf_token": get_token(request),
        "refund_card_type_choices": SalonPaymentCard.CARD_TYPE_CHOICES,
        "is_salon_admin": True,      # ← ВСЁ ВИДИТ
        "viewer_stylist": None,      # ← Нет конкретного стилиста
    }

    html = render_to_string("partials/appointments_table_rows.html", context)
    return JsonResponse({
        "html": html,
        "calendar": calendar_summary,
        "default_visible_dates": default_visible_dates,
        "today": today.isoformat(),
        "latest_created": latest_activity.isoformat() if latest_activity else None,
        "count": len(appointments),
    })


@login_required
@require_GET
def dashboard_updates(request):
    today = now().date()
    yesterday = today - timedelta(days=1)
    user = request.user
    profile = getattr(user, "profile", None)

    appointments_qs = Appointment.objects.filter(start_time__date__gte=yesterday)

    if not user.is_superuser:
        if profile and profile.is_salon_admin and profile.salon:
            appointments_qs = appointments_qs.filter(stylist__salon=profile.salon)
        else:
            return JsonResponse({"has_updates": False, "latest_created": None, "count": 0})

    wait_for_updates = request.GET.get("wait") in {"1", "true", "True"}

    timeout_seconds = 25
    requested_timeout = request.GET.get("timeout")
    if requested_timeout:
        try:
            timeout_seconds = max(5, min(60, int(requested_timeout)))
        except (TypeError, ValueError):
            timeout_seconds = 25

    deadline = timezone.now() + timedelta(seconds=timeout_seconds) if wait_for_updates else None

    since_raw = request.GET.get("since")
    last_count_raw = request.GET.get("count")

    def evaluate_changes():
        totals_local = appointments_qs.aggregate(
            latest_created=Max("created_at"),
            latest_receipt_uploaded=Max("receipt_uploaded_at"),
            latest_refund_receipt_uploaded=Max("refund_receipt_uploaded_at"),
            latest_refund_requested=Max("refund_requested_at"),
            total_count=Count("id"),
        )
        latest_created_local = max(
            (
                ts
                for ts in (
                    totals_local.get("latest_created"),
                    totals_local.get("latest_receipt_uploaded"),
                    totals_local.get("latest_refund_receipt_uploaded"),
                    totals_local.get("latest_refund_requested"),
                )
                if ts is not None
            ),
            default=None,
        )
        total_count_local = totals_local.get("total_count", 0) or 0

        has_updates_local = False

        if since_raw:
            parsed_since = parse_datetime(since_raw)
            if parsed_since is not None:
                if timezone.is_naive(parsed_since):
                    parsed_since = timezone.make_aware(parsed_since)
                if latest_created_local and latest_created_local > parsed_since:
                    has_updates_local = True

        if not has_updates_local and last_count_raw is not None:
            try:
                last_count_value = int(last_count_raw)
            except (TypeError, ValueError):
                last_count_value = None

            if last_count_value is not None and total_count_local != last_count_value:
                has_updates_local = True

        return has_updates_local, latest_created_local, total_count_local

    while True:
        has_updates, latest_created, total_count = evaluate_changes()

        payload = {
            "has_updates": has_updates,
            "latest_created": latest_created.isoformat() if latest_created else None,
            "count": total_count,
        }

        if not wait_for_updates or has_updates or timezone.now() >= deadline:
            return JsonResponse(payload)

        time.sleep(1)


@method_decorator(login_required, name="dispatch")
class AppointmentActionView(View):
    def post(self, request, pk):
        appointment = get_object_or_404(Appointment, pk=pk)
        user = request.user

        # 🔒 Проверка прав
        is_super = user.is_superuser
        profile = getattr(user, "profile", None)
        is_salon_admin = bool(profile and profile.is_salon_admin and profile.salon)
        owns_appointment = is_salon_admin and profile.salon == appointment.stylist.salon if profile else False
        stylist_profile = getattr(user, "stylist_profile", None)
        is_stylist_owner = bool(stylist_profile and stylist_profile == appointment.stylist)

        if not (is_super or owns_appointment or is_stylist_owner):
            return HttpResponseForbidden("Недостаточно прав для изменения этой записи.")

        # Действия
        action = request.POST.get("action")

        if action == "confirm":
            appointment.status = Appointment.Status.CONFIRMED
            updates = appointment.update_payment_status_for_status(Appointment.Status.CONFIRMED)
            update_fields = ['status'] + updates
            appointment.save(update_fields=update_fields)

        elif action == "cancel":
            appointment.status = Appointment.Status.CANCELLED
            updates = appointment.update_payment_status_for_status(Appointment.Status.CANCELLED)
            update_fields = ['status'] + updates
            appointment.save(update_fields=update_fields)
            return JsonResponse({"status": "ok", "action": action})

        elif action == "done":
            appointment.status = Appointment.Status.DONE
            updates = appointment.update_payment_status_for_status(Appointment.Status.DONE)
            update_fields = ['status'] + updates
            appointment.save(update_fields=update_fields)

        else:
            return JsonResponse(
                {"status": "error", "message": "Недопустимое действие."}, status=400
            )

        return JsonResponse({"status": "ok", "action": action})

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
    appointments_qs = (
        Appointment.objects
        .select_related("stylist", "stylist__salon", "payment_card")
        .prefetch_related("services__stylist_service__salon_service__service")
        .filter(customer=request.user)
        .order_by("-start_time")
    )

    upcoming_appointment = (
        appointments_qs
        .filter(start_time__gte=now())
        .order_by("start_time")
        .first()
    )

    profile_form = ProfileUpdateForm(request.user)

    if request.method == "POST":
        if request.POST.get("profile_form"):
            profile_form = ProfileUpdateForm(request.user, request.POST)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Профиль обновлён.")
                return redirect('my_appointments')
        elif request.POST.get("payment_action"):
            appointment_id = request.POST.get("appointment_id")
            appointment = get_object_or_404(
                Appointment,
                id=appointment_id,
                customer=request.user,
            )

            action = request.POST.get("payment_action")

            if action == "change_method":
                if appointment.status in {Appointment.Status.CANCELLED, Appointment.Status.DONE}:
                    messages.error(request, "Изменение способа оплаты недоступно для этой записи.")
                    return redirect('my_appointments')

                if appointment.payment_receipt:
                    messages.error(
                        request,
                        "После загрузки чека изменить способ оплаты нельзя.",
                    )
                    return redirect('my_appointments')

                form = AppointmentPaymentMethodForm(request.POST, appointment=appointment)
                if form.is_valid():
                    method = form.cleaned_data["payment_method"]
                    updates = set()

                    if method == Appointment.PaymentMethod.CASH:
                        if appointment.payment_method != Appointment.PaymentMethod.CASH:
                            appointment.payment_method = Appointment.PaymentMethod.CASH
                            updates.add('payment_method')
                        if appointment.payment_status != Appointment.PaymentStatus.NOT_REQUIRED:
                            appointment.payment_status = Appointment.PaymentStatus.NOT_REQUIRED
                            updates.add('payment_status')
                        if appointment.payment_card_id:
                            appointment.payment_card = None
                            updates.add('payment_card')
                        if appointment.payment_receipt:
                            appointment.payment_receipt.delete(save=False)
                            appointment.payment_receipt = None
                            appointment.receipt_uploaded_at = None
                            updates.update({'payment_receipt', 'receipt_uploaded_at'})
                        if any([
                            appointment.refund_cardholder_name,
                            appointment.refund_card_number,
                            appointment.refund_card_type,
                            appointment.refund_requested_at,
                        ]):
                            appointment.refund_cardholder_name = ''
                            appointment.refund_card_number = ''
                            appointment.refund_card_type = ''
                            appointment.refund_requested_at = None
                            updates.update({
                                'refund_cardholder_name',
                                'refund_card_number',
                                'refund_card_type',
                                'refund_requested_at',
                            })
                    else:
                        salon = getattr(appointment.stylist, 'salon', None)
                        active_card = salon.get_active_payment_card() if salon else None
                        if not active_card:
                            messages.error(request, "У салона нет активной карты для оплаты.")
                            return redirect('my_appointments')

                        if appointment.payment_method != Appointment.PaymentMethod.CARD:
                            appointment.payment_method = Appointment.PaymentMethod.CARD
                            updates.add('payment_method')

                        if appointment.payment_card_id != active_card.id:
                            appointment.payment_card = active_card
                            updates.add('payment_card')

                        new_status = (
                            Appointment.PaymentStatus.AWAITING_PAYMENT
                            if appointment.status == Appointment.Status.CONFIRMED
                            else Appointment.PaymentStatus.PENDING
                        )
                        if appointment.payment_status != new_status:
                            appointment.payment_status = new_status
                            updates.add('payment_status')

                    if updates:
                        appointment.save(update_fields=sorted(updates))
                    messages.success(request, "Способ оплаты обновлён.")
                else:
                    for error in form.errors.get('payment_method', []):
                        messages.error(request, error)

                return redirect('my_appointments')

            elif action == "upload_receipt":
                if appointment.payment_method != Appointment.PaymentMethod.CARD:
                    messages.error(request, "Для этой записи не требуется загрузка чека.")
                    return redirect('my_appointments')

                if appointment.payment_receipt:
                    messages.error(request, "Чек уже загружен и ожидает проверки.")
                    return redirect('my_appointments')

                if appointment.status != Appointment.Status.CONFIRMED:
                    messages.error(request, "Чек можно загрузить после подтверждения записи мастером.")
                    return redirect('my_appointments')

                if appointment.payment_status not in {Appointment.PaymentStatus.AWAITING_PAYMENT}:
                    messages.error(request, "Сейчас нельзя загрузить чек для этой записи.")
                    return redirect('my_appointments')

                form = AppointmentReceiptForm(request.POST, request.FILES)
                if form.is_valid():
                    receipt = form.cleaned_data['receipt']
                    appointment.payment_receipt = receipt
                    appointment.receipt_uploaded_at = timezone.now()
                    appointment.payment_status = Appointment.PaymentStatus.AWAITING_CONFIRMATION
                    appointment.save(update_fields=[
                        'payment_receipt',
                        'receipt_uploaded_at',
                        'payment_status',
                    ])
                    messages.success(request, "Чек успешно загружен и отправлен на проверку.")
                else:
                    for field_errors in form.errors.values():
                        for error in field_errors:
                            messages.error(request, error)

                return redirect('my_appointments')

            elif action == "provide_refund":
                if appointment.status != Appointment.Status.CANCELLED:
                    messages.error(request, "Возврат возможен только для отменённых записей.")
                    return redirect('my_appointments')

                if appointment.payment_method != Appointment.PaymentMethod.CARD:
                    messages.error(request, "Возврат доступен только для переводов на карту.")
                    return redirect('my_appointments')

                if appointment.payment_status == Appointment.PaymentStatus.REFUNDED:
                    messages.info(request, "Возврат уже выполнен, данные нельзя изменить.")
                    return redirect('my_appointments')

                form = AppointmentRefundForm(request.POST)
                if form.is_valid():
                    new_type = form.cleaned_data['refund_card_type']
                    new_holder = form.cleaned_data['refund_cardholder_name']
                    new_number = form.cleaned_data['refund_card_number']
                    updates = set()

                    if appointment.refund_card_type != new_type:
                        appointment.refund_card_type = new_type
                        updates.add('refund_card_type')

                    if appointment.refund_cardholder_name != new_holder:
                        appointment.refund_cardholder_name = new_holder
                        updates.add('refund_cardholder_name')

                    if appointment.refund_card_number != new_number:
                        appointment.refund_card_number = new_number
                        updates.add('refund_card_number')

                    if appointment.payment_status != Appointment.PaymentStatus.REFUND_REQUESTED:
                        appointment.payment_status = Appointment.PaymentStatus.REFUND_REQUESTED
                        updates.add('payment_status')

                    if updates:
                        appointment.refund_requested_at = timezone.now()
                        updates.add('refund_requested_at')
                        appointment.save(update_fields=sorted(updates))
                    messages.success(request, "Данные для возврата сохранены. Мы сообщим, когда перевод будет выполнен.")
                else:
                    for field_errors in form.errors.values():
                        for error in field_errors:
                            messages.error(request, error)

                return redirect('my_appointments')

    appointments = list(appointments_qs)
    for appointment in appointments:
        salon = getattr(appointment.stylist, 'salon', None)
        appointment.active_payment_card = salon.get_active_payment_card() if salon else None
        if appointment.active_payment_card:
            available_payment_method_choices = list(Appointment.PaymentMethod.choices)
        else:
            available_payment_method_choices = [
                choice
                for choice in Appointment.PaymentMethod.choices
                if choice[0] != Appointment.PaymentMethod.CARD
            ]
        appointment.payment_method_choices = available_payment_method_choices
        appointment.can_change_payment_method = (
            appointment.status not in {Appointment.Status.CANCELLED, Appointment.Status.DONE}
            and not appointment.payment_receipt
            and len(appointment.payment_method_choices) > 1
        )
        appointment.show_card_details = (
            appointment.payment_method == Appointment.PaymentMethod.CARD
            and appointment.payment_status == Appointment.PaymentStatus.AWAITING_PAYMENT
            and appointment.status == Appointment.Status.CONFIRMED
            and appointment.active_payment_card is not None
        )
        appointment.can_upload_receipt = (
            appointment.payment_method == Appointment.PaymentMethod.CARD
            and appointment.status == Appointment.Status.CONFIRMED
            and appointment.payment_status == Appointment.PaymentStatus.AWAITING_PAYMENT
            and not appointment.payment_receipt
        )
        appointment.can_provide_refund_details = (
            appointment.status == Appointment.Status.CANCELLED
            and appointment.payment_method == Appointment.PaymentMethod.CARD
            and appointment.payment_status in {
                Appointment.PaymentStatus.REFUND_REQUESTED,
                Appointment.PaymentStatus.PAID,
                Appointment.PaymentStatus.AWAITING_CONFIRMATION,
            }
        )
        appointment.needs_refund_details = (
            appointment.can_provide_refund_details and not appointment.refund_card_number
        )
        appointment.can_edit_refund_details = (
            appointment.can_provide_refund_details
            and appointment.payment_status != Appointment.PaymentStatus.REFUNDED
        )

    status_counts = Counter(a.status for a in appointments)
    status_summary = []
    status_meta = [
        (
            Appointment.Status.PENDING,
            "Ожидают подтверждения",
            "pending",
            "bi bi-hourglass-split",
        ),
        (
            Appointment.Status.CONFIRMED,
            "Подтверждено",
            "confirmed",
            "bi bi-check2-circle",
        ),
        (
            Appointment.Status.DONE,
            "Завершено",
            "done",
            "bi bi-stars",
        ),
        (
            Appointment.Status.CANCELLED,
            "Отменено",
            "canceled",
            "bi bi-x-octagon",
        ),
    ]

    for status, label, card_class, icon_class in status_meta:
        status_summary.append({
            "status": status,
            "count": status_counts.get(status, 0),
            "label": label,
            "card_class": card_class,
            "icon_class": icon_class,
        })

    favorite_salons = [
        favorite.salon
        for favorite in FavoriteSalon.objects.select_related('salon', 'salon__city').filter(user=request.user)
    ]
    for salon in favorite_salons:
        rating = salon.average_rating() or 0
        salon.rating_value = round(rating, 1)

    return render(request, "my_appointments.html", {
        "appointments": appointments,
        "now": now(),
        "upcoming_appointment": upcoming_appointment,
        "profile_form": profile_form,
        "payment_method_choices": Appointment.PaymentMethod.choices,
        "card_type_choices": SalonPaymentCard.CARD_TYPE_CHOICES,
        "status_summary": status_summary,
        "favorite_salons": favorite_salons,
    })

@login_required
def cancel_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, customer=request.user)

    if appointment.status not in [Appointment.Status.DONE]:
        appointment.status = Appointment.Status.CANCELLED
        updates = appointment.update_payment_status_for_status(Appointment.Status.CANCELLED)
        update_fields = ['status']
        update_fields.extend(updates)
        appointment.save(update_fields=update_fields)
        messages.success(request, "Запись отмечена как отменённая.")
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
    tomorrow = today + timedelta(days=1)

    appointments_qs = (
        Appointment.objects
        .filter(stylist=stylist)
        .select_related("customer", "payment_card")
        .prefetch_related(
            Prefetch(
                "services",
                queryset=AppointmentService.objects.select_related(
                    "stylist_service__salon_service__service"
                )
            )
        )
        .order_by("-start_time")
    )

    appointments = list(appointments_qs)
    grouped_appointments = group_appointments_by_date(appointments)
    latest_activity = get_latest_activity_timestamp(appointments)
    latest_created_iso = latest_activity.isoformat() if latest_activity else ""

    cash_total = sum(
        a.get_total_price() for a in appointments if a.status == Appointment.Status.DONE
    )
    cash_today = sum(
        a.get_total_price()
        for a in appointments
        if a.status == Appointment.Status.DONE and a.start_time.date() == today
    )

    default_visible_dates = [
        yesterday.isoformat(),
        today.isoformat(),
        tomorrow.isoformat(),
    ]

    calendar_summary = build_calendar_summary(appointments)

    context = {
        "grouped_appointments": grouped_appointments,
        "appointments": appointments,
        "cash_total": cash_total,
        "cash_today": cash_today,
        "today": today,
        "default_visible_dates_json": json.dumps(default_visible_dates),
        "calendar_summary_json": json.dumps(calendar_summary),
        "latest_created_iso": latest_created_iso,
        "total_cash": cash_today,
        "refund_card_type_choices": SalonPaymentCard.CARD_TYPE_CHOICES,
        "stylist": stylist,
    }

    return render(request, "stylist_dashboard.html", context)


@login_required
@require_GET
def stylist_dashboard_ajax(request):
    try:
        stylist = request.user.stylist_profile
    except Stylist.DoesNotExist:
        return JsonResponse({"html": ""})

    today = now().date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    appointments_qs = (
        Appointment.objects
        .filter(stylist=stylist)
        .select_related("customer", "payment_card")
        .prefetch_related(
            Prefetch(
                "services",
                queryset=AppointmentService.objects.select_related(
                    "stylist_service__salon_service__service"
                )
            )
        )
        .order_by("-start_time")
    )

    appointments = list(appointments_qs)
    grouped_appointments = group_appointments_by_date(appointments)
    latest_activity = get_latest_activity_timestamp(appointments)
    default_visible_dates = [
        yesterday.isoformat(),
        today.isoformat(),
        tomorrow.isoformat(),
    ]
    calendar_summary = build_calendar_summary(appointments)

    context = {
        "grouped_appointments": grouped_appointments,
        "csrf_token": get_token(request),
        "show_stylist_column": False,
        "refund_card_type_choices": SalonPaymentCard.CARD_TYPE_CHOICES,
        "stylist": stylist,
    }

    html = render_to_string("partials/appointments_table_rows.html", context)
    return JsonResponse({
        "html": html,
        "calendar": calendar_summary,
        "default_visible_dates": default_visible_dates,
        "today": today.isoformat(),
        "latest_created": latest_activity.isoformat() if latest_activity else None,
        "count": len(appointments),
    })


@login_required
@require_GET
def stylist_dashboard_updates(request):
    try:
        stylist = request.user.stylist_profile
    except Stylist.DoesNotExist:
        return JsonResponse({"has_updates": False, "latest_created": None, "count": 0})

    today = now().date()
    yesterday = today - timedelta(days=1)

    appointments_qs = Appointment.objects.filter(
        stylist=stylist,
        start_time__date__gte=yesterday,
    )

    wait_for_updates = request.GET.get("wait") in {"1", "true", "True"}

    timeout_seconds = 25
    requested_timeout = request.GET.get("timeout")
    if requested_timeout:
        try:
            timeout_seconds = max(5, min(60, int(requested_timeout)))
        except (TypeError, ValueError):
            timeout_seconds = 25

    deadline = timezone.now() + timedelta(seconds=timeout_seconds) if wait_for_updates else None

    since_raw = request.GET.get("since")
    last_count_raw = request.GET.get("count")

    def evaluate_changes():
        totals_local = appointments_qs.aggregate(
            latest_created=Max("created_at"),
            latest_receipt_uploaded=Max("receipt_uploaded_at"),
            latest_refund_receipt_uploaded=Max("refund_receipt_uploaded_at"),
            latest_refund_requested=Max("refund_requested_at"),
            total_count=Count("id"),
        )
        latest_created_local = max(
            (
                ts
                for ts in (
                    totals_local.get("latest_created"),
                    totals_local.get("latest_receipt_uploaded"),
                    totals_local.get("latest_refund_receipt_uploaded"),
                    totals_local.get("latest_refund_requested"),
                )
                if ts is not None
            ),
            default=None,
        )
        total_count_local = totals_local.get("total_count", 0) or 0

        has_updates_local = False

        if since_raw:
            parsed_since = parse_datetime(since_raw)
            if parsed_since is not None:
                if timezone.is_naive(parsed_since):
                    parsed_since = timezone.make_aware(parsed_since)
                if latest_created_local and latest_created_local > parsed_since:
                    has_updates_local = True

        if not has_updates_local and last_count_raw is not None:
            try:
                last_count_value = int(last_count_raw)
            except (TypeError, ValueError):
                last_count_value = None

            if last_count_value is not None and total_count_local != last_count_value:
                has_updates_local = True

        return has_updates_local, latest_created_local, total_count_local

    while True:
        has_updates, latest_created, total_count = evaluate_changes()

        payload = {
            "has_updates": has_updates,
            "latest_created": latest_created.isoformat() if latest_created else None,
            "count": total_count,
        }

        if not wait_for_updates or has_updates or timezone.now() >= deadline:
            return JsonResponse(payload)

        time.sleep(1)


@require_POST
@login_required
def appointment_update_status(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    # Проверка, что текущий пользователь — это мастер этой записи
    if appointment.stylist.user != request.user:
        return HttpResponseForbidden("Вы не имеете доступа к этой записи")

    new_status = request.POST.get("status")

    if new_status == 'DELETE':
        appointment.status = Appointment.Status.CANCELLED
        updates = appointment.update_payment_status_for_status(Appointment.Status.CANCELLED)
        update_fields = ['status'] + updates
        appointment.save(update_fields=update_fields)
    elif new_status in [s.value for s in Appointment.Status]:
        appointment.status = new_status
        updates = appointment.update_payment_status_for_status(new_status)
        update_fields = ['status'] + updates
        appointment.save(update_fields=update_fields)

    return redirect("stylist_dashboard")


@require_POST
@login_required
def appointment_payment_action(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)

    user = request.user
    profile = getattr(user, "profile", None)
    stylist_profile = getattr(user, "stylist_profile", None)

    is_superuser = user.is_superuser
    is_salon_admin = bool(
        profile and profile.is_salon_admin and profile.salon and profile.salon == appointment.stylist.salon
    )
    is_stylist_owner = bool(stylist_profile and stylist_profile == appointment.stylist)

    if not (is_superuser or is_salon_admin or is_stylist_owner):
        return HttpResponseForbidden("Недостаточно прав для обновления статуса оплаты.")

    action = request.POST.get("payment_action")
    update_fields = []
    success_message = None

    if appointment.payment_method != Appointment.PaymentMethod.CARD:
        messages.error(request, "Для этой записи не настроена оплата через карту.")
        return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')

    if action == "confirm":
        appointment.payment_status = Appointment.PaymentStatus.PAID
        update_fields.append('payment_status')
        success_message = "Оплата подтверждена."
    elif action == "mark_refunded":
        if appointment.status != Appointment.Status.CANCELLED:
            messages.error(request, "Возврат можно завершить только для отменённых записей.")
            return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')

        if not all([
            appointment.refund_card_number,
            appointment.refund_cardholder_name,
            appointment.refund_card_type,
        ]):
            messages.error(
                request,
                "Нельзя завершить возврат: клиент ещё не указал реквизиты карты для перевода.",
            )
            return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')

        form = AppointmentRefundCompleteForm(request.POST, request.FILES)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')

        refund_receipt = form.cleaned_data.get('refund_receipt')
        if refund_receipt:
            if appointment.refund_receipt:
                appointment.refund_receipt.delete(save=False)
            appointment.refund_receipt = refund_receipt
            appointment.refund_receipt_uploaded_at = timezone.now()
            update_fields.extend(['refund_receipt', 'refund_receipt_uploaded_at'])

        appointment.payment_status = Appointment.PaymentStatus.REFUNDED
        update_fields.append('payment_status')
        success_message = "Возврат отмечен как выполненный."
    elif action == "request_refund":
        appointment.payment_status = Appointment.PaymentStatus.REFUND_REQUESTED
        update_fields.append('payment_status')
        if not appointment.refund_requested_at:
            appointment.refund_requested_at = timezone.now()
            update_fields.append('refund_requested_at')
        success_message = "Статус возврата обновлён."
    else:
        messages.error(request, "Неизвестное действие оплаты.")
        return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')

    if update_fields:
        unique_fields = list(dict.fromkeys(update_fields))
        appointment.save(update_fields=unique_fields)

    if success_message:
        messages.success(request, success_message)

    return redirect(request.META.get('HTTP_REFERER') or 'stylist_dashboard')


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
        guest_phone_input = request.POST.get('guest_phone', '').strip()

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
        if (
            Appointment.objects
            .filter(
                stylist=stylist,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .exists()
        ):
            messages.error(request, "Мастер занят в это время.")
            return redirect('manual_appointment')

        if guest_phone_input and not PHONE_INPUT_RE.match(guest_phone_input):
            messages.error(request, "Введите телефон в формате 93-123-45-67.")
            return redirect('manual_appointment')

        guest_phone = normalize_uzbek_phone(guest_phone_input) if guest_phone_input else ''

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
        guest_phone_input = request.POST.get('guest_phone', '').strip()

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

        overlap = (
            Appointment.objects
            .filter(
                stylist=stylist,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .exists()
        )

        if overlap:
            messages.error(request, "Выбранное время занято.")
            return redirect('stylist_manual_appointment')

        if guest_phone_input and not PHONE_INPUT_RE.match(guest_phone_input):
            messages.error(request, "Введите телефон в формате 93-123-45-67.")
            return redirect('stylist_manual_appointment')

        guest_phone = normalize_uzbek_phone(guest_phone_input) if guest_phone_input else ''

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
                overlap = (
                    Appointment.objects
                    .filter(
                        stylist=stylist,
                        start_time__lt=st_aware + duration,
                        end_time__gt=st_aware,
                    )
                    .exclude(status=Appointment.Status.CANCELLED)
                    .exists()
                )

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
    average_ticket = 0
    average_day_revenue = 0
    worked_days = 0
    period_label = None

    stylist_name = (
        stylist.user.get_full_name()
        if hasattr(stylist, "user") and stylist.user.get_full_name()
        else getattr(stylist, "user", request.user).get_username()
    )

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
            period_label = f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"

            for a in report_appointments:
                total_cash += a.get_total_price()

            worked_days = len({a.start_time.date() for a in report_appointments})

            if total_clients:
                average_ticket = total_cash / total_clients

            if worked_days:
                average_day_revenue = total_cash / worked_days

        except ValueError:
            pass

    context = {
        "report_appointments": report_appointments,
        "total_cash": total_cash,
        "total_clients": total_clients,
        "average_ticket": average_ticket,
        "average_day_revenue": average_day_revenue,
        "worked_days": worked_days,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": period_label,
        "stylist_name": stylist_name,
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
    payment_card_form = None
    payment_cards = SalonPaymentCard.objects.none()
    product_form = None
    salon_products = None

    stylists = []
    stylists_map = {}
    profile_salon = getattr(profile, 'salon', None)
    subscription_expires_at = None
    subscription_is_active = False
    if profile_salon:
        subscription_expires_at = profile_salon.subscription_expires_at
        subscription_is_active = profile_salon.is_subscription_active

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
        payment_card_form = SalonPaymentCardForm()
        payment_cards = SalonPaymentCard.objects.filter(salon=profile.salon).order_by('-is_active', '-updated_at')
        salon_products = list(
            SalonProduct.objects.filter(salon=profile.salon).order_by('-created_at')
        )
        for product in salon_products:
            product.update_form = SalonProductForm(instance=product)
        product_form = SalonProductForm()

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
        if selected_stylist and selected_stylist.salon:
            payment_cards = SalonPaymentCard.objects.filter(salon=selected_stylist.salon).order_by('-is_active', '-updated_at')

    stylist = selected_stylist

    def serialize_working_hours_for(target_stylist):
        return [
            {
                'id': w.id,
                'weekday': w.weekday,
                'start': w.start_time.strftime('%H:%M'),
                'end': w.end_time.strftime('%H:%M'),
                'breaks': [
                    {'start': b.start_time.strftime('%H:%M'), 'end': b.end_time.strftime('%H:%M')}
                    for b in w.breaks.all()
                ],
            }
            for w in WorkingHour.objects.filter(stylist=target_stylist).prefetch_related('breaks')
        ]

    def serialize_salon_service(salon_service):
        return {
            'id': salon_service.id,
            'name': salon_service.service.name,
            'category': salon_service.category.name if salon_service.category else '—',
            'duration_minutes': int(salon_service.duration.total_seconds() // 60),
            'position': salon_service.position,
            'is_active': salon_service.is_active,
        }

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
                new_service = salon_service_form.save()
                messages.success(request, 'Услуга добавлена в салон.')
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'service': serialize_salon_service(new_service),
                    })
                return redirect(reverse('stylist_dayoff'))
            elif request.headers.get('x-requested-with') == 'XMLHttpRequest':
                error_data = {
                    field: [e['message'] for e in errors]
                    for field, errors in salon_service_form.errors.get_json_data().items()
                }
                return JsonResponse({'success': False, 'errors': error_data})
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
        elif profile.is_salon_admin and form_type == 'payment_card_add':
            payment_card_form = SalonPaymentCardForm(request.POST)
            if payment_card_form.is_valid():
                card = payment_card_form.save(commit=False)
                card.salon = profile.salon
                if card.is_active:
                    SalonPaymentCard.objects.filter(salon=profile.salon).update(is_active=False)
                card.save()
                messages.success(request, 'Карта добавлена.')
                return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'payment_card_toggle':
            card_id = request.POST.get('card_id')
            card = get_object_or_404(SalonPaymentCard, id=card_id, salon=profile.salon)
            target_state = request.POST.get('target_state') == '1'
            if target_state:
                SalonPaymentCard.objects.filter(salon=profile.salon).exclude(id=card.id).update(is_active=False)
            card.is_active = target_state
            card.save(update_fields=['is_active', 'updated_at'])
            if target_state:
                messages.success(request, 'Карта отмечена как активная.')
            else:
                messages.success(request, 'Карта переведена в неактивное состояние.')
            return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'payment_card_delete':
            card_id = request.POST.get('card_id')
            card = get_object_or_404(SalonPaymentCard, id=card_id, salon=profile.salon)
            card.delete()
            messages.success(request, 'Карта удалена.')
            return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'product_add':
            product_form = SalonProductForm(request.POST, request.FILES)
            if product_form.is_valid():
                product = product_form.save(commit=False)
                product.salon = profile.salon
                product.save()
                messages.success(request, 'Товар добавлен в каталог салона.')
                return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'product_update':
            product_id = request.POST.get('product_id')
            product = get_object_or_404(SalonProduct, id=product_id, salon=profile.salon)
            update_form = SalonProductForm(request.POST, request.FILES, instance=product)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, 'Информация о товаре обновлена.')
                return redirect(reverse('stylist_dayoff'))
            else:
                if isinstance(salon_products, list):
                    for p in salon_products:
                        if p.id == product.id:
                            p.update_form = update_form
                            break
                else:
                    product.update_form = update_form
        elif profile.is_salon_admin and form_type == 'product_toggle':
            product_id = request.POST.get('product_id')
            product = get_object_or_404(SalonProduct, id=product_id, salon=profile.salon)
            product.is_active = not product.is_active
            product.save(update_fields=['is_active', 'updated_at'])
            state = 'активен' if product.is_active else 'выключен'
            messages.success(request, f'Статус товара обновлён: {state}.')
            return redirect(reverse('stylist_dayoff'))
        elif profile.is_salon_admin and form_type == 'product_delete':
            product_id = request.POST.get('product_id')
            product = get_object_or_404(SalonProduct, id=product_id, salon=profile.salon)
            product.delete()
            messages.success(request, 'Товар удалён из каталога.')
            return redirect(reverse('stylist_dayoff'))

        # Дальнейшие действия требуют выбранного стилиста
        if stylist is None and form_type not in {'stylist_add', 'salon_service_add', 'salon_service_delete', 'salon_service_update', 'stylist_update', 'stylist_delete', 'product_add', 'product_update', 'product_delete', 'product_toggle'}:
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

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                blocks = StylistDayOff.objects.filter(stylist=stylist).order_by('-date', '-from_time')
                blocks_html = render_to_string(
                    'partials/_dayoff_table.html',
                    {'blocks': blocks, 'selected_stylist_id': selected_stylist_id},
                    request=request,
                )
                return JsonResponse({'success': True, 'blocks_html': blocks_html})

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
                error_msg = 'Неверный формат даты или времени.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    blocks = StylistDayOff.objects.filter(stylist=stylist).order_by('-date', '-from_time')
                    blocks_html = render_to_string(
                        'partials/_dayoff_table.html',
                        {'blocks': blocks, 'selected_stylist_id': selected_stylist_id},
                        request=request,
                    )
                    return JsonResponse({'success': True, 'blocks_html': blocks_html})

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

            # ✅ ЕСЛИ AJAX — возвращаем JSON
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'working_hours': serialize_working_hours_for(stylist),
                })

            # ⬇️ fallback (если вдруг обычная отправка)
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
            except (ValueError, TypeError):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Неверный формат времени'})
                messages.error(request, 'Неверный формат времени.')
            except ValidationError as exc:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': exc.messages[0]})
                messages.error(request, exc.messages[0])

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # возвращаем обновлённый список рабочих часов для JS
                return JsonResponse({'success': True, 'working_hours': serialize_working_hours_for(stylist)})

            # fallback для обычного POST
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

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'working_hours': serialize_working_hours_for(stylist)})

        # Удаление рабочего интервала
        elif form_type == 'workinghour_delete':
            wh_id = request.POST.get('workinghour_id')
            wh = get_object_or_404(WorkingHour, id=wh_id, stylist=stylist)
            wh.delete()

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # Возвращаем обновлённый список рабочих часов
                return JsonResponse({'success': True, 'working_hours': serialize_working_hours_for(stylist)})

            # fallback для обычного POST
            return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

        elif profile.is_salon_admin and form_type == 'stylist_price_update':
            salon_service_id = request.POST.get('salon_service_id')
            price_raw = (request.POST.get('price') or '').replace(',', '.').strip()

            if not salon_service_id:
                error_message = 'Не выбрана услуга.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
                return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

            if price_raw == '':
                StylistService.objects.filter(
                    stylist=stylist, salon_service_id=salon_service_id
                ).delete()
                success_payload = {
                    'success': True,
                    'price': None,
                }
                messages.success(request, 'Цена удалена для выбранной услуги.')
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(success_payload)
                return redirect(f'{reverse("stylist_dayoff")}?stylist_id={selected_stylist_id}')

            try:
                price_value = Decimal(price_raw)
                if price_value < 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError):
                error_message = 'Введите корректную цену.'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
            else:
                StylistService.objects.update_or_create(
                    stylist=stylist,
                    salon_service_id=salon_service_id,
                    defaults={'price': price_value},
                )
                messages.success(request, 'Цена сохранена.')
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'price': str(price_value),
                    })

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

    context = {
        'blocks': blocks,
        'working_hours': working_hours,
        'stylists': stylists,
        'selected_stylist_id': selected_stylist_id,
        'selected_stylist': stylist,
        'WEEKDAYS': WEEKDAYS,
        'stylist_creation_form': stylist_creation_form,
        'salon_service_form': salon_service_form,
        'salon_services': salon_services,
        'payment_cards': payment_cards,
        'payment_card_form': payment_card_form,
        'salon_products': salon_products,
        'product_form': product_form,
        'is_salon_admin': profile.is_salon_admin,
        'subscription_expires_at': subscription_expires_at,
        'subscription_is_active': subscription_is_active,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.GET.get('partial') == 'blocks':
        blocks_html = render_to_string(
            'partials/_dayoff_table.html',
            {'blocks': blocks, 'selected_stylist_id': selected_stylist_id},
            request=request,
        )
        return JsonResponse({'blocks_html': blocks_html})

    return render(request, 'stylist_dayoff_form.html', context)

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

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        blocks = StylistDayOff.objects.filter(stylist_id=stylist_id).order_by('-date', '-from_time')
        blocks_html = render_to_string(
            'partials/_dayoff_table.html',
            {'blocks': blocks, 'selected_stylist_id': stylist_id},
            request=request,
        )
        return JsonResponse({'success': True, 'blocks_html': blocks_html})

    return redirect(f'{reverse("stylist_dayoff")}?stylist_id={stylist_id}')

@login_required
def ajax_stylist_data(request, stylist_id):
    stylist = get_object_or_404(
        Stylist, id=stylist_id, salon=request.user.profile.salon
    )

    services = []
    for ss in SalonService.objects.filter(salon=stylist.salon):
        price = StylistService.objects.filter(
            stylist=stylist, salon_service=ss
        ).values_list('price', flat=True).first()

        services.append({
            'id': ss.id,
            'name': ss.service.name,
            'duration': int(ss.duration.total_seconds() // 60),
            'price': price
        })

    working_hours = []
    for wh in WorkingHour.objects.filter(stylist=stylist).prefetch_related('breaks'):
        working_hours.append({
            'id': wh.id,
            'weekday': wh.weekday,  # ✅ число 0–6
            'start': wh.start_time.strftime('%H:%M'),
            'end': wh.end_time.strftime('%H:%M'),
            'breaks': [
                {
                    'start': b.start_time.strftime('%H:%M'),
                    'end': b.end_time.strftime('%H:%M')
                } for b in wh.breaks.all()
            ]
        })

    return JsonResponse({
        'services': services,
        'working_hours': working_hours
    })

@login_required
@require_POST
def ajax_update_price(request):
    stylist = get_object_or_404(
        Stylist, id=request.POST['stylist_id'],
        salon=request.user.profile.salon
    )

    price = request.POST.get('price')
    salon_service_id = request.POST['salon_service_id']

    if price == '':
        StylistService.objects.filter(
            stylist=stylist, salon_service_id=salon_service_id
        ).delete()
    else:
        StylistService.objects.update_or_create(
            stylist=stylist,
            salon_service_id=salon_service_id,
            defaults={'price': Decimal(price)}
        )

    return JsonResponse({'status': 'ok'})
