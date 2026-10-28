import time

from django.conf import settings
from django.contrib.auth import logout


class SSOSessionGuardMiddleware:
    """
    Необязательный middleware: ограничивает время жизни локальной сессии,
    созданной через SSO. По истечении MAX_AGE пользователь тихо
    разлогинивается и при следующем обращении к защищённой странице
    заново пройдёт через /sso/login/ -> Auth-сервис (где и проверяется
    актуальный список разрешённых сервисов).

    Подключать НЕ обязательно - без него SSO всё равно работает,
    просто отзыв доступа применится только к новым логинам.
    """

    SESSION_KEY = "sso_authenticated_at"
    MAX_AGE = getattr(settings, "SSO_SESSION_MAX_AGE", 8 * 60 * 60)  # 8 часов

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            issued_at = request.session.get(self.SESSION_KEY)
            if issued_at is None:
                request.session[self.SESSION_KEY] = time.time()
            elif time.time() - issued_at > self.MAX_AGE:
                logout(request)
        return self.get_response(request)
