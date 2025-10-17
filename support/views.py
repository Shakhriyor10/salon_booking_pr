from __future__ import annotations

import os

from typing import Any, Dict, Optional, Tuple

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from .forms import SupportMessageForm
from .models import SupportMessage, SupportThread
from .utils import get_or_create_thread_for_request


def _user_is_support_staff(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile and getattr(profile, 'is_salon_admin', False))


def _can_staff_reply(thread: SupportThread, user) -> bool:
    return thread.can_user_reply(user)


def _thread_status(thread: SupportThread, user) -> Dict[str, Any]:
    assigned_name = thread.assigned_to_name()
    assigned_to_me = bool(thread.assigned_to_id and user.is_authenticated and thread.assigned_to_id == user.id)

    if thread.is_closed:
        label = 'Закрыто'
        badge = 'bg-secondary'
    elif assigned_to_me:
        label = 'Назначено вам'
        badge = 'bg-primary'
    elif assigned_name:
        label = f'Назначено: {assigned_name}'
        badge = 'bg-warning text-dark'
    else:
        label = 'Ожидает ответа'
        badge = 'bg-success'

    return {
        'label': label,
        'badge': badge,
        'assigned_to_me': assigned_to_me,
        'assigned_name': assigned_name,
    }


def _thread_notice(thread: SupportThread, user) -> Tuple[str, str]:
    if thread.is_closed:
        return 'Обращение закрыто. Новые сообщения не принимаются.', 'secondary'
    if not _can_staff_reply(thread, user):
        assigned_name = thread.assigned_to_name()
        if assigned_name:
            message = (
                'Обращение закреплено за администратором '
                f'{assigned_name}. Только он или суперпользователь может отвечать.'
            )
        else:
            message = 'У вас нет прав отвечать на это обращение.'
        return message, 'warning'
    return '', ''


def _format_thread(thread: SupportThread, user) -> Dict[str, Any]:
    status = _thread_status(thread, user)
    notice_text, notice_level = _thread_notice(thread, user)
    return {
        'id': str(thread.id),
        'display_name': thread.display_name,
        'contact_email': thread.contact_email,
        'is_closed': thread.is_closed,
        'assigned_to': status['assigned_name'],
        'assigned_to_me': status['assigned_to_me'],
        'status': status['label'],
        'status_badge': status['badge'],
        'can_reply': _can_staff_reply(thread, user),
        'can_close': (not thread.is_closed) and _can_staff_reply(thread, user),
        'notice': notice_text,
        'notice_level': notice_level,
    }


def _format_message(message: SupportMessage) -> Dict[str, Any]:
    timestamp = timezone.localtime(message.created_at)
    attachment: Optional[Dict[str, Any]] = None
    if message.attachment:
        attachment = {
            'url': message.attachment.url,
            'name': os.path.basename(message.attachment.name),
        }
    return {
        'id': message.id,
        'body': message.body or '',
        'is_from_staff': message.is_from_staff,
        'author': message.author.get_username() if message.author else None,
        'created_at': format_date(timestamp, 'd.m.Y H:i'),
        'attachment': attachment,
    }


@require_GET
def widget_state(request: HttpRequest) -> JsonResponse:
    thread = get_or_create_thread_for_request(request, create=False)

    if not thread:
        return JsonResponse(
            {
                'thread': None,
                'messages': [],
                'is_staff': _user_is_support_staff(request.user),
            }
        )

    messages_data = [_format_message(message) for message in thread.messages.all()]

    return JsonResponse(
        {
            'thread': {
                'id': str(thread.id),
                'contact_name': thread.contact_name,
                'contact_email': thread.contact_email,
                'is_closed': thread.is_closed,
            },
            'messages': messages_data,
            'is_staff': _user_is_support_staff(request.user),
        }
    )


@require_POST
def widget_send(request: HttpRequest) -> JsonResponse:
    form = SupportMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)

    thread = get_or_create_thread_for_request(
        request,
        create=True,
        name=form.cleaned_data.get('contact_name'),
        email=form.cleaned_data.get('contact_email'),
    )

    if not thread:
        return JsonResponse({'errors': {'__all__': ['Не удалось создать обращение.']}}, status=400)

    message = SupportMessage.objects.create(
        thread=thread,
        author=request.user if request.user.is_authenticated else None,
        is_from_staff=_user_is_support_staff(request.user),
        body=form.cleaned_data['message'],
        attachment=form.cleaned_data.get('attachment'),
    )
    thread.updated_at = timezone.now()
    thread.save(update_fields=['updated_at'])

    data = _format_message(message)
    return JsonResponse({'message': data, 'thread_id': str(thread.id)})


