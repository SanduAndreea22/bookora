from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import AvailabilityRule, Booking, Review, Service, Workspace

User = get_user_model()

DEMO_PASSWORD = "demo12345"

BUSINESSES = [
    {
        "owner": "demo_salon",
        "name": "Glow Hair Studio",
        "slug": "glow-hair-studio",
        "city": "Bucharest",
        "address": "Strada Victoriei 12",
        "currency": "RON",
        "services": [
            ("Haircut & Style", "Wash, cut and blow-dry tailored to your face shape.", 45, "120.00"),
            ("Balayage Coloring", "Hand-painted highlights for a natural sun-kissed look.", 120, "450.00"),
            ("Express Blowout", "Quick blowout for when you're in a hurry.", 30, "80.00"),
        ],
    },
    {
        "owner": "demo_dental",
        "name": "Bright Smile Dental",
        "slug": "bright-smile-dental",
        "city": "Cluj-Napoca",
        "address": "Bulevardul Eroilor 45",
        "currency": "RON",
        "services": [
            ("Checkup & Cleaning", "Routine dental exam with professional cleaning.", 30, "200.00"),
            ("Teeth Whitening", "In-office whitening treatment, visible results in one session.", 60, "500.00"),
            ("Consultation", "First-visit consultation and treatment plan.", 20, "100.00"),
        ],
    },
    {
        "owner": "demo_yoga",
        "name": "Zenith Yoga & Pilates",
        "slug": "zenith-yoga-pilates",
        "city": "Timisoara",
        "address": "Piata Unirii 3",
        "currency": "RON",
        "services": [
            ("Private Yoga Session", "One-on-one yoga tailored to your level and goals.", 60, "150.00"),
            ("Pilates Reformer", "Reformer-based full body strength session.", 50, "180.00"),
            ("Group Class Drop-in", "Join any scheduled group class.", 60, "60.00"),
        ],
    },
    {
        "owner": "demo_photo",
        "name": "Aperture Photo Studio",
        "slug": "aperture-photo-studio",
        "city": "Iasi",
        "address": "Strada Lapusneanu 8",
        "currency": "EUR",
        "services": [
            ("Portrait Session", "Studio portrait session with 10 edited photos.", 90, "350.00"),
            ("Product Photography", "Catalog-ready product shots, white background.", 120, "600.00"),
            ("Headshot Quick Session", "Professional headshot in under 30 minutes.", 30, "150.00"),
        ],
    },
]

CLIENTS = ["demo_client1", "demo_client2", "demo_client3"]

REVIEW_COMMENTS = [
    (5, "Absolutely loved it, will book again!"),
    (5, "Professional, punctual, and friendly. Highly recommend."),
    (4, "Great experience overall, small wait but worth it."),
    (5, "Best in the city, no question."),
    (3, "Good service, though a bit pricier than I expected."),
    (4, "Very clean space and attentive staff."),
]


class Command(BaseCommand):
    help = "Seed the database with realistic demo businesses, services, bookings and reviews."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previously seeded demo accounts/workspaces before reseeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        clients = [self._get_or_create_client(username) for username in CLIENTS]

        comment_cycle = iter(REVIEW_COMMENTS * 10)

        for biz in BUSINESSES:
            owner = self._get_or_create_provider(biz["owner"])
            workspace, created = Workspace.objects.get_or_create(
                slug=biz["slug"],
                defaults={
                    "owner": owner,
                    "name": biz["name"],
                    "city": biz["city"],
                    "address": biz["address"],
                    "currency": biz["currency"],
                },
            )
            if not created:
                self.stdout.write(f"Skipping '{biz['name']}' (already seeded).")
                continue

            services = []
            for name, description, duration_min, price in biz["services"]:
                service = Service.objects.create(
                    workspace=workspace,
                    name=name,
                    description=description,
                    duration_min=duration_min,
                    price=price,
                    is_active=True,
                )
                services.append(service)

            # Mon-Fri 09:00-17:00, Saturday 10:00-14:00
            for weekday in range(0, 5):
                AvailabilityRule.objects.create(
                    workspace=workspace, weekday=weekday, start_time="09:00", end_time="17:00",
                )
            AvailabilityRule.objects.create(
                workspace=workspace, weekday=5, start_time="10:00", end_time="14:00",
            )

            self._create_bookings_and_reviews(workspace, services, clients, comment_cycle)

            self.stdout.write(self.style.SUCCESS(f"Seeded '{biz['name']}' ({workspace.slug})."))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Demo accounts use password '{DEMO_PASSWORD}'.\n"
            f"Providers: {', '.join(b['owner'] for b in BUSINESSES)}\n"
            f"Clients: {', '.join(CLIENTS)}"
        ))

    def _reset(self):
        demo_usernames = [b["owner"] for b in BUSINESSES] + CLIENTS
        deleted, _ = User.objects.filter(username__in=demo_usernames).delete()
        self.stdout.write(f"Reset: removed {deleted} related demo objects.")

    def _get_or_create_provider(self, username):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "user_type": "PROVIDER",
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    def _get_or_create_client(self, username):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "user_type": "CLIENT",
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    def _create_bookings_and_reviews(self, workspace, services, clients, comment_cycle):
        now = timezone.now()
        tz = timezone.get_current_timezone()

        # --- Past bookings (for reviews) ---
        past_offsets = [21, 14, 10, 6, 3]
        for i, days_ago in enumerate(past_offsets):
            service = services[i % len(services)]
            client = clients[i % len(clients)]
            day = (now - timedelta(days=days_ago)).date()
            start_at = timezone.make_aware(
                timezone.datetime.combine(day, timezone.datetime.min.time()).replace(hour=10 + i),
                tz,
            )
            end_at = start_at + timedelta(minutes=service.duration_min)

            booking = Booking.objects.create(
                workspace=workspace,
                service=service,
                customer=client,
                start_at=start_at,
                end_at=end_at,
                status=Booking.Status.CONFIRMED,
            )

            rating, comment = next(comment_cycle)
            Review.objects.get_or_create(
                workspace=workspace,
                customer=client,
                defaults={"booking": booking, "rating": rating, "comment": comment},
            )

        # --- Upcoming bookings (today + this week, so dashboards have live data) ---
        upcoming_offsets = [0, 1, 2, 4]
        for i, days_ahead in enumerate(upcoming_offsets):
            service = services[(i + 1) % len(services)]
            client = clients[(i + 1) % len(clients)]
            day = (now + timedelta(days=days_ahead)).date()
            hour = 11 + i if days_ahead > 0 else max((now + timedelta(hours=3)).hour, 9)
            start_at = timezone.make_aware(
                timezone.datetime.combine(day, timezone.datetime.min.time()).replace(hour=min(hour, 16)),
                tz,
            )
            end_at = start_at + timedelta(minutes=service.duration_min)

            if start_at <= now:
                continue

            Booking.objects.get_or_create(
                workspace=workspace,
                service=service,
                customer=client,
                start_at=start_at,
                defaults={"end_at": end_at, "status": Booking.Status.CONFIRMED},
            )
