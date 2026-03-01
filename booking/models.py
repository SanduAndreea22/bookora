from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


# ====================================
# 🏢 MODEL: Workspace (Business)
# ====================================

class Workspace(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_workspaces",
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    city = models.CharField(max_length=120, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    currency = models.CharField(
        max_length=3,
        default="RON",
        help_text="Codul ISO al monedei (ex: RON, EUR, USD)"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ====================================
# 🧑‍💼 MODEL: Membership (Owner/Staff)
# ====================================

class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        STAFF = "STAFF", "Staff"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "workspace"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.workspace} ({self.role})"


# ====================================
# 🛎️ MODEL: Service
# ====================================

class Service(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="services",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    duration_min = models.PositiveIntegerField(default=30)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["workspace", "name"]

    def __str__(self):
        return f"{self.name} ({self.duration_min} min)"

    @property
    def formatted_price(self):
        if self.price is not None:
            return f"{self.price} {self.workspace.currency}"
        return "Free"


# ====================================
# 🗓️ MODEL: AvailabilityRule (Weekly schedule)
# ====================================

class AvailabilityRule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="availability_rules",
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["workspace", "weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="availability_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.workspace} {self.get_weekday_display()} {self.start_time}-{self.end_time}"


# ====================================
# 🛑 MODEL: TimeOff (Closed times)
# ====================================

class TimeOff(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="time_off",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-start_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="timeoff_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.workspace}: {self.start_at} - {self.end_at}"

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("End time must be after start time.")


# ====================================
# 📌 MODEL: Booking (Appointment)
# ====================================

class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["workspace", "start_at"]),
            models.Index(fields=["workspace", "end_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="booking_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.customer} — {self.service} @ {self.start_at}"

    def clean(self):
        # Basic validation
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("End time must be after start time.")

        # Overlap check (no double booking)
        qs = Booking.objects.filter(
            workspace=self.workspace,
            status=Booking.Status.CONFIRMED,
        ).filter(
            Q(start_at__lt=self.end_at) & Q(end_at__gt=self.start_at)
        )

        if self.pk:
            qs = qs.exclude(pk=self.pk)

        if qs.exists():
            raise ValidationError("This time slot is already booked.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)