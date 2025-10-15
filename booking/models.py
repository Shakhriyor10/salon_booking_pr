# booking/models.py
from datetime import timedelta, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse
from django.db.models import Avg, Q

User = get_user_model()

class StylistLevel(models.Model):
    name = models.CharField(max_length=50, unique=True)  # Например: Топ Барбер
    order = models.PositiveIntegerField(default=0)  # Для сортировки (чем выше — тем круче)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name

class City(models.Model):
    name = models.CharField(max_length=100)
    position = models.PositiveIntegerField(default=0)  # для сортировки в списках

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['position', 'name']


class Salon(models.Model):
    GENDER_CHOICES = [
        ('', 'Не указано'),
        ('male', 'Мужской'),
        ('female', 'Женский'),
        ('both', 'Обе'),
    ]
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name='salons')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    photo = models.ImageField(upload_to='photo_salon/', null=True, blank=True)
    photo_2 = models.ImageField(upload_to='photo_salon/', null=True, blank=True)
    photo_3 = models.ImageField(upload_to='photo_salon/', null=True, blank=True)
    photo_4 = models.ImageField(upload_to='photo_salon/', null=True, blank=True)
    photo_5 = models.ImageField(upload_to='photo_salon/', null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    status = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    type = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        blank=True,
        null=True,
        verbose_name="Тип салона"
    )
    slug = models.SlugField(max_length=150, blank=True)  # добавили поле slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('salon_detail', kwargs={'pk': self.pk, 'slug': self.slug})

    def __str__(self):
        return f"{self.name} ({self.city.name})"

    def average_rating(self):
        return self.reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    def get_photos(self):
        photos = []
        for field_name in ('photo', 'photo_2', 'photo_3', 'photo_4', 'photo_5'):
            image = getattr(self, field_name)
            if image:
                photos.append(image)
        return photos

    class Meta:
        ordering = ['-position', 'name']



class SalonPaymentCard(models.Model):
    salon = models.ForeignKey('Salon', on_delete=models.CASCADE, related_name='payment_cards')
    card_holder = models.CharField(max_length=120, verbose_name='Владелец карты')
    card_number = models.CharField(max_length=32, verbose_name='Номер карты')
    description = models.CharField(max_length=255, blank=True, verbose_name='Комментарий')
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']
        verbose_name = 'Карта для оплаты'
        verbose_name_plural = 'Карты для оплаты'

    def __str__(self):
        return f"{self.salon.name}: {self.masked_number}"

    @property
    def masked_number(self):
        digits = ''.join(ch for ch in self.card_number if ch.isdigit())
        if len(digits) >= 4:
            return f"**** **** **** {digits[-4:]}"
        return self.card_number

    @staticmethod
    def format_card_number(value: str) -> str:
        digits = ''.join(ch for ch in value or '' if ch.isdigit())
        return ' '.join(
            digits[i:i + 4] for i in range(0, len(digits), 4)
        ) or value

    def formatted_number(self) -> str:
        return self.format_card_number(self.card_number)

    def clean(self):
        super().clean()
        digits = ''.join(ch for ch in self.card_number if ch.isdigit())
        if len(digits) < 12:
            raise ValidationError({'card_number': 'Номер карты должен содержать не менее 12 цифр.'})
        self.card_number = digits

    def save(self, *args, **kwargs):
        digits = ''.join(ch for ch in self.card_number if ch.isdigit())
        if digits:
            self.card_number = digits
        self.full_clean()
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField(max_length=100, verbose_name='Категория')
    photo = models.ImageField(upload_to='category_photos/', null=True, blank=True)

    def __str__(self):
        return self.name



class Service(models.Model):
    name = models.CharField('Название', max_length=120, unique=True)
    description = models.TextField('Описание', blank=True)
    photo = models.ImageField('Фото услуги', upload_to='service_photos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Услуга'
        verbose_name_plural = 'Услуги'

    def __str__(self):
        return self.name


class SalonService(models.Model):
    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name='salon_services')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='salon_services')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    duration = models.DurationField(default=timedelta(minutes=30))
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0, verbose_name="Позиция")

    class Meta:
        unique_together = ('salon', 'service')
        verbose_name = 'Услуга салона'
        verbose_name_plural = 'Услуги салона'

    def __str__(self):
        return f"{self.salon.name} — {self.service.name}"


