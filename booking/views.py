from __future__ import annotations
from datetime import datetime, timedelta, date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import slugify
from .models import Workspace, Service, AvailabilityRule, TimeOff, Booking

def is_provider(user) -> bool:
    return getattr(user, "user_type", "") == "PROVIDER"


def is_client(user) -> bool:
    return getattr(user, "user_type", "CLIENT") == "CLIENT"


class SlotError(Exception):
    """User-facing booking error."""


# ============================================================
# Public marketplace
# ============================================================

def services_list(request):
    """
    /services/?q=&city=
    Public: list services across all workspaces.
    """
    q = (request.GET.get("q") or "").strip()
    city = (request.GET.get("city") or "").strip()

    services = Service.objects.filter(is_active=True).select_related("workspace")

    if q:
        services = services.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(workspace__name__icontains=q)
        )

    if city:
        services = services.filter(workspace__city__icontains=city)

    services = services.order_by("name")[:200]

    return render(request, "booking/services_list.html", {
        "services": services,
        "q": q,
        "city": city,
    })


def workspace_detail(request, slug: str):
    """
    /business/<slug>/
    Public: workspace page showing its services.
    """
    workspace = get_object_or_404(Workspace, slug=slug)
    services = workspace.services.filter(is_active=True).order_by("name")

    return render(request, "booking/workspace_detail.html", {
        "workspace": workspace,
        "services": services,
    })


def slots_view(request, slug: str):
    """
    /business/<slug>/slots/?service=<id>&date=YYYY-MM-DD
    Public: see available slots for a service on a day.
    """
    workspace = get_object_or_404(Workspace, slug=slug)

    service_id = request.GET.get("service")
    day_str = request.GET.get("date")

    if not service_id or not day_str:
        messages.error(request, "Missing service or date.")
        return redirect("booking:workspace_detail", slug=slug)

    service = get_object_or_404(Service, id=service_id, workspace=workspace)

    day = parse_date(day_str)
    if not day:
        messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
        return redirect("booking:workspace_detail", slug=slug)

    slots = get_available_slots(workspace=workspace, service=service, day=day)

    return render(request, "booking/slots.html", {
        "workspace": workspace,
        "service": service,
        "day": day,
        "slots": slots,
    })


# ============================================================
# Client booking flow
# ============================================================

@login_required(login_url="users:login")
def book_confirm(request, slug: str):
    """
    /business/<slug>/book/?service=<id>&start=ISO_DATETIME
    Client confirms booking. POST creates booking atomically.
    """
    workspace = get_object_or_404(Workspace, slug=slug)

    service_id = request.GET.get("service")
    start_str = request.GET.get("start")

    if not service_id or not start_str:
        messages.error(request, "Missing booking details.")
        return redirect("booking:workspace_detail", slug=slug)

    service = get_object_or_404(Service, id=service_id, workspace=workspace)

    start_at = parse_datetime(start_str)
    if not start_at:
        messages.error(request, "Invalid start datetime.")
        return redirect("booking:workspace_detail", slug=slug)

    # Ensure timezone-aware
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())

    end_at = start_at + timedelta(minutes=service.duration_min)

    if request.method == "POST":
        if not is_client(request.user):
            messages.error(request, "Only clients can create bookings.")
            return redirect("booking:workspace_detail", slug=slug)

        try:
            create_booking_atomic(
                workspace=workspace,
                service=service,
                customer=request.user,
                start_at=start_at,
                end_at=end_at,
            )
        except SlotError as e:
            messages.error(request, str(e))
            return redirect("booking:workspace_detail", slug=slug)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect("booking:workspace_detail", slug=slug)

        messages.success(request, "Booking created successfully!")
        return redirect("booking:my_bookings")

    return render(request, "booking/book_confirm.html", {
        "workspace": workspace,
        "service": service,
        "start_at": start_at,
        "end_at": end_at,
    })


@login_required(login_url="users:login")
def my_bookings(request):
    """
    /my-bookings/
    Client only.
    """
    if not is_client(request.user):
        messages.error(request, "Only clients can access My bookings.")
        return redirect("pages:home")

    bookings = Booking.objects.filter(customer=request.user).select_related(
        "workspace", "service"
    ).order_by("-start_at")

    return render(request, "booking/my_bookings.html", {"bookings": bookings})


@login_required(login_url="users:login")
def cancel_booking(request, booking_id: int):
    """
    /my-bookings/<id>/cancel/
    Client cancels their booking (soft cancel).
    """
    if not is_client(request.user):
        messages.error(request, "Only clients can cancel bookings.")
        return redirect("pages:home")

    booking = get_object_or_404(Booking, id=booking_id, customer=request.user)

    if request.method == "POST":
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])
        messages.success(request, "Booking cancelled.")
        return redirect("booking:my_bookings")

    return render(request, "booking/cancel_confirm.html", {"booking": booking})


# ============================================================
# Provider setup (NO admin)
# ============================================================

