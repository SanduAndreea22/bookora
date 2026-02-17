from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    class UserType(models.TextChoices):
        CLIENT = "CLIENT", "Client"
        PROVIDER = "PROVIDER", "Provider"

    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.CLIENT,
    )

    phone = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["username"]

    def __str__(self):
        return self.username
