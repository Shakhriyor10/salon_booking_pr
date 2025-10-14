from django import template

register = template.Library()


@register.filter(name="add_class")
def add_class(field, css):
    return field.as_widget(attrs={"class": css})


@register.filter
def is_stylist(user):
    return hasattr(user, "stylist_profile")


@register.filter
def sum_prices(appointment_services):
    return sum(
        ap.stylist_service.price
        for ap in appointment_services
        if ap.stylist_service and ap.stylist_service.price
    )


@register.simple_tag
def count_by_status(appointments, status):
    """Count appointments with a particular status."""

    if not appointments:
        return 0

    return sum(1 for appointment in appointments if getattr(appointment, "status", None) == status)


@register.filter
def status_badge_class(status):
    """Return bootstrap color classes for appointment status badges."""

    palette = {
        "P": "bg-warning text-dark",  # Pending / new
        "C": "bg-info text-dark",  # Confirmed
        "D": "bg-success",  # Done
        "X": "bg-secondary",  # Cancelled by client
        "CN": "bg-danger",  # Cancelled by salon
    }

    return palette.get(status, "bg-secondary")