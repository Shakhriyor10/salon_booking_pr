"""Database maintenance helpers for the booking app."""
from __future__ import annotations

from contextlib import suppress

from django.db import connection
from django.db.utils import OperationalError, ProgrammingError

__all__ = ["ensure_active_slot_constraint"]


_CONSTRAINT_SYNCED = False


def _has_appointment_table() -> bool:
    """Return True when the appointment table exists."""
    with suppress(OperationalError, ProgrammingError):
        return "booking_appointment" in connection.introspection.table_names()
    return False


def ensure_active_slot_constraint() -> None:
    """Drop the legacy unique constraint and create a filtered alternative.

    Older databases may still contain the unconditional unique constraint on
    ``(stylist_id, start_time)`` that blocks reusing a slot after a cancellation.
    We drop that constraint (when present) and replace it with a filtered unique
    index that ignores cancelled appointments so the time slot becomes available
    again for new bookings.
    """
    global _CONSTRAINT_SYNCED

    if _CONSTRAINT_SYNCED:
        return

    if connection.vendor not in {"postgresql", "sqlite"}:
        _CONSTRAINT_SYNCED = True
        return

    if not _has_appointment_table():
        return

    statements = []
    if connection.vendor == "postgresql":
        statements = [
            "ALTER TABLE booking_appointment DROP CONSTRAINT IF EXISTS "
            "booking_appointment_stylist_id_start_time_ffca5c92_uniq;",
            "CREATE UNIQUE INDEX IF NOT EXISTS unique_active_appointment_per_slot "
            "ON booking_appointment (stylist_id, start_time) "
            "WHERE status <> 'X';",
        ]
    elif connection.vendor == "sqlite":
        statements = [
            "DROP INDEX IF EXISTS unique_active_appointment_per_slot;",
            "CREATE UNIQUE INDEX IF NOT EXISTS unique_active_appointment_per_slot "
            "ON booking_appointment (stylist_id, start_time) "
            "WHERE status <> 'X';",
        ]

    for statement in statements:
        with suppress(OperationalError, ProgrammingError):
            with connection.cursor() as cursor:
                cursor.execute(statement)

    _CONSTRAINT_SYNCED = True
