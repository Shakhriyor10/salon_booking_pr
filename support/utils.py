from __future__ import annotations

from typing import Optional

from django.http import HttpRequest

from .models import SupportThread


def get_or_create_thread_for_request(
    request: HttpRequest,
    *,
    create: bool = True,
    name: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[SupportThread]:
    """Return an existing open thread for the requester or create a new one."""

    thread: Optional[SupportThread] = None

    if request.user.is_authenticated:
        thread = (
            SupportThread.objects.filter(user=request.user, is_closed=False)
            .order_by('-updated_at')
            .first()
        )
        if not thread and create:
            thread = SupportThread.objects.create(user=request.user)
    else:
        session_key = request.session.session_key
        if not session_key and create:
            request.session.create()
            session_key = request.session.session_key
        if session_key:
            thread = (
                SupportThread.objects.filter(session_key=session_key, is_closed=False)
                .order_by('-updated_at')
                .first()
            )
            if not thread and create:
                thread = SupportThread.objects.create(session_key=session_key)

    if thread and create:
        updated = False
        if name and not thread.contact_name:
            thread.contact_name = name
            updated = True
        if email and not thread.contact_email:
            thread.contact_email = email
            updated = True
        if updated:
            thread.save(update_fields=['contact_name', 'contact_email', 'updated_at'])

    return thread
