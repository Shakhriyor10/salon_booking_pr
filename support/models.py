import uuid

from django.conf import settings
from django.db import models


class SupportThread(models.Model):
    """A conversation thread between a visitor and the support team."""

    id = models.UUIDField(
        'Идентификатор', primary_key=True, default=uuid.uuid4, editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_threads',
        verbose_name='Пользователь',
    )
    contact_name = models.CharField('Имя посетителя', max_length=150, blank=True)
    contact_email = models.EmailField('Электронная почта', blank=True)
    session_key = models.CharField('Ключ сессии', max_length=40, blank=True, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_threads',
        verbose_name='Ответственный администратор',
    )
    is_closed = models.BooleanField('Обращение закрыто', default=False)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Обращение в поддержку'
        verbose_name_plural = 'Обращения в поддержку'

    def __str__(self) -> str:
        return f"Обращение {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.user:
            full_name = self.user.get_full_name()
            return full_name or self.user.get_username()
        return self.contact_name or 'Гость'

    def assigned_to_name(self) -> str:
        if not self.assigned_to:
            return ''
        full_name = self.assigned_to.get_full_name()
        return full_name or self.assigned_to.get_username()

    def can_user_reply(self, user) -> bool:
        if self.is_closed or not getattr(user, 'is_authenticated', False):
            return False
        if getattr(user, 'is_superuser', False):
            return True
        is_support_staff = getattr(user, 'is_staff', False)
        if not is_support_staff:
            profile = getattr(user, 'profile', None)
            is_support_staff = bool(profile and getattr(profile, 'is_salon_admin', False))
        if not is_support_staff:
            return False
        if self.assigned_to_id and self.assigned_to_id != user.id:
            return False
        return True


class SupportMessage(models.Model):
    thread = models.ForeignKey(
        SupportThread,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Диалог',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_messages',
        verbose_name='Автор',
    )
    is_from_staff = models.BooleanField('Ответ администратора', default=False)
    body = models.TextField('Сообщение', blank=True)
    attachment = models.ImageField(
        'Вложение',
        upload_to='support/attachments/%Y/%m/',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Сообщение поддержки'
        verbose_name_plural = 'Сообщения поддержки'

    def __str__(self) -> str:
        return f"Сообщение в обращении {self.thread_id}"