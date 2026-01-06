from django.contrib import admin

from .models import SupportMessage, SupportThread


@admin.register(SupportThread)
class SupportThreadAdmin(admin.ModelAdmin):
    list_display = (
        'display_name_admin',
        'contact_email',
        'assigned_to_display',
        'status_display',
        'updated_at',
    )
    list_display_links = ('display_name_admin',)
    search_fields = (
        'contact_name',
        'contact_email',
        'user__username',
        'user__first_name',
        'user__last_name',
    )
    list_filter = ('is_closed', 'assigned_to')
    list_select_related = ('user', 'assigned_to')
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Контактные данные', {'fields': ('user', 'contact_name', 'contact_email', 'session_key')}),
        ('Статус обращения', {'fields': ('assigned_to', 'is_closed')}),
        ('Служебная информация', {'fields': ('created_at', 'updated_at')}),
    )

    def display_name_admin(self, obj: SupportThread) -> str:
        return obj.display_name

    display_name_admin.short_description = 'Обращение'

    def assigned_to_display(self, obj: SupportThread) -> str:
        return obj.assigned_to_name() or '—'

    assigned_to_display.short_description = 'Ответственный'

    def status_display(self, obj: SupportThread) -> str:
        return 'Закрыто' if obj.is_closed else 'Открыто'

    status_display.short_description = 'Статус'


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = (
        'thread',
        'author_display',
        'is_from_staff',
        'created_at',
        'has_attachment',
    )
    search_fields = (
        'body',
        'thread__contact_name',
        'thread__user__username',
        'thread__user__first_name',
        'thread__user__last_name',
    )
    list_filter = ('is_from_staff', 'created_at')
    list_select_related = ('thread', 'author')
    autocomplete_fields = ('thread', 'author')
    readonly_fields = ('created_at',)
    fieldsets = (
        (None, {'fields': ('thread', 'author', 'is_from_staff', 'body', 'attachment')}),
        ('Служебная информация', {'fields': ('created_at',)}),
    )

    def author_display(self, obj: SupportMessage) -> str:
        if obj.author:
            full_name = obj.author.get_full_name()
            return full_name or obj.author.get_username()
        return 'Гость'

    author_display.short_description = 'Автор'

    def has_attachment(self, obj: SupportMessage) -> bool:
        return bool(obj.attachment)

    has_attachment.boolean = True
    has_attachment.short_description = 'Вложение'