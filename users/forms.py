from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class SignUpForm(UserCreationForm):
    phone = forms.CharField(max_length=20, label='Телефон')

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'phone', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit)

        # Профиль может ещё не существовать, поэтому создаём вручную
        from .models import Profile
        profile, created = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.save()

        return user

