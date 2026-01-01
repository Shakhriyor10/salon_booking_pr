import re

DEFAULT_COUNTRY_CODE = '998'
MIN_PHONE_DIGITS = 7


def _clean_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone(phone_value: str, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Return a normalized international phone number with a leading +.

    If the user didn't specify a country code, the default one is used (Uzbekistan by
    default). Non-digit characters are stripped from the body. If the raw input already
    contains a "+" prefix, the provided country code is respected.
    """
    raw_value = (phone_value or "").strip()
    digits = _clean_digits(raw_value)

    if not digits:
        return ''

    if raw_value.startswith('+'):
        return f"+{digits}"

    if len(digits) <= 9:
        default_digits = _clean_digits(default_country_code) or DEFAULT_COUNTRY_CODE
        return f"+{default_digits}{digits}"

    return f"+{digits}"


def is_valid_phone_input(phone_value: str) -> bool:
    """Check that a phone-like value contains enough digits to be a real number."""
    return len(_clean_digits(phone_value)) >= MIN_PHONE_DIGITS
