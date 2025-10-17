# Generated manually because makemigrations is unavailable in the execution environment.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон')),
                ('telegram_id', models.CharField(blank=True, max_length=32, null=True, unique=True, verbose_name='Telegram ID')),
                ('telegram_username', models.CharField(blank=True, max_length=255, verbose_name='Telegram username')),
                ('is_salon_admin', models.BooleanField(default=False, verbose_name='Салон-админ')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL)),
                ('salon', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='booking.salon', verbose_name='Салон')),
            ],
        ),
    ]
