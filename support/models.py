import uuid

from django.conf import settings
from django.db import models


class SupportThread(models.Model):
    """A conversation thread between a visitor and the support team."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_threads',
    )
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    is_closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self) -> str:
        return f"Support thread {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.user:
            full_name = self.user.get_full_name()
            return full_name or self.user.get_username()
        return self.contact_name or 'Гость'


class SupportMessage(models.Model):
    thread = models.ForeignKey(
        SupportThread,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_messages',
    )
    is_from_staff = models.BooleanField(default=False)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self) -> str:
        return f"Message in {self.thread_id}"
