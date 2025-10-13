import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

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
        from .models import Profile
        profile, created = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.save()

        return user
