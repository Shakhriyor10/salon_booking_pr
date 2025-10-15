from django.apps import AppConfig


class BookingConfig(AppConfig):
    name = 'booking'

    def ready(self):
        # Ensure that the historical unique constraint blocking cancelled
        # appointments is replaced with a filtered index that ignores
        # cancelled rows so time slots can be reused.
        from .maintenance import ensure_active_slot_constraint

        ensure_active_slot_constraint()