@login_required(login_url="users:login")
def provider_home(request):
    """
    /provider/
    Provider landing page. If no workspace -> create it.
    """
    if not is_provider(request.user):
        messages.error(request, "Only providers can access this page.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()
    return render(request, "booking/provider_home.html", {"workspace": workspace})


@login_required(login_url="users:login")
def provider_workspace_create(request):
    """
    /provider/workspace/create/
    MVP: one workspace per provider.
    """
    if not is_provider(request.user):
        messages.error(request, "Only providers can create a workspace.")
        return redirect("pages:home")

    existing = Workspace.objects.filter(owner=request.user).first()
    if existing:
        return redirect("booking:provider_services")

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        city = (request.POST.get("city") or "").strip()
        address = (request.POST.get("address") or "").strip()

        if len(name) < 3:
            messages.error(request, "Business name must be at least 3 characters.")
            return redirect("booking:provider_workspace_create")

        base_slug = slugify(name)[:150] or "business"
        slug = base_slug
        i = 2
        while Workspace.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{i}"
            i += 1

        Workspace.objects.create(
            owner=request.user,
            name=name,
            slug=slug,
            city=city,
            address=address,
        )
        messages.success(request, "Workspace created.")
        return redirect("booking:provider_services")

    return render(request, "booking/provider_workspace_form.html")


@login_required(login_url="users:login")
def provider_services(request):
    """
    /provider/services/
    Create and list services for the provider workspace.
    """
    if not is_provider(request.user):
        messages.error(request, "Only providers can manage services.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()
    if not workspace:
        return redirect("booking:provider_workspace_create")

    services = workspace.services.order_by("name")

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        description = (request.POST.get("description") or "").strip()
        duration_raw = (request.POST.get("duration_min") or "30").strip()
        price_raw = (request.POST.get("price") or "").strip()

        try:
            duration_min = int(duration_raw)
        except ValueError:
            duration_min = 30

        if len(name) < 2:
            messages.error(request, "Service name is too short.")
            return redirect("booking:provider_services")

        Service.objects.create(
            workspace=workspace,
            name=name,
            description=description,
            duration_min=max(5, duration_min),
            price=price_raw or None,
            is_active=True,
        )
        messages.success(request, "Service added.")
        return redirect("booking:provider_services")

    return render(request, "booking/provider_services.html", {
        "workspace": workspace,
        "services": services,
    })


@login_required(login_url="users:login")
def provider_availability(request):
    """
    /provider/availability/
    Add weekly availability rules.
    """
    if not is_provider(request.user):
        messages.error(request, "Only providers can manage availability.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()
    if not workspace:
        return redirect("booking:provider_workspace_create")

    rules = workspace.availability_rules.order_by("weekday", "start_time")

    if request.method == "POST":
        weekday = request.POST.get("weekday")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        if weekday is None or not start_time or not end_time:
            messages.error(request, "Please fill all fields.")
            return redirect("booking:provider_availability")

        try:
            AvailabilityRule.objects.create(
                workspace=workspace,
                weekday=int(weekday),
                start_time=start_time,
                end_time=end_time,
            )
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect("booking:provider_availability")

        messages.success(request, "Availability rule added.")
        return redirect("booking:provider_availability")

    return render(request, "booking/provider_availability.html", {
        "workspace": workspace,
        "rules": rules,
        "weekdays": AvailabilityRule.Weekday.choices,
    })


# ============================================================
# Booking logic
# ============================================================

def get_available_slots(workspace: Workspace, service: Service, day: date):
    """
    Returns list of timezone-aware datetime starts in 30-minute increments.
    """
    weekday = day.weekday()
    rules = AvailabilityRule.objects.filter(workspace=workspace, weekday=weekday).order_by("start_time")
    if not rules.exists():
        return []

    tz = timezone.get_current_timezone()
    now = timezone.now()

    day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    day_end = day_start + timedelta(days=1)

    existing = Booking.objects.filter(
        workspace=workspace,
        status=Booking.Status.CONFIRMED,
        start_at__lt=day_end,
        end_at__gt=day_start,
    )

    time_off = TimeOff.objects.filter(
        workspace=workspace,
        start_at__lt=day_end,
        end_at__gt=day_start,
    )

    step = timedelta(minutes=30)
    dur = timedelta(minutes=service.duration_min)

    slots = []
    for rule in rules:
        start_dt = timezone.make_aware(datetime.combine(day, rule.start_time), tz)
        end_dt = timezone.make_aware(datetime.combine(day, rule.end_time), tz)

        t = start_dt
        while t + dur <= end_dt:
            candidate_start = t
            candidate_end = t + dur

            if candidate_start < now:
                t += step
                continue

            if time_off.filter(start_at__lt=candidate_end, end_at__gt=candidate_start).exists():
                t += step
                continue

            if existing.filter(start_at__lt=candidate_end, end_at__gt=candidate_start).exists():
                t += step
                continue

            slots.append(candidate_start)
            t += step

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

