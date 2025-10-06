from django import template

register = template.Library()

@register.filter
def floatval(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0