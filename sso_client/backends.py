from django.contrib.auth import get_user_model

User = get_user_model()


class SSOBackend:
    """
    Аутентификация по claims из проверенного JWT, выпущенного центральным
    Auth-сервисом. Пароль не проверяется - доверие базируется на подписи
    токена, которая уже была проверена в views.sso_callback.

    Матчинг идёт по USERNAME_FIELD локальной модели (обычно "username"),
    в который в этом сервисе изначально заносился табельный номер
    сотрудника. Поскольку табельный номер - единый идентификатор во всех
    системах, поиск существующего локального аккаунта происходит
    автоматически, без ручных сопоставлений.

    Не ставится первым в AUTHENTICATION_BACKENDS автоматически - основной
    ModelBackend остаётся рабочим для локальных/служебных учёток.
    """

    def authenticate(self, request, sso_claims=None):
        if not sso_claims:
            return None

        tab_number = sso_claims.get("username")  # табельный номер
        if not tab_number:
            return None

        username_field = getattr(User, "USERNAME_FIELD", "username")
        user, created = User.objects.get_or_create(
            **{username_field: tab_number},
            defaults={"is_active": True},
        )

        if created and hasattr(user, "set_unusable_password"):
            user.set_unusable_password()
            user.save(update_fields=["password"])

        if request is not None:
            request.sso_role = sso_claims.get("role", "")

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
