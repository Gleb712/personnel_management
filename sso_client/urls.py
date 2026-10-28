"""
Подключение в config/urls.py проекта:

    from sso_client.urls import overrides as sso_overrides

    urlpatterns = [
        *sso_overrides,                              # первыми: перекрывают вход, выход и смену пароля
        path('sso/', include('sso_client.urls')),
        path('admin/', admin.site.urls),
        ...
    ]

overrides занимают адреса /login/, /logout/, /password/change/ и /admin/password_change/, поэтому
шаблоны и настройки проекта ({% url 'core:logout' %}, LOGIN_URL = 'core:login') менять не нужно:
имена маршрутов остаются прежними, а запросы по этим адресам обрабатывает единый вход.
Если в проекте адреса другие, используйте make_overrides(...) (см. ниже) или направьте проект на
/sso/login/ и /sso/logout/ напрямую (LOGIN_URL = '/sso/login/', форма выхода с action="/sso/logout/").
"""
from django.urls import path

from . import views

app_name = "sso_client"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("callback/", views.callback, name="callback"),
    path("logout/", views.logout, name="logout"),
    path("backchannel-logout/", views.backchannel_logout, name="backchannel_logout"),
]

def make_overrides(login="login/", logout="logout/", password_change=("password/change/", "admin/password_change/")):
    """
    Адреса входа, выхода и смены пароля, которые занимает единый вход. По умолчанию - адреса каркаса;
    если в проекте они другие, укажите свои (без начального «/»):

        *make_overrides(login="accounts/login/", logout="accounts/logout/", password_change=("accounts/password/",))
    """
    paths = [path(login, views.login), path(logout, views.logout)]
    paths += [path(p, views.password_change) for p in password_change]
    return paths


overrides = make_overrides()
