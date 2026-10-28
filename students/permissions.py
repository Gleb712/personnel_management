from functools import wraps

from django.shortcuts import redirect

from core.permissions import GROUP_ADMIN, _user_in_groups


GROUP_STUDENTS = 'Работа со студентами'


def user_can_access_students(user):
    """Раздел «Студенты»: администраторы и группа «Работа со студентами»."""
    return _user_in_groups(user, GROUP_ADMIN, GROUP_STUDENTS)


def can_access_students(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if user_can_access_students(request.user):
            return view_func(request, *args, **kwargs)
        return redirect('core:access_denied')
    return wrapper
