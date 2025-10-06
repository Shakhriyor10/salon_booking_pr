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
)


def validate_stylist_photo(photo):
    """Проверить изображение стилиста на размер и пропорции."""
    if not photo:
        return photo

    max_size_bytes = 1024 * 1024  # 1 МБ
    if photo.size > max_size_bytes:
        raise forms.ValidationError('Размер фото должен быть не более 1 МБ.')

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
    level = forms.ModelChoiceField(
        label='Уровень', queryset=StylistLevel.objects.all(), required=False
    )
    photo = forms.ImageField(
        label='Фото',
        required=False,
        help_text='Фото должно быть квадратным и весить не более 1 МБ.',
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

        photo = self.cleaned_data.get('photo')
        if photo:
            stylist.avatar = photo
            stylist.save(update_fields=['avatar'])

        return stylist


class StylistUpdateForm(forms.Form):
    username = forms.CharField(label='Логин', max_length=150, required=True)
    first_name = forms.CharField(label='Имя', max_length=150, required=True)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)
    phone = forms.CharField(label='Телефон', max_length=20, required=False)
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
        help_text='Фото должно быть квадратным и весить не более 1 МБ.',
    )
    remove_photo = forms.BooleanField(
        label='Удалить текущее фото',
        required=False,
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
            raise ValueError('Стлист не указан для обновления данных.')

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

        photo = self.cleaned_data.get('photo')
        remove_photo = self.cleaned_data.get('remove_photo')

        if photo:
            self.stylist.avatar = photo
        elif remove_photo:
            if self.stylist.avatar:
                self.stylist.avatar.delete(save=False)
            self.stylist.avatar = None

        self.stylist.save()

        return self.stylist


class SalonServiceForm(forms.Form):
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
        self.fields['category'].queryset = Category.objects.all().order_by('name')

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            else:
                field.widget.attrs.setdefault('class', 'form-control')

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
