from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from booking.phone_utils import is_valid_phone_input, normalize_phone
from .models import Profile

class SignUpForm(UserCreationForm):
    phone = forms.CharField(
        max_length=32,
        label='Телефон',
        help_text='Укажите номер вместе с кодом страны (например, +1 202 555 0199).'
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'phone', 'password1', 'password2')

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if not is_valid_phone_input(phone):
            raise forms.ValidationError('Введите корректный номер телефона.')
        return normalize_phone(phone)

    def save(self, commit=True):
        user = super().save(commit)

        # Профиль может ещё не существовать, поэтому создаём вручную
        profile, created = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.save()

        return user


class ProfileUpdateForm(forms.Form):
    first_name = forms.CharField(label='Имя', max_length=150, required=False)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)
    phone = forms.CharField(
        label='Телефон',
        required=False,
        max_length=32,
        help_text='Укажите номер вместе с кодом страны (например, +1 202 555 0199).'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        initial = kwargs.setdefault('initial', {})
        initial.setdefault('first_name', user.first_name)
        initial.setdefault('last_name', user.last_name)

        profile = getattr(user, 'profile', None)
        if profile and profile.phone:
            initial.setdefault('phone', profile.phone)

        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css_class = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f"form-control {css_class}".strip()

            if name == 'phone':
                field.widget.attrs.setdefault('placeholder', '+998 90 123 45 67')
                field.widget.attrs.setdefault('data-uzbek-phone-input', 'true')
                field.widget.attrs.setdefault('inputmode', 'tel')
                field.widget.attrs.setdefault('autocomplete', 'tel')

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '')
        if not phone:
            return ''
        if not is_valid_phone_input(phone):
            raise forms.ValidationError('Введите корректный номер телефона.')
        return normalize_phone(phone)

    def save(self):
        user = self.user
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.save(update_fields=['first_name', 'last_name'])

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data.get('phone', '')
        profile.save(update_fields=['phone'])

        return user