from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from . import views
from .models import SsoSession

User = get_user_model()
SSO = dict(SSO_SERVER_URL="http://auth.local:8000/", SSO_SERVER_INTERNAL_URL="http://127.0.0.1:8000/",
           SSO_CLIENT_ID="hr", SSO_CLIENT_SECRET="secret")
PAYLOAD = {"sid": "sid-1", "user": {
    "username": "1234", "first_name": "Иван", "last_name": "Иванов", "patronymic": "Петрович",
    "department": "Цех", "position": "Мастер",
}}


@override_settings(**SSO)
class SsoClientTests(TestCase):
    def start_login(self, next_url="/profile/"):
        response = self.client.get(reverse("sso_client:login"), {"next": next_url})
        self.assertEqual(response.status_code, 200)
        url = urlparse(response.context["url"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "http://auth.local:8000/sso/authorize/")
        return parse_qs(url.query)

    def finish_login(self, payload=PAYLOAD):
        params = self.start_login()
        with mock.patch.object(views, "_validate", return_value=payload):
            return self.client.get(reverse("sso_client:callback"), {"ticket": "t1", "state": params["state"][0]})

    def test_guest_goes_to_sso(self):
        response = self.client.get("/profile/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        response = self.client.get("/login/")
        self.assertContains(response, "http://auth.local:8000/sso/authorize/")
        params = self.start_login()
        self.assertEqual(params["client_id"], ["hr"])
        self.assertEqual(params["redirect_uri"], ["http://testserver/sso/callback/"])

    def test_callback_creates_user_and_profile(self):
        response = self.finish_login()
        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)
        user = User.objects.get(username="1234")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(user.profile.full_name, "Иванов Иван Петрович")
        self.assertTrue(SsoSession.objects.filter(sid="sid-1", username="1234").exists())
        self.assertEqual(self.client.get("/profile/").status_code, 200)

    def test_existing_user_keeps_groups_and_data(self):
        local = User.objects.create_user("1234", "old-pass-1!", is_staff=True)
        group = Group.objects.get_or_create(name="Редактор")[0]
        local.groups.add(group)
        UserProfile.objects.create(user=local, role="editor")
        self.finish_login()
        local.refresh_from_db()
        self.assertTrue(local.is_staff)
        self.assertFalse(local.has_usable_password())
        self.assertEqual(list(local.groups.all()), [group])
        self.assertEqual(UserProfile.objects.filter(user=local).count(), 1)
        self.assertEqual(local.profile.role, "editor")
        self.assertEqual(User.objects.count(), 1)

    @override_settings(SSO_AUTO_CREATE=False)
    def test_unknown_user_is_refused_without_auto_create(self):
        response = self.finish_login()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="1234").exists())

    def test_logout_requires_post_and_goes_to_auth(self):
        self.finish_login()
        response = self.client.get("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/profile/").status_code, 200)
        response = self.client.post("/logout/")
        self.assertContains(response, "http://auth.local:8000/sso/logout/")
        self.assertRedirects(self.client.get("/profile/"), "/login/", fetch_redirect_response=False)
        self.assertFalse(SsoSession.objects.exists())

    def test_password_change_goes_to_auth(self):
        self.assertRedirects(self.client.get("/password/change/"), "http://auth.local:8000/password/change/",
                             fetch_redirect_response=False)
