from django.urls import path
from . import views

app_name = "booking"

urlpatterns = [
    path("services/", views.services_list, name="services_list"),
    path("business/<slug:slug>/", views.workspace_detail, name="workspace_detail"),
    path("business/<slug:slug>/slots/", views.slots_view, name="slots"),
    path("business/<slug:slug>/book/", views.book_confirm, name="book_confirm"),
    path("my-bookings/", views.my_bookings, name="my_bookings"),
    path("my-bookings/<int:booking_id>/cancel/", views.cancel_booking, name="cancel_booking"),
    path("provider/", views.provider_home, name="provider_home"),
    path("provider/workspace/create/", views.provider_workspace_create, name="provider_workspace_create"),
    path("provider/timeoff/", views.provider_timeoff, name="provider_timeoff"),
    path("provider/timeoff/<int:timeoff_id>/delete/", views.delete_timeoff, name="delete_timeoff"),
    path("provider/services/", views.provider_services, name="provider_services"),
    path("provider/availability/", views.provider_availability, name="provider_availability"),
]