class SupportInboxView(LoginRequiredMixin, TemplateView):
    template_name = 'support/inbox.html'

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not _user_is_support_staff(request.user):
            messages.error(request, 'У вас нет доступа к чату поддержки.')
            return render(request, 'support/no_access.html', status=403)
        return super().dispatch(request, *args, **kwargs)


@login_required
@user_passes_test(_user_is_support_staff)
@require_GET
def threads_list(request: HttpRequest) -> JsonResponse:
    threads = SupportThread.objects.filter(is_closed=False).select_related('assigned_to', 'user')
    data = []
    for thread in threads:
        status = _thread_status(thread, request.user)
        data.append(
            {
                'id': str(thread.id),
                'display_name': thread.display_name,
                'last_message': _last_message_preview(thread),
                'updated_at': format_date(timezone.localtime(thread.updated_at), 'd.m.Y H:i'),
                'status': status['label'],
                'status_badge': status['badge'],
                'assigned_to_me': status['assigned_to_me'],
            }
        )
    return JsonResponse({'threads': data})


@login_required
@user_passes_test(_user_is_support_staff)
@require_GET
def thread_messages(request: HttpRequest, thread_id: str) -> JsonResponse:
    thread = get_object_or_404(
        SupportThread.objects.select_related('assigned_to', 'user'), pk=thread_id
    )
    messages_data = [_format_message(message) for message in thread.messages.all()]
    return JsonResponse(
        {
            'thread': _format_thread(thread, request.user),
            'messages': messages_data,
        }
    )


@login_required
@user_passes_test(_user_is_support_staff)
@require_POST
def staff_send(request: HttpRequest, thread_id: str) -> JsonResponse:
    thread = get_object_or_404(
        SupportThread.objects.select_related('assigned_to', 'user'), pk=thread_id
    )
    form = SupportMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)

    if thread.is_closed:
        return JsonResponse(
            {
                'errors': {'__all__': ['Обращение закрыто. Новые сообщения не принимаются.']},
                'thread': _format_thread(thread, request.user),
            },
            status=400,
        )
    if thread.assigned_to_id and thread.assigned_to_id != request.user.id and not request.user.is_superuser:
        return JsonResponse(
            {
                'errors': {'__all__': ['Обращение закреплено за другим администратором.']},
                'thread': _format_thread(thread, request.user),
            },
            status=403,
        )

    message = SupportMessage.objects.create(
        thread=thread,
        author=request.user,
        is_from_staff=True,
        body=form.cleaned_data['message'],
        attachment=form.cleaned_data.get('attachment'),
    )

    thread.updated_at = timezone.now()
    update_fields = ['updated_at']
    if not thread.assigned_to_id:
        thread.assigned_to = request.user
        update_fields.append('assigned_to')
    thread.save(update_fields=update_fields)

    return JsonResponse(
        {
            'message': _format_message(message),
            'thread': _format_thread(thread, request.user),
        }
    )


@login_required
@user_passes_test(_user_is_support_staff)
@require_POST
def thread_close(request: HttpRequest, thread_id: str) -> JsonResponse:
    thread = get_object_or_404(
        SupportThread.objects.select_related('assigned_to', 'user'), pk=thread_id
    )

    if thread.is_closed:
        return JsonResponse({'thread': _format_thread(thread, request.user)})

    if not _can_staff_reply(thread, request.user):
        return JsonResponse(
            {
                'errors': {'__all__': ['У вас нет прав закрыть это обращение.']},
                'thread': _format_thread(thread, request.user),
            },
            status=403,
        )

    thread.is_closed = True
    thread.updated_at = timezone.now()
    thread.save(update_fields=['is_closed', 'updated_at'])

    return JsonResponse({'thread': _format_thread(thread, request.user)})


def _last_message_preview(thread: SupportThread) -> str:
    last_message: Optional[SupportMessage] = thread.messages.last()
    if not last_message:
        return ''
    if last_message.body:
        return last_message.body
    if last_message.attachment:
        return '📎 Фото'
    return ''