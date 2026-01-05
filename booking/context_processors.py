from datetime import timedelta

from django.utils import timezone

from .models import Appointment


def overdue_appointments_prompt(request):
    """Expose overdue appointments info for salon admins once per session."""

    if not request.user.is_authenticated:
        return {}

    profile = getattr(request.user, "profile", None)
    if not (profile and profile.is_salon_admin and profile.salon):
        return {}

    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    overdue_qs = Appointment.objects.filter(
        stylist__salon=profile.salon,
        status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        start_time__date__gte=previous_month_start,
        start_time__date__lte=previous_month_end,
    )

    overdue_count = overdue_qs.count()
    session_key = f"overdue_prompt_shown_{request.user.id}"

    if overdue_count and not request.session.get(session_key):
        request.session[session_key] = True
        return {
            "overdue_appointments_prompt": {
                "count": overdue_count,
                "start_date": previous_month_start,
                "end_date": previous_month_end,
            }
        }

    return {}
