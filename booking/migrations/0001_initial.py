from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import datetime


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StylistLevel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('order', models.PositiveIntegerField(default=0)),
            ],
            options={'ordering': ['order']},
        ),
        migrations.CreateModel(
            name='City',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('position', models.PositiveIntegerField(default=0)),
            ],
            options={'ordering': ['position', 'name']},
        ),
        migrations.CreateModel(
            name='Salon',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('address', models.CharField(max_length=255)),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('photo', models.ImageField(blank=True, null=True, upload_to='photo_salon/')),
                ('photo_2', models.ImageField(blank=True, null=True, upload_to='photo_salon/')),
                ('photo_3', models.ImageField(blank=True, null=True, upload_to='photo_salon/')),
                ('photo_4', models.ImageField(blank=True, null=True, upload_to='photo_salon/')),
                ('photo_5', models.ImageField(blank=True, null=True, upload_to='photo_salon/')),
                ('phone', models.CharField(blank=True, max_length=20)),
                ('status', models.BooleanField(default=True)),
                ('position', models.PositiveIntegerField(default=0)),
                ('type', models.CharField(blank=True, choices=[('', 'Не указано'), ('male', 'Мужской'), ('female', 'Женский'), ('both', 'Обе')], max_length=10, null=True, verbose_name='Тип салона')),
                ('slug', models.SlugField(blank=True, max_length=150)),
                ('city', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salons', to='booking.city')),
            ],
            options={'ordering': ['-position', 'name']},
        ),
        migrations.CreateModel(
            name='SalonPaymentCard',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('card_type', models.CharField(choices=[('uzcard', 'UZCARD'), ('humo', 'HUMO'), ('visa', 'VISA'), ('mastercard', 'Mastercard'), ('mir', 'МИР'), ('other', 'Другая')], default='other', max_length=32)),
                ('cardholder_name', models.CharField(max_length=120)),
                ('card_number', models.CharField(max_length=32)),
                ('is_active', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('salon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_cards', to='booking.salon')),
            ],
            options={'ordering': ['-is_active', '-updated_at'], 'unique_together': {('salon', 'card_number')}, 'verbose_name': 'Карта салона', 'verbose_name_plural': 'Карты салона'},
        ),
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Категория')),
                ('photo', models.ImageField(blank=True, null=True, upload_to='category_photos/')),
            ],
        ),
        migrations.CreateModel(
            name='Service',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Название')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('photo', models.ImageField(blank=True, null=True, upload_to='service_photos/', verbose_name='Фото услуги')),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['name'], 'verbose_name': 'Услуга', 'verbose_name_plural': 'Услуги'},
        ),
        migrations.CreateModel(
            name='Stylist',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telegram_username', models.CharField(blank=True, max_length=64, null=True, verbose_name='Telegram Username')),
                ('telegram_chat_id', models.BigIntegerField(blank=True, null=True, verbose_name='Telegram chat_id')),
                ('bio', models.TextField(blank=True, verbose_name='О себе')),
                ('avatar', models.ImageField(blank=True, null=True, upload_to='stylists/', verbose_name='Фото')),
                ('level', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='booking.stylistlevel')),
                ('salon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stylists', to='booking.salon')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='stylist_profile', to=settings.AUTH_USER_MODEL, verbose_name='Аккаунт')),
            ],
            options={'verbose_name': 'Мастер', 'verbose_name_plural': 'Мастера'},
        ),
        migrations.CreateModel(
            name='SalonService',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('duration', models.DurationField(default=datetime.timedelta(minutes=30))),
                ('is_active', models.BooleanField(default=True)),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Позиция')),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='booking.category')),
                ('salon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salon_services', to='booking.salon')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salon_services', to='booking.service')),
            ],
            options={'verbose_name': 'Услуга салона', 'verbose_name_plural': 'Услуги салона', 'unique_together': {('salon', 'service')}},
        ),
        migrations.CreateModel(
            name='WorkingHour',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weekday', models.PositiveSmallIntegerField(choices=[(0, 'Понедельник'), (1, 'Вторник'), (2, 'Среда'), (3, 'Четверг'), (4, 'Пятница'), (5, 'Суббота'), (6, 'Воскресенье')], verbose_name='День недели')),
                ('start_time', models.TimeField(verbose_name='Начало')),
                ('end_time', models.TimeField(verbose_name='Конец')),
                ('stylist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='working_hours', to='booking.stylist', verbose_name='Мастер')),
            ],
            options={'ordering': ['stylist', 'weekday', 'start_time'], 'verbose_name': 'Рабочий интервал', 'verbose_name_plural': 'Рабочие интервалы', 'unique_together': {('stylist', 'weekday', 'start_time')}},
        ),
        migrations.CreateModel(
            name='Appointment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('guest_name', models.CharField(blank=True, max_length=100, verbose_name='Имя гостя')),
                ('guest_phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон гостя')),
                ('start_time', models.DateTimeField(verbose_name='Начало')),
                ('end_time', models.DateTimeField(blank=True, null=True, verbose_name='Конец')),
                ('status', models.CharField(choices=[('P', 'Ожидает подтверждения'), ('C', 'Подтверждена'), ('X', 'Отменена'), ('D', 'Выполнена')], default='P', max_length=1)),
                ('payment_method', models.CharField(choices=[('cash', 'Наличные'), ('card', 'Перевод на карту')], default='cash', max_length=16)),
                ('payment_status', models.CharField(choices=[('not_required', 'Не требуется'), ('pending', 'Ожидает подтверждения записи'), ('awaiting_payment', 'Ожидает оплаты'), ('awaiting_confirmation', 'Чек на проверке'), ('paid', 'Оплачено'), ('refund_requested', 'Ожидает возврата'), ('refunded', 'Возврат выполнен')], default='not_required', max_length=24)),
                ('payment_receipt', models.ImageField(blank=True, null=True, upload_to='payment_receipts/')),
                ('receipt_uploaded_at', models.DateTimeField(blank=True, null=True)),
                ('refund_cardholder_name', models.CharField(blank=True, max_length=120)),
                ('refund_card_number', models.CharField(blank=True, max_length=64)),
                ('refund_card_type', models.CharField(blank=True, max_length=64)),
                ('refund_requested_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, verbose_name='Комментарий клиента')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='appointments', to=settings.AUTH_USER_MODEL, verbose_name='Клиент')),
                ('payment_card', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='appointments', to='booking.salonpaymentcard')),
                ('stylist', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appointments', to='booking.stylist', verbose_name='Мастер')),
            ],
            options={'ordering': ['-start_time'], 'verbose_name': 'Запись', 'verbose_name_plural': 'Записи'},
        ),
        migrations.CreateModel(
            name='StylistService',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Цена, сум')),
                ('salon_service', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='booking.salonservice')),
                ('stylist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stylist_services', to='booking.stylist')),
            ],
            options={'verbose_name': 'Цена услуги мастера', 'verbose_name_plural': 'Цены услуг мастеров', 'unique_together': {('stylist', 'salon_service')}},
        ),
        migrations.CreateModel(
            name='AppointmentService',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('appointment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='services', to='booking.appointment')),
                ('stylist_service', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='booking.stylistservice')),
            ],
        ),
        migrations.CreateModel(
            name='BreakPeriod',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.TimeField(verbose_name='Начало перерыва')),
                ('end_time', models.TimeField(verbose_name='Конец перерыва')),
                ('working_hour', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='breaks', to='booking.workinghour', verbose_name='Рабочий интервал')),
            ],
            options={'ordering': ['start_time'], 'verbose_name': 'Перерыв', 'verbose_name_plural': 'Перерывы'},
        ),
        migrations.CreateModel(
            name='Review',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.IntegerField(choices=[(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])),
                ('comment', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('salon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to='booking.salon')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='StylistDayOff',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('from_time', models.TimeField(blank=True, null=True)),
                ('to_time', models.TimeField(blank=True, null=True)),
                ('stylist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='booking.stylist')),
            ],
            options={'unique_together': {('stylist', 'date', 'from_time', 'to_time')}},
        ),
        migrations.AddConstraint(
            model_name='appointment',
            constraint=models.UniqueConstraint(condition=~models.Q(status='X'), fields=('stylist', 'start_time'), name='unique_active_appointment_per_slot'),
        ),
    ]
