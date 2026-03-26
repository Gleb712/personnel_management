def user_permissions(request):
    """
    Добавляет в контекст шаблона булевы флаги на основе групп пользователя.
    Используется в base.html для показа/скрытия пунктов меню.
    """
    user = request.user
 
    if not user.is_authenticated:
        return {
            'can_upload_files': False,
            'can_edit_data':    False,
            'can_view_admin':   False,
        }
 
    if user.is_superuser:
        return {
            'can_upload_files': True,
            'can_edit_data':    True,
            'can_view_admin':   True,
        }
 
    group_names = set(user.groups.values_list('name', flat=True))
 
    UPLOAD_GROUPS = {'Администратор', 'Директор по персоналу', 'Редактор'}
    EDIT_GROUPS   = {'Администратор', 'Директор по персоналу', 'Редактор'}
 
    return {
        # Показывать ли пункт «Загрузка файлов» в боковом меню
        'can_upload_files': bool(group_names & UPLOAD_GROUPS),
 
        # Показывать ли кнопки редактирования в интерфейсе
        'can_edit_data': bool(group_names & EDIT_GROUPS),
 
        # Показывать ли ссылку «Администрирование» — нужен is_staff
        'can_view_admin': user.is_staff,
    }
