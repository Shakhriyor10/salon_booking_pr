from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from users.models import Profile

from .models import (
    Review,
    Stylist,
    StylistLevel,
    Service,
    Category,
    SalonService,
)

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

        return stylist


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
