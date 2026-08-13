"""Business logic for the booking flow, kept separate from the HTTP layer.

Used by both booking.views (server-rendered flow) and booking.api (REST API)
so the two don't need to import from each other.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AvailabilityRule, Booking, Service, TimeOff, Workspace


class SlotError(Exception):
    """User-facing booking error."""


def get_available_slots(workspace: Workspace, service: Service, day: date):
    """
    Calculează sloturile disponibile pentru un serviciu,
    asigurând o pauză obligatorie după fiecare programare.
    """
    weekday = day.weekday()
    rules = AvailabilityRule.objects.filter(workspace=workspace, weekday=weekday).order_by("start_time")

    if not rules.exists():
        return []

    tz = timezone.get_current_timezone()
    now = timezone.now()

    # Nu permitem rezervări cu mai puțin de 2 ore înainte
    booking_threshold = now + timedelta(hours=2)

    day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    day_end = day_start + timedelta(days=1)

    # Luăm toate rezervările și perioadele de time-off
    existing_bookings = list(Booking.objects.filter(
        workspace=workspace,
        status=Booking.Status.CONFIRMED,
        start_at__lt=day_end,
        end_at__gt=day_start,
    ).values_list("start_at", "end_at"))

    time_off_periods = list(TimeOff.objects.filter(
        workspace=workspace,
        start_at__lt=day_end,
        end_at__gt=day_start,
    ).values_list("start_at", "end_at"))

    all_blocked_intervals = existing_bookings + time_off_periods

    # --- LOGICA DE PAUZĂ ---
    PAUZA_MIN = 10
    dur_serviciu = timedelta(minutes=service.duration_min)
    dur_totala_blocata = timedelta(minutes=service.duration_min + PAUZA_MIN)

    # Pasul cu care „scanăm” ziua pentru a găsi locuri libere
    search_step = timedelta(minutes=15)

    slots = []
    for rule in rules:
        start_dt = timezone.make_aware(datetime.combine(day, rule.start_time), tz)
        end_dt = timezone.make_aware(datetime.combine(day, rule.end_time), tz)

        t = start_dt
        # Căutăm sloturi cât timp serviciul se încadrează în program
        while t + dur_serviciu <= end_dt:
            candidate_start = t
            # Verificăm dacă intervalul (Serviciu + Pauză) este liber
            candidate_end_with_pauza = t + dur_totala_blocata

            # Sărim peste orele din trecut sau sub pragul de 2 ore
            if candidate_start < booking_threshold:
                t += search_step
                continue

            # Verificăm dacă acest bloc (serviciu + pauză) se suprapune cu altceva
            is_occupied = any(
                start < candidate_end_with_pauza and end > candidate_start
                for start, end in all_blocked_intervals
            )

            if not is_occupied:
                slots.append(candidate_start)
                # Dacă am găsit loc, următorul slot posibil
                # începe abia după ce se termină serviciul + pauza actuală
                t += dur_totala_blocata
            else:
                # Dacă e ocupat, căutăm mai departe peste 15 minute
                t += search_step

    return slots


def create_booking_atomic(workspace: Workspace, service: Service, customer, start_at, end_at):
    """
    Transaction-safe booking creation (prevents double booking).
    """
    with transaction.atomic():
        overlap = Booking.objects.select_for_update().filter(
            workspace=workspace,
            status=Booking.Status.CONFIRMED,
        ).filter(
            Q(start_at__lt=end_at) & Q(end_at__gt=start_at)
        )

        if overlap.exists():
            raise SlotError("That time slot is already booked.")

        booking = Booking(
            workspace=workspace,
            service=service,
            customer=customer,
            start_at=start_at,
            end_at=end_at,
            status=Booking.Status.CONFIRMED,
        )
        booking.full_clean()
        booking.save()
        return booking
