from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


GROUP_ADMIN  = "Администратор"
GROUP_HR     = "Директор по персоналу"
GROUP_EDITOR = "Редактор"
GROUP_VIEWER = "Просмотр"

UPLOAD_GROUPS = {GROUP_ADMIN, GROUP_HR, GROUP_EDITOR}
EDIT_GROUPS   = {GROUP_ADMIN, GROUP_HR, GROUP_EDITOR}


def _user_in_groups(user, *group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def login_required_custom(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        return view_func(request, *args, **kwargs)
    return wrapper


def can_upload(view_func):
    """
    Загрузка файлов — Администратор, Директор по персоналу, Редактор.
    Группа «Просмотр»: редирект на страницу «Нет доступа» (не сообщение).
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if _user_in_groups(request.user, GROUP_ADMIN, GROUP_HR, GROUP_EDITOR):
            return view_func(request, *args, **kwargs)
        return redirect('core:access_denied')
    return wrapper


def can_edit(view_func):
    """
    Редактирование — Администратор, Директор по персоналу, Редактор.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if _user_in_groups(request.user, GROUP_ADMIN, GROUP_HR, GROUP_EDITOR):
            return view_func(request, *args, **kwargs)
        return redirect('core:access_denied')
    return wrapper


def can_view(view_func):
    """Минимальный доступ — любой авторизованный пользователь."""
    return login_required_custom(view_func)