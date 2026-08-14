from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import AvailabilityRule, Booking, Service, Workspace
from .services import SlotError, create_booking_atomic, get_available_slots

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


class ProviderAvailabilityViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", password="pw12345", user_type="PROVIDER")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio Two", slug="studio-two")
        self.client.force_login(self.owner)

    def test_invalid_time_range_is_rejected_without_500(self):
        response = self.client.post("/booking/provider/availability/", {
            "weekday": "0",
            "start_time": "17:00",
            "end_time": "09:00",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AvailabilityRule.objects.count(), 0)

    def test_valid_time_range_is_created(self):
        response = self.client.post("/booking/provider/availability/", {
            "weekday": "0",
            "start_time": "09:00",
            "end_time": "17:00",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AvailabilityRule.objects.count(), 1)


class ProviderServicesViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", password="pw12345", user_type="PROVIDER")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio Three", slug="studio-three")
        self.client.force_login(self.owner)

    def test_negative_price_is_rejected(self):
        response = self.client.post("/booking/provider/services/", {
            "name": "Haircut",
            "description": "",
            "duration_min": "30",
            "price": "-10",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Service.objects.count(), 0)

    def test_non_numeric_price_is_rejected(self):
        response = self.client.post("/booking/provider/services/", {
            "name": "Haircut",
            "description": "",
            "duration_min": "30",
            "price": "not-a-number",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Service.objects.count(), 0)

    def test_valid_price_is_saved(self):
        response = self.client.post("/booking/provider/services/", {
            "name": "Haircut",
            "description": "",
            "duration_min": "30",
            "price": "99.90",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Service.objects.get().price, Decimal("99.90"))


class BookConfirmAnonymousTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner4", password="pw12345", user_type="PROVIDER")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio Four", slug="studio-four")
        self.service = Service.objects.create(workspace=self.workspace, name="Haircut", duration_min=30)

    def test_anonymous_user_gets_explanatory_message_and_properly_encoded_next(self):
        start = timezone.now() + timedelta(hours=3)
        url = f"/booking/business/studio-four/book/?service={self.service.id}&start={start.isoformat()}"
        response = self.client.get(url)

        expected_next = urlencode({"next": url})
        self.assertRedirects(
            response, f"/users/login/?{expected_next}",
            fetch_redirect_response=False,
        )

        followed = self.client.get(response.url, follow=True)
        messages_text = [str(m) for m in followed.context["messages"]]
        self.assertTrue(any("log in" in m.lower() for m in messages_text))

    def test_full_round_trip_registering_mid_booking_returns_to_the_same_booking(self):
        """The exact bug found in manual UX testing: the booking URL contains its
        own '&' (service + start params), which must survive being nested inside
        the login/register redirect chain instead of getting truncated."""
        import re

        start = timezone.now() + timedelta(hours=3)
        booking_url = f"/booking/business/studio-four/book/?service={self.service.id}&start={start.isoformat()}"

        response = self.client.get(booking_url)
        login_url = response.url
        self.assertIn(urlencode({"next": booking_url}), login_url)

        # Follow the actual "Create one" link as rendered in the page, rather than
        # hand-building it, since the template's |urlencode filter and Python's
        # urlencode() don't escape identically -- only the real link matters.
        response = self.client.get(login_url)
        match = re.search(r'href="(/users/register/\?next=[^"]+)"', response.content.decode())
        self.assertIsNotNone(match, "Create one link with ?next= not found on login page")
        register_link = match.group(1).replace("&amp;", "&")

        response = self.client.get(register_link)
        self.assertEqual(response.context["next"], booking_url)

        response = self.client.post(register_link, {
            "username": "roundtrip_user",
            "email": "roundtrip@example.com",
            "password": "S0me-Very-Unusual-Pass",
            "role": "CLIENT",
            "next": booking_url,
        })
        self.assertRedirects(response, booking_url, fetch_redirect_response=False)


class WorkspaceDetailAvailabilityTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner5", password="pw12345", user_type="PROVIDER")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio Five", slug="studio-five")

    def test_shows_message_when_no_availability_set(self):
        response = self.client.get("/booking/business/studio-five/")
        self.assertContains(response, "hasn't set their booking hours yet")

    def test_shows_form_when_availability_set(self):
        AvailabilityRule.objects.create(
            workspace=self.workspace, weekday=0, start_time="09:00", end_time="17:00",
        )
        response = self.client.get("/booking/business/studio-five/")
        self.assertContains(response, "See available slots")
        self.assertNotContains(response, "hasn't set their booking hours yet")


class ProviderDashboardChecklistTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner6", password="pw12345", user_type="PROVIDER")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Studio Six", slug="studio-six")
        self.client.force_login(self.owner)

    def test_checklist_shown_when_incomplete(self):
        response = self.client.get("/booking/provider/")
        self.assertContains(response, "Finish setting up your business")

    def test_checklist_hidden_once_complete(self):
        Service.objects.create(workspace=self.workspace, name="Haircut", duration_min=30)
        AvailabilityRule.objects.create(
            workspace=self.workspace, weekday=0, start_time="09:00", end_time="17:00",
        )
        response = self.client.get("/booking/provider/")
        self.assertNotContains(response, "Finish setting up your business")


class CustomErrorPageTests(TestCase):
    def test_404_uses_custom_page(self):
        response = self.client.get("/booking/business/this-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, "Back to Bookora", status_code=404)
