from __future__ import annotations
from datetime import datetime, timedelta, date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from .models import Workspace, Service, AvailabilityRule, TimeOff, Booking
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.core.exceptions import ValidationError
from django.utils import timezone

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
    workspace = get_object_or_404(Workspace, slug=slug)
    services = workspace.services.filter(is_active=True).order_by("name")

    return render(request, "booking/workspace_detail.html", {
        "workspace": workspace,
        "services": services,
    })


def slots_view(request, slug: str):
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

    # Ne asigurăm că avem un timezone corect
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())

    end_at = start_at + timedelta(minutes=service.duration_min)

    if request.method == "POST":
        if not is_client(request.user):
            messages.error(request, "Only clients can create bookings.")
            return redirect("booking:workspace_detail", slug=slug)

        # --- VERIFICARE FINALĂ DE SECURITATE ---
        # Re-calculăm sloturile disponibile pentru acea zi
        # Asta verifică automat: trecutul, pragul de 2 ore, regulile de lucru și suprapunerile.
        available_slots = get_available_slots(workspace, service, start_at.date())

        if start_at not in available_slots:
            messages.error(request, "This slot is no longer available or is too close to the current time.")
            return redirect("booking:workspace_detail", slug=slug)

        try:
            # create_booking_atomic se ocupă de blocarea bazei de date (select_for_update)
            create_booking_atomic(
                workspace=workspace,
                service=service,
                customer=request.user,
                start_at=start_at,
                end_at=end_at,
            )
            messages.success(request, "Booking created successfully!")
            return redirect("booking:my_bookings")

        except SlotError as e:
            messages.error(request, str(e))
            return redirect("booking:workspace_detail", slug=slug)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect("booking:workspace_detail", slug=slug)

    return render(request, "booking/book_confirm.html", {
        "workspace": workspace,
        "service": service,
        "start_at": start_at,
        "end_at": end_at,
    })


@login_required(login_url="users:login")
def my_bookings(request):

    if not is_client(request.user):
        messages.error(request, "Only clients can access My bookings.")
        return redirect("pages:home")

    bookings = Booking.objects.filter(customer=request.user).select_related(
        "workspace", "service"
    ).order_by("-start_at")

    return render(request, "booking/my_bookings.html", {"bookings": bookings})


@login_required(login_url="users:login")
def cancel_booking(request, booking_id: int):
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

from django.db.models import Sum
from django.utils import timezone


@login_required(login_url="users:login")
def provider_home(request):
    if not is_provider(request.user):
        messages.error(request, "Only providers can access this page.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()

    # Pregătim datele pentru Dashboard
    now = timezone.now()
    today = now.date()

    bookings_today = []
    stats = {
        "revenue_today": 0,
        "count_today": 0,
        "upcoming_total": 0,
    }

    if workspace:
        # 1. Agenda de azi: Filtrăm toate rezervările confirmate pentru data curentă
        bookings_today = workspace.bookings.filter(
            start_at__date=today,
            status=Booking.Status.CONFIRMED
        ).select_related('customer', 'service').order_by('start_at')

        # 2. Calculăm Venitul de Azi (Accounting touch!)
        # Sumăm prețurile serviciilor pentru programările de astăzi
        stats["revenue_today"] = bookings_today.aggregate(
            total=Sum('service__price')
        )['total'] or 0

        stats["count_today"] = bookings_today.count()

        # 3. Total Rezervări Viitoare (pentru a vedea gradul de ocupare general)
        stats["upcoming_total"] = workspace.bookings.filter(
            start_at__gte=now,
            status=Booking.Status.CONFIRMED
        ).count()

    return render(request, "booking/provider_home.html", {
        "workspace": workspace,
        "bookings_today": bookings_today,
        "stats": stats,
        "today": today,
    })


@login_required(login_url="users:login")
def provider_workspace_create(request):

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
        currency = (request.POST.get("currency") or "RON").strip().upper()

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
            currency=currency,
        )
        messages.success(request, "Workspace created.")
        return redirect("booking:provider_services")

    return render(request, "booking/provider_workspace_form.html")


@login_required(login_url="users:login")
def provider_services(request):

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
        "currency": workspace.currency
    })


@login_required(login_url="users:login")
def provider_availability(request):

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

@login_required
def provider_timeoff(request):
    if not is_provider(request.user):
        messages.error(request, "Only providers can access this page.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()

    if not workspace:
        messages.error(request, "Create a workspace first.")
        return redirect("booking:provider_workspace_create")

    if request.method == "POST":
        start_str = request.POST.get("start_at")
        end_str = request.POST.get("end_at")
        reason = request.POST.get("reason", "")

        start_at = parse_datetime(start_str)
        end_at = parse_datetime(end_str)

        if not start_at or not end_at:
            messages.error(request, "Invalid datetime format.")
            return redirect("booking:provider_timeoff")

        # timezone safety
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at)

        if timezone.is_naive(end_at):
            end_at = timezone.make_aware(end_at)

        timeoff = TimeOff(
            workspace=workspace,
            start_at=start_at,
            end_at=end_at,
            reason=reason,
        )

        try:
            timeoff.full_clean()
            timeoff.save()
            messages.success(request, "Time blocked successfully.")
        except ValidationError as e:
            messages.error(request, e.message)

        return redirect("booking:provider_timeoff")

    timeoffs = workspace.time_off.all()

    return render(request, "booking/provider_timeoff.html", {
        "workspace": workspace,
        "timeoffs": timeoffs,
    })

@login_required
def delete_timeoff(request, timeoff_id):
    timeoff = get_object_or_404(
        TimeOff,
        id=timeoff_id,
        workspace__owner=request.user
    )

    timeoff.delete()
    messages.success(request, "Time block removed.")
    return redirect("booking:provider_timeoff")


def get_available_slots(workspace: Workspace, service: Service, day: date):
    weekday = day.weekday()
    rules = AvailabilityRule.objects.filter(workspace=workspace, weekday=weekday).order_by("start_time")
    if not rules.exists():
        return []

    tz = timezone.get_current_timezone()
    now = timezone.now()

    booking_threshold = now + timedelta(hours=2)

    day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    day_end = day_start + timedelta(days=1)

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

    step = timedelta(minutes=30)

    # --- MODIFICARE AICI: Adăugăm pauza de 15 minute la durata căutată ---
    PAUZA_MIN = 15
    dur_serviciu = timedelta(minutes=service.duration_min)
    dur_cu_pauza = timedelta(minutes=service.duration_min + PAUZA_MIN)

    slots = []
    for rule in rules:
        start_dt = timezone.make_aware(datetime.combine(day, rule.start_time), tz)
        end_dt = timezone.make_aware(datetime.combine(day, rule.end_time), tz)

        t = start_dt
        # Verificăm dacă serviciul + pauza se încadrează în programul de lucru
        while t + dur_cu_pauza <= end_dt:
            candidate_start = t
            candidate_end = t + dur_cu_pauza  # Verificăm ocuparea pentru tot intervalul (45 min)

            if candidate_start < booking_threshold:
                t += step
                continue

            is_occupied = any(
                start < candidate_end and end > candidate_start
                for start, end in all_blocked_intervals
            )

            if not is_occupied:
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
