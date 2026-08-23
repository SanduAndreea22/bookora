from functools import wraps

from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect


def _client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def ratelimit_post(key_prefix, limit=10, period_seconds=300):
    """Throttle POST requests per client IP. Best-effort protection against
    scripted brute force; relies on Django's cache backend (per-process by
    default), so a shared cache (e.g. Redis) is recommended for multi-worker
    deployments."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.method == 'POST':
                cache_key = f"ratelimit:{key_prefix}:{_client_ip(request)}"
                attempts = cache.get(cache_key, 0)
                if attempts >= limit:
                    messages.error(request, "Too many attempts. Please try again in a few minutes.")
                    return redirect(request.path)
                cache.set(cache_key, attempts + 1, period_seconds)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
