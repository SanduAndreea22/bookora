from __future__ import annotations
import logging
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, ProtectedError, Q, Sum
from urllib.parse import urlencode
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Workspace, Service, AvailabilityRule, TimeOff, Booking, Review
from .services import SlotError, create_booking_atomic, get_available_slots

logger = logging.getLogger(__name__)


def is_provider(user) -> bool:
    return getattr(user, "user_type", "") == "PROVIDER"


def is_client(user) -> bool:
    return getattr(user, "user_type", "CLIENT") == "CLIENT"


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

    reviews = workspace.reviews.select_related("customer").order_by("-created_at")
    rating_stats = reviews.aggregate(average=Avg("rating"), count=Count("id"))

    my_review = None
    can_review = False
    if request.user.is_authenticated and is_client(request.user):
        my_review = reviews.filter(customer=request.user).first()
        if not my_review:
            can_review = Booking.objects.filter(
                workspace=workspace,
                customer=request.user,
                status=Booking.Status.CONFIRMED,
                start_at__lt=timezone.now(),
            ).exists()

    return render(request, "booking/workspace_detail.html", {
        "workspace": workspace,
        "services": services,
        "reviews": reviews,
        "rating_average": rating_stats["average"],
        "rating_count": rating_stats["count"],
        "my_review": my_review,
        "can_review": can_review,
        "has_availability": workspace.availability_rules.exists(),
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
        messages.error(request, "Invalid date.")
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

def book_confirm(request, slug: str):
    workspace = get_object_or_404(Workspace, slug=slug)

    if not request.user.is_authenticated:
        messages.info(request, "Please log in or create a free account to confirm this booking.")
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{reverse('users:login')}?{query}")

    service_id = request.GET.get("service")
    start_str = request.GET.get("start")

    if not service_id or not start_str:
        messages.error(request, "Missing booking details.")
        return redirect("booking:workspace_detail", slug=slug)

    service = get_object_or_404(Service, id=service_id, workspace=workspace)

    start_at = parse_datetime(start_str)
    if not start_at:
        messages.error(request, "Invalid datetime.")
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
            messages.success(request, "Booking created successfully.")
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
    has_services = False
    has_availability = False

    if workspace:
        has_services = workspace.services.exists()
        has_availability = workspace.availability_rules.exists()
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

    # 4. Trend de venituri pe ultimele 7 zile, pentru graficul din dashboard
    revenue_chart = []
    if workspace:
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            total = workspace.bookings.filter(
                start_at__date=day,
                status=Booking.Status.CONFIRMED,
            ).aggregate(total=Sum('service__price'))['total'] or 0
            revenue_chart.append({"label": day.strftime("%d %b"), "value": float(total)})

    return render(request, "booking/provider_home.html", {
        "workspace": workspace,
        "bookings_today": bookings_today,
        "stats": stats,
        "today": today,
        "revenue_chart": revenue_chart,
        "has_services": has_services,
        "has_availability": has_availability,
    })


@login_required(login_url="users:login")
def provider_workspace_create(request):

    if not is_provider(request.user):
        messages.error(request, "Only providers can create a business.")
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

        if not (2 <= len(currency) <= 3) or not currency.isalpha():
            messages.error(request, "Currency must be a 2-3 letter ISO code (e.g. RON, EUR, USD).")
            return redirect("booking:provider_workspace_create")

        base_slug = slugify(name)[:150] or "business"
        slug = base_slug
        i = 2
        for _ in range(20):
            try:
                with transaction.atomic():
                    Workspace.objects.create(
                        owner=request.user,
                        name=name,
                        slug=slug,
                        city=city,
                        address=address,
                        currency=currency,
                    )
                break
            except IntegrityError:
                slug = f"{base_slug}-{i}"
                i += 1
        else:
            logger.warning("Exhausted slug attempts for workspace name=%r", name)
            messages.error(request, "Could not create business, please try again.")
            return redirect("booking:provider_workspace_create")

        messages.success(request, "Business created.")
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

    edit_id = request.POST.get("service_id") if request.method == "POST" else request.GET.get("edit")
    editing_service = get_object_or_404(Service, id=edit_id, workspace=workspace) if edit_id else None

    def redirect_back():
        if editing_service:
            return redirect(f"{reverse('booking:provider_services')}?edit={editing_service.id}")
        return redirect("booking:provider_services")

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
            return redirect_back()

        price = None
        if price_raw:
            try:
                price = Decimal(price_raw)
            except InvalidOperation:
                messages.error(request, "Invalid price.")
                return redirect_back()
            if price < 0:
                messages.error(request, "Price cannot be negative.")
                return redirect_back()

        if editing_service:
            editing_service.name = name
            editing_service.description = description
            editing_service.duration_min = max(5, duration_min)
            editing_service.price = price
            service = editing_service
        else:
            service = Service(
                workspace=workspace,
                name=name,
                description=description,
                duration_min=max(5, duration_min),
                price=price,
                is_active=True,
            )

        try:
            service.full_clean()
            service.save()
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect_back()

        messages.success(request, "Service updated." if editing_service else "Service added.")
        return redirect("booking:provider_services")

    return render(request, "booking/provider_services.html", {
        "workspace": workspace,
        "services": services,
        "currency": workspace.currency,
        "editing_service": editing_service,
    })


@login_required
@require_POST
def toggle_service_active(request, service_id):
    service = get_object_or_404(Service, id=service_id, workspace__owner=request.user)
    service.is_active = not service.is_active
    service.save(update_fields=["is_active"])
    messages.success(request, "Service is now active." if service.is_active else "Service deactivated — hidden from clients.")
    return redirect("booking:provider_services")


@login_required
@require_POST
def delete_service(request, service_id):
    service = get_object_or_404(Service, id=service_id, workspace__owner=request.user)
    try:
        service.delete()
        messages.success(request, "Service deleted.")
    except ProtectedError:
        messages.error(
            request,
            "This service has existing bookings and can't be deleted. "
            "Deactivate it instead so clients stop seeing it.",
        )
    return redirect("booking:provider_services")


@login_required(login_url="users:login")
def provider_availability(request):

    if not is_provider(request.user):
        messages.error(request, "Only providers can manage availability.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()
    if not workspace:
        return redirect("booking:provider_workspace_create")

    rules = workspace.availability_rules.order_by("weekday", "start_time")

    edit_id = request.POST.get("rule_id") if request.method == "POST" else request.GET.get("edit")
    editing_rule = get_object_or_404(AvailabilityRule, id=edit_id, workspace=workspace) if edit_id else None

    def redirect_back():
        if editing_rule:
            return redirect(f"{reverse('booking:provider_availability')}?edit={editing_rule.id}")
        return redirect("booking:provider_availability")

    if request.method == "POST":
        weekday = request.POST.get("weekday")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        if weekday is None or not start_time or not end_time:
            messages.error(request, "Please fill in all fields.")
            return redirect_back()

        try:
            weekday = int(weekday)
        except ValueError:
            messages.error(request, "Invalid weekday.")
            return redirect_back()

        if editing_rule:
            editing_rule.weekday = weekday
            editing_rule.start_time = start_time
            editing_rule.end_time = end_time
            rule = editing_rule
        else:
            rule = AvailabilityRule(
                workspace=workspace,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )

        try:
            rule.full_clean()
            rule.save()
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect_back()

        messages.success(request, "Availability rule updated." if editing_rule else "Availability rule added.")
        return redirect("booking:provider_availability")

    return render(request, "booking/provider_availability.html", {
        "workspace": workspace,
        "rules": rules,
        "weekdays": AvailabilityRule.Weekday.choices,
        "editing_rule": editing_rule,
    })


@login_required
@require_POST
def delete_availability_rule(request, rule_id):
    rule = get_object_or_404(AvailabilityRule, id=rule_id, workspace__owner=request.user)
    rule.delete()
    messages.success(request, "Availability rule removed.")
    return redirect("booking:provider_availability")

@login_required
def provider_timeoff(request):
    if not is_provider(request.user):
        messages.error(request, "Only providers can access this page.")
        return redirect("pages:home")

    workspace = Workspace.objects.filter(owner=request.user).first()

    if not workspace:
        messages.error(request, "Create a business first.")
        return redirect("booking:provider_workspace_create")

    if request.method == "POST":
        start_str = request.POST.get("start_at")
        end_str = request.POST.get("end_at")
        reason = request.POST.get("reason", "")

        start_at = parse_datetime(start_str)
        end_at = parse_datetime(end_str)

        if not start_at or not end_at:
            messages.error(request, "Invalid datetime.")
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
@require_POST
def delete_timeoff(request, timeoff_id):
    timeoff = get_object_or_404(
        TimeOff,
        id=timeoff_id,
        workspace__owner=request.user
    )

    timeoff.delete()
    messages.success(request, "Time block removed.")
    return redirect("booking:provider_timeoff")


@login_required(login_url="users:login")
@require_POST
def leave_review(request, slug: str):
    workspace = get_object_or_404(Workspace, slug=slug)

    if not is_client(request.user):
        messages.error(request, "Only clients can leave reviews.")
        return redirect("booking:workspace_detail", slug=slug)

    last_past_booking = Booking.objects.filter(
        workspace=workspace,
        customer=request.user,
        status=Booking.Status.CONFIRMED,
        start_at__lt=timezone.now(),
    ).order_by("-start_at").first()

    if not last_past_booking:
        messages.error(request, "You can only review a business after a completed booking.")
        return redirect("booking:workspace_detail", slug=slug)

    try:
        rating = int(request.POST.get("rating", 0))
    except ValueError:
        rating = 0
    comment = (request.POST.get("comment") or "").strip()

    if rating < 1 or rating > 5:
        messages.error(request, "Rating must be between 1 and 5.")
        return redirect("booking:workspace_detail", slug=slug)

    review, created = Review.objects.get_or_create(
        workspace=workspace,
        customer=request.user,
        defaults={"rating": rating, "comment": comment, "booking": last_past_booking},
    )

    if not created:
        review.rating = rating
        review.comment = comment
        review.booking = last_past_booking

    try:
        review.full_clean()
        review.save()
        messages.success(request, "Thanks for your review." if created else "Review updated. Thanks!")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))

    return redirect("booking:workspace_detail", slug=slug)

