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

    def test_strong_password_creates_user_and_logs_in_automatically(self):
        response = self.client.post(reverse("users:register"), {
            "username": "newuser2",
            "email": "newuser2@example.com",
            "password": "S0me-Very-Unusual-Pass",
            "role": "CLIENT",
        })
        self.assertRedirects(response, reverse("pages:home"))
        self.assertTrue(User.objects.filter(username="newuser2").exists())

        # auto-logged in, no second login required
        profile_response = self.client.get(reverse("users:profile"))
        self.assertEqual(profile_response.status_code, 200)

    def test_register_redirects_to_next_after_success(self):
        next_url = reverse("booking:my_bookings")
        response = self.client.post(f"{reverse('users:register')}?next={next_url}", {
            "username": "newuser3",
            "email": "newuser3@example.com",
            "password": "S0me-Very-Unusual-Pass",
            "role": "CLIENT",
            "next": next_url,
        })
        self.assertRedirects(response, next_url)

    def test_register_ignores_unsafe_next(self):
        response = self.client.post(f"{reverse('users:register')}?next=https://evil.example.com/", {
            "username": "newuser4",
            "email": "newuser4@example.com",
            "password": "S0me-Very-Unusual-Pass",
            "role": "CLIENT",
            "next": "https://evil.example.com/",
        })
        self.assertRedirects(response, reverse("pages:home"))

    def test_all_validation_errors_shown_together(self):
        response = self.client.post(reverse("users:register"), {
            "username": "ab",
            "email": "not-an-email",
            "password": "123",
            "role": "CLIENT",
        }, follow=True)
        messages_text = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("at least 4 characters" in m for m in messages_text))
        self.assertTrue(any("valid email" in m for m in messages_text))
        self.assertTrue(len(messages_text) >= 2)

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

    def test_login_redirects_to_next(self):
        next_url = reverse("booking:my_bookings")
        response = self.client.post(f"{reverse('users:login')}?next={next_url}", {
            "username": "loginuser",
            "password": "S0me-Very-Unusual-Pass",
        })
        self.assertRedirects(response, next_url)

    def test_login_ignores_unsafe_next(self):
        response = self.client.post(f"{reverse('users:login')}?next=https://evil.example.com/", {
            "username": "loginuser",
            "password": "S0me-Very-Unusual-Pass",
        })
        self.assertRedirects(response, reverse("pages:home"))


class ProfileViewTests(TestCase):
    def test_requires_login(self):
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 302)

    def test_page_has_exactly_one_h1(self):
        user = User.objects.create_user(username="a11yuser", password="S0me-Very-Unusual-Pass")
        self.client.force_login(user)
        response = self.client.get(reverse("users:profile"))
        self.assertContains(response, f"<h1>{user.username}</h1>", count=1)
