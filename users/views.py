from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model

User = get_user_model()

def register(request):
    if request.user.is_authenticated:
        return redirect("users:profile")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        role = request.POST.get("role", "CLIENT").upper()

        if len(username) < 4:
            messages.error(request, "Username must have at least 4 characters.")
            return redirect("users:register")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return redirect("users:register")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already used.")
            return redirect("users:register")

        if len(password) < 6:
            messages.error(request, "Password must have at least 6 characters.")
            return redirect("users:register")

        if role not in ["CLIENT", "PROVIDER"]:
            role = "CLIENT"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            user_type=role
        )

        messages.success(request, "Account created successfully. You can now log in.")
        return redirect("users:login")

    return render(request, "users/register.html")

def user_login(request):
    if request.user.is_authenticated:
        return redirect("pages:home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get("next")
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect(next_url or "pages:home")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "users/login.html")

@login_required(login_url="users:login")
def profile(request):
    return render(request, "users/profile.html", {
        "user": request.user
    })

@login_required
def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("pages:home")