class Stylist(models.Model):
    """Парикмахер/стилист – отдельный пользователь Django."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='stylist_profile',
        verbose_name='Аккаунт'
    )
    telegram_username = models.CharField(max_length=64, blank=True, null=True, verbose_name="Telegram Username")
    telegram_chat_id = models.BigIntegerField(
        "Telegram chat_id", blank=True, null=True
    )
    bio = models.TextField('О себе', blank=True)
    avatar = models.ImageField('Фото', upload_to='stylists/', blank=True, null=True)
    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name='stylists')
    level = models.ForeignKey(StylistLevel, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Мастер'
        verbose_name_plural = 'Мастера'

    def __str__(self):
        full_name = self.user.get_full_name() or self.user.username
        if self.level:
            return f"{full_name} — {self.level.name}"
        return full_name


WEEKDAYS = [
    (0, 'Понедельник'),
    (1, 'Вторник'),
    (2, 'Среда'),
    (3, 'Четверг'),
    (4, 'Пятница'),
    (5, 'Суббота'),
    (6, 'Воскресенье'),
]


class WorkingHour(models.Model):
    """Типовой рабочий интервал мастера (повторяется каждую неделю)."""
    stylist = models.ForeignKey(
        Stylist, related_name='working_hours', on_delete=models.CASCADE,
        verbose_name='Мастер'
    )
    weekday = models.PositiveSmallIntegerField('День недели', choices=WEEKDAYS)
    start_time = models.TimeField('Начало')
    end_time = models.TimeField('Конец')

    class Meta:
        unique_together = ('stylist', 'weekday', 'start_time')
        ordering = ['stylist', 'weekday', 'start_time']
        verbose_name = 'Рабочий интервал'
        verbose_name_plural = 'Рабочие интервалы'

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError('Время окончания должно быть позже начала.')

    def __str__(self):
        return f'{self.get_weekday_display()} {self.start_time}–{self.end_time}'


class Appointment(models.Model):
    """Запись клиента на услуги (несколько)."""

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Наличные'
        CARD = 'card', 'Карта'

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Ожидает оплаты'
        AWAITING_CONFIRMATION = 'awaiting_confirmation', 'Ожидает подтверждения'
        PAID = 'paid', 'Оплачено'
        REFUND_REQUESTED = 'refund_requested', 'Возврат запрошен'
        REFUNDED = 'refunded', 'Возврат выполнен'

    class Status(models.TextChoices):
        PENDING = 'P', 'Ожидает подтверждения'
        CONFIRMED = 'C', 'Подтверждена'
        CANCELLED = 'X', 'Отменена'
        DONE = 'D', 'Выполнена'

    customer = models.ForeignKey(
        User,
        related_name='appointments',
        on_delete=models.CASCADE,
        verbose_name='Клиент',
        null=True,
        blank=True
    )

    guest_name = models.CharField('Имя гостя', max_length=100, blank=True)
    guest_phone = models.CharField('Телефон гостя', max_length=20, blank=True)

    stylist = models.ForeignKey(
        Stylist,
        related_name='appointments',
        on_delete=models.PROTECT,
        verbose_name='Мастер'
    )

    start_time = models.DateTimeField('Начало')
    end_time = models.DateTimeField('Конец', blank=True, null=True)

    status = models.CharField(
        max_length=1,
        choices=Status.choices,
        default=Status.PENDING
    )

    payment_method = models.CharField(
        max_length=16,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    payment_status = models.CharField(
        max_length=32,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    payment_card = models.ForeignKey(
        SalonPaymentCard,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments',
    )
    payment_card_snapshot = models.CharField(max_length=64, blank=True)
    payment_card_holder_snapshot = models.CharField(max_length=128, blank=True)
    payment_receipt = models.ImageField(upload_to='payment_receipts/', null=True, blank=True)
    payment_submitted_at = models.DateTimeField(null=True, blank=True)
    payment_confirmed_at = models.DateTimeField(null=True, blank=True)
    refund_card_number = models.CharField(max_length=64, blank=True)
    refund_receipt = models.ImageField(upload_to='refund_receipts/', null=True, blank=True)
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refund_confirmed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField('Комментарий клиента', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_time']
        verbose_name = 'Запись'
        verbose_name_plural = 'Записи'
        constraints = [
            models.UniqueConstraint(
                fields=('stylist', 'start_time'),
                condition=~Q(status='X'),
                name='unique_active_appointment_per_slot',
            )
        ]

    def __str__(self):
        start = timezone.localtime(self.start_time).strftime('%d.%m %H:%M')
        name = self.customer if self.customer else (self.guest_name or "Гость")
        return f'{name} ➜ {self.stylist} ({start})'

    def set_payment_card(self, card: SalonPaymentCard | None):
        self.payment_card = card
        if card:
            self.payment_card_snapshot = card.card_number
            self.payment_card_holder_snapshot = card.card_holder
        else:
            self.payment_card_snapshot = ''
            self.payment_card_holder_snapshot = ''

    def get_payment_card_display(self) -> str:
        if self.payment_card:
            return self.payment_card.formatted_number()
        if self.payment_card_snapshot:
            return SalonPaymentCard.format_card_number(self.payment_card_snapshot)
        return ''

    def get_payment_card_holder_display(self) -> str:
        if self.payment_card and self.payment_card.card_holder:
            return self.payment_card.card_holder
        return self.payment_card_holder_snapshot

    @property
    def is_card_payment_locked(self) -> bool:
        if self.payment_method != self.PaymentMethod.CARD:
            return False
        if self.payment_receipt:
            return True
        return self.payment_status in {
            self.PaymentStatus.AWAITING_CONFIRMATION,
            self.PaymentStatus.PAID,
            self.PaymentStatus.REFUND_REQUESTED,
            self.PaymentStatus.REFUNDED,
        }

    def get_refund_card_display(self) -> str:
        if not self.refund_card_number:
            return ''
        return SalonPaymentCard.format_card_number(self.refund_card_number)

    def get_total_price(self):
        return sum(s.get_price() for s in self.services.all())

    def get_total_duration(self):
        return sum((s.get_duration() for s in self.services.all()), timedelta())

    def save(self, *args, **kwargs):
        if not self.end_time:
            self.end_time = self.start_time + self.get_total_duration()
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.end_time and self.end_time <= self.start_time:
            raise ValidationError('Конец визита должен быть позже начала.')

        if not self.customer and not (self.guest_name and self.guest_phone):
            raise ValidationError('Укажите клиента или имя и телефон гостя.')

        if self.customer and (self.guest_name or self.guest_phone):
            raise ValidationError('Нельзя указывать и клиента, и данные гостя одновременно.')

        clash = Appointment.objects.filter(
            stylist=self.stylist,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time
        ).exclude(pk=self.pk).exclude(status=Appointment.Status.CANCELLED).exists()

        if clash:
            raise ValidationError('На это время мастер уже занят.')

        if self.payment_method == self.PaymentMethod.CARD:
            if self.payment_card and self.payment_card.salon != self.stylist.salon:
                raise ValidationError('Карта оплаты должна принадлежать салону мастера.')
            if not (self.payment_card or self.payment_card_snapshot):
                raise ValidationError('Для оплаты картой необходимо указать карту салона.')


class AppointmentService(models.Model):
    appointment = models.ForeignKey(Appointment, related_name='services', on_delete=models.CASCADE)
    stylist_service = models.ForeignKey('StylistService', on_delete=models.SET_NULL,
                                        null=True, blank=True)

    def get_duration(self):
        if self.stylist_service and self.stylist_service.salon_service:
            return self.stylist_service.salon_service.duration
        return timedelta()

    def get_price(self):
        if self.stylist_service:
            return self.stylist_service.price
        return Decimal('0')

    def __str__(self):
        if (
            self.stylist_service and
            self.stylist_service.salon_service and
            self.stylist_service.salon_service.service
        ):
            return self.stylist_service.salon_service.service.name
        return f"AppointmentService #{self.pk}"


class StylistService(models.Model):
    stylist = models.ForeignKey('Stylist', on_delete=models.CASCADE, related_name='stylist_services')
    salon_service = models.ForeignKey('SalonService', on_delete=models.CASCADE, null=True, blank=True)
    price = models.DecimalField('Цена, сум', max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ('stylist', 'salon_service')
        verbose_name = 'Цена услуги мастера'
        verbose_name_plural = 'Цены услуг мастеров'

    def __str__(self):
        return f"{self.stylist} – {self.salon_service} – {self.price} сум"


class BreakPeriod(models.Model):
    working_hour = models.ForeignKey(
        WorkingHour,
        related_name='breaks',
        on_delete=models.CASCADE,
        verbose_name='Рабочий интервал'
    )
    start_time = models.TimeField('Начало перерыва')
    end_time = models.TimeField('Конец перерыва')

    class Meta:
        ordering = ['start_time']
        verbose_name = 'Перерыв'
        verbose_name_plural = 'Перерывы'

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError('Время окончания перерыва должно быть позже начала.')

        if self.working_hour:
            if self.start_time < self.working_hour.start_time or self.end_time > self.working_hour.end_time:
                raise ValidationError('Перерыв должен быть внутри рабочего интервала.')

    def __str__(self):
        return f'Перерыв {self.start_time}–{self.end_time}'



class Review(models.Model):
    salon = models.ForeignKey('Salon', on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])  # 1–5 звёзд
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.salon.name} - {self.rating}★ by {self.user}"


class StylistDayOff(models.Model):
    stylist = models.ForeignKey('Stylist', on_delete=models.CASCADE)
    date = models.DateField()
    from_time = models.TimeField(null=True, blank=True)  # если не указано — значит целый день
    to_time = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ('stylist', 'date', 'from_time', 'to_time')

    def __str__(self):
        if self.from_time and self.to_time:
            return f"{self.stylist} — не работает {self.date} с {self.from_time} до {self.to_time}"
        return f"{self.stylist} — выходной {self.date}"