from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class RegisterViewTests(TestCase):
    def test_weak_password_is_rejected(self):
        response = self.client.post(reverse("users:register"), {
            "username": "newuser1",
            "email": "newuser1@example.com",
            "password": "111111",
            "role": "CLIENT",
        })
        self.assertRedirects(response, reverse("users:register"))
        self.assertFalse(User.objects.filter(username="newuser1").exists())

    def test_strong_password_creates_user(self):
        response = self.client.post(reverse("users:register"), {
            "username": "newuser2",
            "email": "newuser2@example.com",
            "password": "S0me-Very-Unusual-Pass",
            "role": "CLIENT",
        })
        self.assertRedirects(response, reverse("users:login"))
        self.assertTrue(User.objects.filter(username="newuser2").exists())

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user(username="taken", password="S0me-Very-Unusual-Pass")
        response = self.client.post(reverse("users:register"), {
            "username": "taken",
            "email": "other@example.com",
            "password": "An0ther-Unusual-Pass",
            "role": "CLIENT",
        })
        self.assertRedirects(response, reverse("users:register"))
        self.assertEqual(User.objects.filter(username="taken").count(), 1)


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="loginuser", password="S0me-Very-Unusual-Pass")

    def test_correct_credentials_log_in(self):
        response = self.client.post(reverse("users:login"), {
            "username": "loginuser",
            "password": "S0me-Very-Unusual-Pass",
        })
        self.assertRedirects(response, reverse("pages:home"))

        profile_response = self.client.get(reverse("users:profile"))
        self.assertEqual(profile_response.status_code, 200)

    def test_wrong_password_does_not_log_in(self):
        response = self.client.post(reverse("users:login"), {
            "username": "loginuser",
            "password": "wrong-password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)


class ProfileViewTests(TestCase):
    def test_requires_login(self):
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 302)
