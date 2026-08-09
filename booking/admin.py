from django.contrib import admin

from .models import (
    AvailabilityRule,
    Booking,
    Membership,
    Review,
    Service,
    TimeOff,
    Workspace,
)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "city", "owner", "currency", "created_at")
    search_fields = ("name", "city", "owner__username")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "role", "created_at")
    list_filter = ("role",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "duration_min", "price", "is_active")
    list_filter = ("is_active", "workspace")
    search_fields = ("name", "workspace__name")


@admin.register(AvailabilityRule)
class AvailabilityRuleAdmin(admin.ModelAdmin):
    list_display = ("workspace", "weekday", "start_time", "end_time")
    list_filter = ("weekday", "workspace")


@admin.register(TimeOff)
class TimeOffAdmin(admin.ModelAdmin):
    list_display = ("workspace", "start_at", "end_at", "reason")
    list_filter = ("workspace",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("workspace", "service", "customer", "start_at", "end_at", "status")
    list_filter = ("status", "workspace")
    search_fields = ("customer__username", "workspace__name", "service__name")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("workspace", "customer", "rating", "created_at")
    list_filter = ("rating", "workspace")
