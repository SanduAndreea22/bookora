# bookora/urls.py

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    path("", include("pages.urls")),        # homepage + pagini statice
    path("users/", include("users.urls")),  # auth
    path("booking/", include("booking.urls")),  # booking system
    path("api/", include("booking.api_urls")),  # read-only REST API
    path("api-auth/", include("rest_framework.urls")),  # browsable API login
]
