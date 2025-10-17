from django.contrib import admin

from .models import SupportMessage, SupportThread


@admin.register(SupportThread)
class SupportThreadAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'contact_email', 'user', 'is_closed', 'updated_at')
    search_fields = (
        'contact_name',
        'contact_email',
        'user__username',
        'user__first_name',
        'user__last_name',
    )
    list_filter = ('is_closed',)


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ('thread', 'author', 'is_from_staff', 'created_at', 'has_attachment')
    search_fields = ('body', 'thread__contact_name', 'thread__user__username')
    list_filter = ('is_from_staff', 'created_at')
    autocomplete_fields = ('thread', 'author')

    def has_attachment(self, obj: SupportMessage) -> bool:
        return bool(obj.attachment)

    has_attachment.boolean = True
    has_attachment.short_description = 'Вложение'
