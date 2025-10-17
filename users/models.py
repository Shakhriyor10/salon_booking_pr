from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField('Телефон', max_length=20, blank=True)
    telegram_id = models.CharField('Telegram ID', max_length=32, blank=True, null=True, unique=True)
    telegram_username = models.CharField('Telegram username', max_length=255, blank=True)

    is_salon_admin = models.BooleanField(default=False, verbose_name="Салон-админ")
    salon = models.ForeignKey('booking.Salon', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Салон")

    def __str__(self):
        return f"{self.user} – {self.phone}"


from django.db import models

# Create your models here.
