from django import template
from django.core.exceptions import ObjectDoesNotExist

register = template.Library()

@register.filter
def floatval(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


@register.simple_tag(takes_context=True)
def user_salon_url(context):
    request = context.get('request')
    if not request:
        return ''

    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return ''

    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'is_salon_admin', False):
        salon = getattr(profile, 'salon', None)
        if salon and salon.is_subscription_active:
            return salon.get_absolute_url()

    try:
        stylist_profile = user.stylist_profile
    except ObjectDoesNotExist:
        stylist_profile = None

    if stylist_profile:
        salon = getattr(stylist_profile, 'salon', None)
        if salon and salon.is_subscription_active:
            return salon.get_absolute_url()

    return ''
