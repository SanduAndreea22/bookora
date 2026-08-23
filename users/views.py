import logging
from urllib.parse import urlencode

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from .decorators import ratelimit_post
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

User = get_user_model()
logger = logging.getLogger(__name__)


def _safe_next_url(request, next_url):
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return None


@ratelimit_post("register")
def register(request):
    if request.user.is_authenticated:
        return redirect("users:profile")

    next_url = request.POST.get("next") or request.GET.get("next") or ""

    def redirect_to_register():
        if next_url:
            return redirect(f"{reverse('users:register')}?{urlencode({'next': next_url})}")
        return redirect("users:register")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        role = request.POST.get("role", "CLIENT").upper()

        if role not in ["CLIENT", "PROVIDER"]:
            role = "CLIENT"

        errors = []

        if len(username) < 4:
            errors.append("Username must have at least 4 characters.")
        elif User.objects.filter(username=username).exists():
            errors.append("Username already taken.")

        try:
            validate_email(email)
        except ValidationError:
            errors.append("Please enter a valid email address.")
        else:
            if User.objects.filter(email=email).exists():
                errors.append("Email already used.")

        try:
            validate_password(password, user=User(username=username, email=email))
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect_to_register()

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            user_type=role
        )
        login(request, user)
        messages.success(request, "Account created successfully. Welcome to Bookora!")

        safe_next = _safe_next_url(request, next_url)
        return redirect(safe_next or "pages:home")

    return render(request, "users/register.html", {"next": next_url})

@ratelimit_post("login")
def user_login(request):
    if request.user.is_authenticated:
        return redirect("pages:home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}.")
            safe_next = _safe_next_url(request, request.GET.get("next"))
            return redirect(safe_next or "pages:home")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "users/login.html")

@login_required(login_url="users:login")
def profile(request):
    return render(request, "users/profile.html", {
        "user": request.user
    })

@login_required
@require_POST
def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("pages:home")
