from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import AvailabilityRule, Booking, Service, Workspace
from .views import SlotError, create_booking_atomic, get_available_slots

User = get_user_model()


class BookingOverlapTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw12345", user_type="PROVIDER")
        self.customer = User.objects.create_user(username="client", password="pw12345", user_type="CLIENT")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio", slug="studio")
        self.service = Service.objects.create(workspace=self.workspace, name="Haircut", duration_min=30)

        self.start = timezone.now() + timedelta(hours=3)
        self.end = self.start + timedelta(minutes=30)

    def test_create_booking_atomic_succeeds_for_free_slot(self):
        booking = create_booking_atomic(
            workspace=self.workspace,
            service=self.service,
            customer=self.customer,
            start_at=self.start,
            end_at=self.end,
        )
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_create_booking_atomic_rejects_overlap(self):
        create_booking_atomic(
            workspace=self.workspace,
            service=self.service,
            customer=self.customer,
            start_at=self.start,
            end_at=self.end,
        )

        with self.assertRaises(SlotError):
            create_booking_atomic(
                workspace=self.workspace,
                service=self.service,
                customer=self.customer,
                start_at=self.start + timedelta(minutes=10),
                end_at=self.end + timedelta(minutes=10),
            )

        self.assertEqual(Booking.objects.count(), 1)

    def test_model_clean_rejects_overlap(self):
        Booking.objects.create(
            workspace=self.workspace,
            service=self.service,
            customer=self.customer,
            start_at=self.start,
            end_at=self.end,
        )

        clashing = Booking(
            workspace=self.workspace,
            service=self.service,
            customer=self.customer,
            start_at=self.start + timedelta(minutes=10),
            end_at=self.end + timedelta(minutes=10),
        )
        with self.assertRaises(ValidationError):
            clashing.clean()


class AvailableSlotsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw12345", user_type="PROVIDER")
        self.customer = User.objects.create_user(username="client", password="pw12345", user_type="CLIENT")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio", slug="studio")
        self.service = Service.objects.create(workspace=self.workspace, name="Haircut", duration_min=30)

        # Availability tomorrow, all day, so the 2h threshold never excludes everything.
        self.tomorrow = (timezone.now() + timedelta(days=1)).date()
        AvailabilityRule.objects.create(
            workspace=self.workspace,
            weekday=self.tomorrow.weekday(),
            start_time="09:00",
            end_time="12:00",
        )

    def test_returns_a_list_not_none(self):
        slots = get_available_slots(self.workspace, self.service, self.tomorrow)
        self.assertIsInstance(slots, list)
        self.assertGreater(len(slots), 0)

    def test_booked_slot_is_excluded(self):
        slots_before = get_available_slots(self.workspace, self.service, self.tomorrow)
        first_slot = slots_before[0]

        Booking.objects.create(
            workspace=self.workspace,
            service=self.service,
            customer=self.customer,
            start_at=first_slot,
            end_at=first_slot + timedelta(minutes=self.service.duration_min),
        )

        slots_after = get_available_slots(self.workspace, self.service, self.tomorrow)
        self.assertNotIn(first_slot, slots_after)

    def test_no_rules_returns_empty_list(self):
        AvailabilityRule.objects.all().delete()
        slots = get_available_slots(self.workspace, self.service, self.tomorrow)
        self.assertEqual(slots, [])
