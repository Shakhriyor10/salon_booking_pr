import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Profile

class SignUpForm(UserCreationForm):
    phone = forms.RegexField(
        max_length=20,
        regex=r'^\d{2}-\d{3}-\d{2}-\d{2}$',
        label='Телефон',
        error_messages={'invalid': 'Введите номер в формате 93-123-45-67.'}
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'phone', 'password1', 'password2')

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        digits = re.sub(r"\D", "", phone)
        return f"+998{digits}"

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
    phone = forms.RegexField(
        label='Телефон',
        regex=r'^\d{2}-\d{3}-\d{2}-\d{2}$',
        required=False,
        max_length=20,
        error_messages={'invalid': 'Введите номер в формате 93-123-45-67.'}
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        initial = kwargs.setdefault('initial', {})
        initial.setdefault('first_name', user.first_name)
        initial.setdefault('last_name', user.last_name)

        phone = ''
        profile = getattr(user, 'profile', None)
        if profile and profile.phone:
            digits = re.sub(r"\D", "", profile.phone)
            if digits.startswith('998') and len(digits) >= 11:
                body = digits[-9:]
                phone = f"{body[0:2]}-{body[2:5]}-{body[5:7]}-{body[7:9]}"
            elif len(digits) == 9:
                phone = f"{digits[0:2]}-{digits[2:5]}-{digits[5:7]}-{digits[7:9]}"
            else:
                phone = profile.phone
        initial.setdefault('phone', phone)

        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css_class = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f"form-control {css_class}".strip()

            if name == 'phone':
                field.widget.attrs.setdefault('placeholder', '93-123-45-67')
                field.widget.attrs.setdefault('data-uzbek-phone-input', 'true')
                field.widget.attrs.setdefault('inputmode', 'numeric')
                field.widget.attrs.setdefault('autocomplete', 'tel')

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '')
        if not phone:
            return ''
        digits = re.sub(r"\D", "", phone)
        return f"+998{digits}" if digits else ''

    def save(self):
        user = self.user
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.save(update_fields=['first_name', 'last_name'])

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data.get('phone', '')
        profile.save(update_fields=['phone'])

        return user