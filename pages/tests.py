from django.test import TestCase
from django.urls import reverse


class StaticPagesTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("pages:home"))
        self.assertEqual(response.status_code, 200)

    def test_about_page_loads(self):
        response = self.client.get(reverse("pages:about"))
        self.assertEqual(response.status_code, 200)
