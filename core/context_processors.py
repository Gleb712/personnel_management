from core.models import UserProfile


def user_permissions(request):
    """
    Добавляет в контекст шаблона:
    - флаги доступа (can_upload_files, can_edit_data, can_view_admin)
    - user_display_name: ФИО в формате «Фамилия И.О.» или username если ФИО не заполнено
    """
    user = request.user

    if not user.is_authenticated:
        return {
            'can_upload_files':  False,
            'can_edit_data':     False,
            'can_view_admin':    False,
            'user_display_name': '',
        }

    # Получаем сокращённое ФИО из профиля
    try:
        profile = user.profile
        user_display_name = profile.get_short_name()
    except UserProfile.DoesNotExist:
        user_display_name = user.username
    except Exception:
        user_display_name = user.username

    if user.is_superuser:
        return {
            'can_upload_files':  True,
            'can_edit_data':     True,
            'can_view_admin':    True,
            'user_display_name': user_display_name,
        }

    group_names = set(user.groups.values_list('name', flat=True))

    UPLOAD_GROUPS = {'Администратор', 'Директор по персоналу', 'Редактор'}
    EDIT_GROUPS   = {'Администратор', 'Директор по персоналу', 'Редактор'}

    return {
        'can_upload_files':  bool(group_names & UPLOAD_GROUPS),
        'can_edit_data':     bool(group_names & EDIT_GROUPS),
        'can_view_admin':    user.is_staff,
        'user_display_name': user_display_name,
    }
