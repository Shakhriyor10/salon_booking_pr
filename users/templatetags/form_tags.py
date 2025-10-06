from django import template

register = template.Library()

@register.filter(name='add_class')
def add_class(field, css):
    return field.as_widget(attrs={"class": css})

@register.filter
def is_stylist(user):
    return hasattr(user, 'stylist_profile')

@register.filter
def sum_prices(appointment_services):
    return sum(ap.stylist_service.price for ap in appointment_services if ap.stylist_service and ap.stylist_service.price)