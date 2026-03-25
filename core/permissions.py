from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


# Названия групп пользователей
GROUP_HR = "Директор по персоналу"
GROUP_EDITOR = "Редактор"
GROUP_VIEWER = "Просмотр"


def _user_in_groups(user, *group_names):
    """Проверяет принадлежность пользователя к одной из групп"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()

def _get_login_redirect(user):
    """Куда редиректить после авторизации"""
    # Администратор
    if user.is_superuser:
        return '/upload/'
    # Директор по персоналу и просмотрщики
    if user.groups.filter(name__in=[GROUP_HR, GROUP_VIEWER]).exists():
        return '/reports/headcount/'
    return '/upload/'

def login_required_custom(view_func):
    """Редиректит неавторизованных пользователей на страницу входа"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        return view_func(request, *args, **kwargs)
    return wrapper

def can_upload(view_func):
    """Загрузка файлов в систему - доступ у GROUP_HR, GROUP_EDITOR"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if _user_in_groups(request.user, GROUP_HR, GROUP_EDITOR):
            return view_func(request, *args, **kwargs)
        messages.error(request, 'У вас нет доступа к этой странице')
        return redirect('core:access_denied')
    return wrapper


def can_edit(view_func):
    """Редактирование данных в системе - доступ у GROUP_HR, GROUP_EDITOR"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if _user_in_groups(request.user, GROUP_HR, GROUP_EDITOR):
            return view_func(request, *args, **kwargs)
        messages.error(request, 'У вас нет доступа к этой странице')
        return redirect('core:access_denied')
    return wrapper


def can_view(view_func):
    """Минимальный доступ — любой авторизованный пользователь"""
    return login_required_custom(view_func)

def redirect_by_role(user):
    """Возвращает HTTPRedirect в зависимости от роли пользователя"""
    from django.shortcuts import redirect
    return redirect(_get_login_redirect(user))
