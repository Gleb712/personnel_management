from .permissions import user_can_access_students


def students_access(request):
    """Флаг для пункта меню «Студенты»."""
    return {'can_access_students': user_can_access_students(request.user)}
