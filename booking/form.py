from collections import defaultdict
from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from PIL import Image

from users.models import Profile

from .models import (
    Review,
    Stylist,
    StylistLevel,
    Service,
    Category,
    SalonService,
    SalonPaymentCard,
    Appointment,
)


def validate_stylist_photo(photo):
    """Проверить изображение стилиста на размер и пропорции."""
    if not photo:
        return photo

    max_size_bytes = 4 * 1024 * 1024  # 4 МБ
    if photo.size > max_size_bytes:
        raise forms.ValidationError('Размер фото должен быть не более 4 МБ.')

    try:
        image = Image.open(photo)
        image.load()
        width, height = image.size
    except Exception:
        raise forms.ValidationError('Не удалось прочитать изображение. Загрузите корректный файл.')
    finally:
        if hasattr(photo, 'seek'):
            photo.seek(0)

    if width != height:
        raise forms.ValidationError('Фото должно быть квадратным (ширина должна равняться высоте).')

    return photo

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Ваш отзыв (необязательно)',
                'rows': 3,
            }),
        }


class StylistCreationForm(UserCreationForm):
    first_name = forms.CharField(label='Имя', max_length=150, required=True)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    telegram_chat_id = forms.IntegerField(
        label='Telegram chat_id', required=False,
        help_text='Укажите chat_id или оставьте поле пустым.'
    )
    level = forms.ModelChoiceField(
        label='Уровень', queryset=StylistLevel.objects.all(), required=False
    )
    photo = forms.ImageField(
        label='Фото',
        required=True,
        help_text='Фото должно быть квадратным и весить не более 4 МБ.',
    )
    bio = forms.CharField(
        label='О себе',
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        required=False,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            'username',
            'first_name',
            'last_name',
            'phone',
            'password1',
            'password2',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            css_class = 'form-control'
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            field.widget.attrs.setdefault('class', css_class)

        # Textarea already has styling above, ensure passwords styled too
        self.fields['password1'].widget.attrs.setdefault('class', 'form-control')
        self.fields['password2'].widget.attrs.setdefault('class', 'form-control')
        if 'photo' in self.fields:
            self.fields['photo'].widget.attrs.setdefault('accept', 'image/*')

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        return validate_stylist_photo(photo)

    def save(self, salon, commit=True):
        """Создать пользователя и привязать его к салону как мастера."""

        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')

        if commit:
            user.save()
            self.save_m2m()

        # Обновляем профиль пользователя
        profile = getattr(user, 'profile', None)
        if profile is None:
            profile = Profile.objects.create(user=user)

        profile.phone = self.cleaned_data.get('phone', '')
        profile.is_salon_admin = False
        profile.salon = salon
        profile.save()

        stylist = Stylist.objects.create(
            user=user,
            salon=salon,
            level=self.cleaned_data.get('level'),
            bio=self.cleaned_data.get('bio', ''),
        )

        stylist.telegram_chat_id = self.cleaned_data.get('telegram_chat_id')

        photo = self.cleaned_data.get('photo')
        if photo:
            stylist.avatar = photo
            stylist.save(update_fields=['avatar', 'telegram_chat_id'])
        else:
            stylist.save(update_fields=['telegram_chat_id'])

        return stylist


class StylistUpdateForm(forms.Form):
    username = forms.CharField(label='Логин', max_length=150, required=True)
    first_name = forms.CharField(label='Имя', max_length=150, required=True)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
    telegram_chat_id = forms.IntegerField(
        label='Telegram chat_id', required=False,
        help_text='Укажите chat_id или оставьте поле пустым.'
    )
    level = forms.ModelChoiceField(
        label='Уровень', queryset=StylistLevel.objects.all(), required=False
    )
    bio = forms.CharField(
        label='О себе',
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        required=False,
    )
    photo = forms.ImageField(
        label='Новое фото',
        required=False,
        help_text='Фото должно быть квадратным и весить не более 4 МБ.',
    )

    # === НОВЫЕ ПОЛЯ ===
    show_client_phone = forms.BooleanField(
        label='Показывать номер клиента в дашборде',
        required=False,
        widget=forms.CheckboxInput()
    )
    allow_cancel_appointment = forms.BooleanField(
        label='Разрешить отмену записей',
        required=False,
        widget=forms.CheckboxInput()
    )

    def __init__(self, *args, stylist=None, **kwargs):
        self.stylist = stylist
        initial = kwargs.get('initial', {}).copy()
        if stylist and not kwargs.get('data'):
            user = stylist.user
            profile = getattr(user, 'profile', None)
            initial.update({
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone': profile.phone if profile else '',
                'level': stylist.level,
                'bio': stylist.bio,
                'telegram_chat_id': stylist.telegram_chat_id,
                'show_client_phone': getattr(stylist, 'show_client_phone', True),
                'allow_cancel_appointment': getattr(stylist, 'allow_cancel_appointment', True),
            })
            kwargs['initial'] = initial

        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            else:
                field.widget.attrs.setdefault('class', 'form-control')

            if stylist:
                field.widget.attrs.setdefault('id', f'id_{field_name}_{stylist.id}')

        if 'photo' in self.fields:
            self.fields['photo'].widget.attrs.setdefault('accept', 'image/*')

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if not username:
            raise forms.ValidationError('Укажите логин пользователя.')

        queryset = User.objects.all()
        if self.stylist and self.stylist.user_id:
            queryset = queryset.exclude(pk=self.stylist.user_id)

        if queryset.filter(username=username).exists():
            raise forms.ValidationError('Пользователь с таким логином уже существует.')

        return username

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        return validate_stylist_photo(photo)

    def save(self):
        if not self.stylist:
            raise ValueError('Стилист не указан для обновления данных.')

        user = self.stylist.user
        user.username = self.cleaned_data['username']
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.save()

        profile = getattr(user, 'profile', None)
        if profile is None:
            profile = Profile.objects.create(user=user)

        profile.phone = self.cleaned_data.get('phone', '')
        profile.salon = self.stylist.salon
        profile.save()

        self.stylist.level = self.cleaned_data.get('level')
        self.stylist.bio = self.cleaned_data.get('bio', '')
        self.stylist.telegram_chat_id = self.cleaned_data.get('telegram_chat_id')

        # === СОХРАНЕНИЕ НОВЫХ ПОЛЕЙ ===
        self.stylist.show_client_phone = self.cleaned_data.get('show_client_phone', True)
        self.stylist.allow_cancel_appointment = self.cleaned_data.get('allow_cancel_appointment', True)

        photo = self.cleaned_data.get('photo')
        if photo:
            if self.stylist.avatar:
                self.stylist.avatar.delete(save=False)
            self.stylist.avatar = photo

        update_fields = ['level', 'bio', 'telegram_chat_id', 'show_client_phone', 'allow_cancel_appointment']
        if photo:
            update_fields.append('avatar')

        self.stylist.save(update_fields=update_fields)

        return self.stylist


class SalonServiceForm(forms.Form):
    TYPE_LABELS = {
        'male': 'Муж',
        'female': 'Жен',
        'both': 'Жен / Муж',
        '': 'Не указано',
    }
    TYPE_ORDER = ['female', 'male', 'both', '']

    service = forms.ModelChoiceField(
        label='Услуга', queryset=Service.objects.none(), required=True
    )
    category = forms.ModelChoiceField(
        label='Категория', queryset=Category.objects.none(), required=False
    )
    duration = forms.IntegerField(
        label='Длительность (мин)', min_value=5, initial=30, required=True
    )
    position = forms.IntegerField(label='Позиция', min_value=0, required=False)
    is_active = forms.BooleanField(label='Активна', required=False, initial=True)

    def __init__(self, salon, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.salon = salon

        used_services = salon.salon_services.values_list('service_id', flat=True)
        self.fields['service'].queryset = (
            Service.objects.filter(is_active=True)
            .exclude(id__in=used_services)
            .order_by('name')
        )
        service_field = self.fields['service']
        self._service_type_map = self._build_service_type_map(service_field.queryset)
        service_field.label_from_instance = self._service_label_from_instance
        category_field = self.fields['category']
        category_field.queryset = Category.objects.all().order_by('name')
        category_field.empty_label = 'Без категории'

        self._category_type_map = self._build_category_type_map(category_field.queryset)
        category_field.label_from_instance = self._category_label_from_instance

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            else:
                field.widget.attrs.setdefault('class', 'form-control')

    def _build_service_type_map(self, queryset):
        service_ids = list(queryset.values_list('id', flat=True))
        if not service_ids:
            return {}

        type_map = defaultdict(set)
        related_services = (
            SalonService.objects.filter(service_id__in=service_ids)
            .select_related('salon')
            .values_list('service_id', 'salon__type')
        )
        for service_id, salon_type in related_services:
            normalized_type = salon_type or ''
            type_map[service_id].add(normalized_type)

        return type_map

    def _build_category_type_map(self, queryset):
        category_ids = list(queryset.values_list('id', flat=True))
        if not category_ids:
            return {}

        type_map = defaultdict(set)
        related_categories = (
            SalonService.objects.filter(category_id__in=category_ids)
            .select_related('salon')
            .values_list('category_id', 'salon__type')
        )
        for category_id, salon_type in related_categories:
            normalized_type = salon_type or ''
            type_map[category_id].add(normalized_type)

        return type_map

    def _format_type_labels(self, type_keys):
        if not type_keys:
            return ''

        normalized_keys = {key or '' for key in type_keys}
        if 'both' in normalized_keys:
            return self.TYPE_LABELS['both']

        labels = []
        for type_key in self.TYPE_ORDER:
            if type_key in normalized_keys:
                labels.append(self.TYPE_LABELS[type_key])

        remaining = normalized_keys.difference(self.TYPE_ORDER)
        for key in sorted(remaining):
            labels.append(self.TYPE_LABELS.get(key, key))

        return ' / '.join(labels)

    def _service_label_from_instance(self, service):
        base_name = service.name
        type_keys = self._service_type_map.get(service.id)
        labels = self._format_type_labels(type_keys or set())
        if not labels:
            return base_name

        return f"{base_name} — ({labels})"

    def _category_label_from_instance(self, category):
        base_name = category.name
        type_keys = self._category_type_map.get(category.id)
        labels = self._format_type_labels(type_keys or set())
        if not labels:
            return base_name

        return f"{base_name} — ({labels})"

    def save(self):
        salon_service = SalonService.objects.create(
            salon=self.salon,
            service=self.cleaned_data['service'],
            category=self.cleaned_data.get('category'),
            duration=timedelta(minutes=self.cleaned_data['duration']),
            is_active=self.cleaned_data.get('is_active', True),
            position=self.cleaned_data.get('position') or 0,
        )

        return salon_service


class SalonServiceUpdateForm(forms.ModelForm):
    duration = forms.IntegerField(label='Длительность (мин)', min_value=5, required=True)

    class Meta:
        model = SalonService
        fields = ['category', 'duration', 'position', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.label_suffix = ''

        self.fields['category'].queryset = Category.objects.all().order_by('name')
        self.fields['category'].required = False
        self.fields['category'].empty_label = 'Без категории'
        self.fields['position'].required = False

        if self.instance and self.instance.pk and 'duration' not in self.initial:
            self.initial['duration'] = int(self.instance.duration.total_seconds() // 60)

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            else:
                field.widget.attrs.setdefault('class', 'form-control')

    def clean_duration(self):
        minutes = self.cleaned_data['duration']
        return timedelta(minutes=minutes)

    def clean_position(self):
        position = self.cleaned_data.get('position')
        if position is None:
            return 0
        return position


class SalonPaymentCardForm(forms.ModelForm):
    class Meta:
        model = SalonPaymentCard
        fields = [
            'card_type',
            'cardholder_name',
            'card_number',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_card_types = {'uzcard', 'humo'}
        card_type_field = self.fields['card_type']
        card_type_field.choices = [
            choice
            for choice in card_type_field.choices
            if choice[0] in allowed_card_types or choice[0] == ''
        ]

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                css_class = 'form-select'
            else:
                css_class = 'form-control'
            field.widget.attrs.setdefault('class', css_class)

    def clean_card_number(self):
        value = (self.cleaned_data.get('card_number') or '').replace(' ', '')
        if not value:
            raise forms.ValidationError('Введите номер карты салона.')
        if not value.isdigit():
            raise forms.ValidationError('Номер карты должен содержать только цифры.')
        return value


class AppointmentPaymentMethodForm(forms.Form):
    payment_method = forms.ChoiceField(choices=Appointment.PaymentMethod.choices)

    def __init__(self, *args, appointment: Appointment, **kwargs):
        self.appointment = appointment
        super().__init__(*args, **kwargs)
        self.fields['payment_method'].widget.attrs.setdefault('class', 'form-select form-select-sm')

    def clean_payment_method(self):
        method = self.cleaned_data['payment_method']
        if self.appointment.payment_receipt:
            raise forms.ValidationError(
                'После загрузки чека изменить способ оплаты нельзя.'
            )
        if method == Appointment.PaymentMethod.CARD:
            salon = getattr(self.appointment.stylist, 'salon', None)
            if not salon or not salon.get_active_payment_card():
                raise forms.ValidationError('У салона нет активной карты для оплаты.')
        return method


class AppointmentReceiptForm(forms.Form):
    receipt = forms.ImageField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['receipt'].widget.attrs.setdefault('class', 'form-control')
        self.fields['receipt'].widget.attrs.setdefault('accept', 'image/*')


class AppointmentRefundForm(forms.Form):
    refund_card_type = forms.ChoiceField(
        choices=SalonPaymentCard.CARD_TYPE_CHOICES,
        label='Тип карты',
    )
    refund_cardholder_name = forms.CharField(max_length=120, label='Имя владельца')
    refund_card_number = forms.CharField(max_length=32, label='Номер карты')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_refund_card_number(self):
        value = (self.cleaned_data.get('refund_card_number') or '').replace(' ', '')
        if not value:
            raise forms.ValidationError('Введите номер карты для возврата.')
        if not value.isdigit():
            raise forms.ValidationError('Номер карты для возврата должен содержать только цифры.')
        return value


class AppointmentRefundCompleteForm(forms.Form):
    refund_receipt = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['refund_receipt']
        field.widget.attrs.setdefault('class', 'form-control form-control-sm')
        field.widget.attrs.setdefault('accept', 'image/*')