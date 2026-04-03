from collections import defaultdict

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import User, Group
from django.utils.html import format_html, mark_safe

from core.models import (
    Employee, Production, Workshop,
    DismissalReason, EmployeeCategory, Position,
    UserProfile
)

GROUP_META = {
    'Директор по персоналу': {
        'icon': '👤',
        'desc': 'Загрузка файлов, просмотр и редактирование сотрудников, '
                'работа со справочниками (без удаления), все отчёты.',
    },
    'Редактор': {
        'icon': '✏️',
        'desc': 'Загрузка файлов, добавление и редактирование сотрудников, '
                'просмотр отчётов. Справочники — только чтение.',
    },
    'Просмотр': {
        'icon': '👁️',
        'desc': 'Только просмотр списка сотрудников и отчётов.',
    },
    'Администратор': {
        'icon': '🔧',
        'desc': 'Полный доступ к данным. Управление пользователями через /admin/. '
                'Для входа в /admin/ нужен флаг is_staff.',
    },
}

ACTION_RU = {'add': 'добавление', 'change': 'изменение', 'delete': 'удаление', 'view': 'просмотр'}
MODEL_RU = {
    'employee': 'Сотрудники', 'production': 'Производства',
    'workshop': 'Цеха', 'dismissalreason': 'Причины увольнений',
    'employeecategory': 'Категории работников', 'position': 'Должности',
    'user': 'Пользователи',
}

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name = 'Данные сотрудника'
    verbose_name_plural = 'Данные сотрудника'
    fields = ('full_name',)
    extra = 1
    max_num = 1

# Пользователи
class UserAdmin(BaseUserAdmin):
    inlines      = [UserProfileInline]
    list_display = ('username', 'email', 'get_fio',
                    'get_groups_display', 'is_active', 'is_staff')
    list_filter   = ('is_active', 'is_staff', 'groups')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering      = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Личные данные', {'fields': ('first_name', 'last_name', 'email')}),
        ('Флаги доступа', {
            'fields': ('is_active', 'is_staff', 'is_superuser'),
            'description': (
                '<b>is_staff</b> — разрешает вход в /admin/. Нужен для группы «Администратор».<br>'
                '<b>is_superuser</b> — полный доступ без ограничений. Только для разработчиков.'
            ),
        }),
        ('Роль пользователя', {
            'fields': ('groups',),
            'description': (
                'Выберите <b>одну группу</b> — права выдаются автоматически.<br>'
                '<table style="margin-top:8px;font-size:12px;border-collapse:collapse">'
                '<tr><td style="padding:3px 12px 3px 0"><b>👤 Директор по персоналу</b></td>'
                '<td style="color:#666">загрузка + редактирование + отчёты</td></tr>'
                '<tr><td style="padding:3px 12px 3px 0"><b>✏️ Редактор</b></td>'
                '<td style="color:#666">загрузка + редактирование сотрудников + отчёты</td></tr>'
                '<tr><td style="padding:3px 12px 3px 0"><b>👁 Просмотр</b></td>'
                '<td style="color:#666">только список сотрудников и отчёты</td></tr>'
                '<tr><td style="padding:3px 12px 3px 0"><b>🔧 Администратор</b></td>'
                '<td style="color:#666">полный доступ к данным + /admin/ (нужен is_staff)</td></tr>'
                '</table>'
            ),
        }),
        ('Важные даты', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2',
                       'first_name', 'last_name', 'email',
                       'is_active', 'is_staff', 'groups'),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            # Администратор не может назначать суперправа и прямые permissions
            return ('is_superuser', 'user_permissions', 'last_login', 'date_joined')
        return ('last_login', 'date_joined')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            # Администратор не видит суперпользователей
            qs = qs.filter(is_superuser=False)
        return qs

    def has_delete_permission(self, request, obj=None):
        # Администратор не может удалять пользователей — только суперпользователь
        if not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    @admin.display(description='ФИО')
    def get_fio(self, obj):
        try:
            name = obj.profile.full_name
            return name if name else mark_safe('<span style="color:#9ca3af">—</span>')
        except Exception:
            return mark_safe('<span style="color:#9ca3af">—</span>')

    @admin.display(description='Роль / Группа')
    def get_groups_display(self, obj):
        if obj.is_superuser:
            return mark_safe('<span style="color:#f59e0b;font-weight:600">⚡ Суперпользователь</span>')
        groups = list(obj.groups.values_list('name', flat=True))
        if not groups:
            return mark_safe('<span style="color:#9ca3af;font-style:italic">не назначена</span>')
        parts = [f'{GROUP_META.get(g, {}).get("icon", "•")} {g}' for g in groups]
        return format_html('<span>{}</span>', ' | '.join(parts))


# Группы (только просмотр для администратора)

class GroupAdmin(BaseGroupAdmin):
    list_display = ('get_name_display', 'get_description', 'get_user_count', 'get_permissions_display')
    search_fields = ('name',)

    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            # Администратор видит группы, но не может их редактировать
            return ('name', 'permissions')
        return ()

    def has_add_permission(self, request):
        # Только суперпользователь может создавать новые группы
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        # Только суперпользователь может удалять группы
        return request.user.is_superuser
    
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """
        Ограничивает список доступных групп для роли администратора.
        Ограничиваем список видимых групп до 4 стандартных.
        """
        if db_field.name == 'groups' and not request.user.is_superuser:
            from django.contrib.auth.models import Group
            kwargs['queryset'] = Group.objects.filter(name__in=[
                'Администратор',
                'Директор по персоналу',
                'Редактор',
                'Просмотр',
            ])
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def has_change_permission(self, request, obj=None):
        # Администратор может открыть группу для просмотра, но не сохранить
        return True

    @admin.display(description='Группа')
    def get_name_display(self, obj):
        icon = GROUP_META.get(obj.name, {}).get('icon', '👥')
        return format_html('<strong>{} {}</strong>', icon, obj.name)

    @admin.display(description='Описание')
    def get_description(self, obj):
        desc = GROUP_META.get(obj.name, {}).get('desc', '—')
        return mark_safe(f'<span style="color:#555;font-size:12px">{desc}</span>')

    @admin.display(description='Пользователей')
    def get_user_count(self, obj):
        count = obj.user_set.count()
        if count == 0:
            return mark_safe('<span style="color:#9ca3af">0</span>')
        return format_html(
            '<a href="/admin/auth/user/?groups__id__exact={}" style="font-weight:600;color:#3b82f6">{} чел.</a>',
            obj.pk, count
        )

    @admin.display(description='Права на данные')
    def get_permissions_display(self, obj):
        perms = list(
            obj.permissions
            .select_related('content_type')
            .values_list('content_type__app_label', 'content_type__model', 'codename')
        )
        if not perms:
            return mark_safe('<span style="color:#9ca3af">нет прав</span>')

        by_model = defaultdict(list)
        for app, model, codename in perms:
            if app not in ('core', 'auth'):
                continue
            action = codename.split('_')[0]
            model_ru = MODEL_RU.get(model, model)
            by_model[model_ru].append(ACTION_RU.get(action, action))

        lines = [
            f'<span style="font-size:11px"><b style="color:#555">{m}:</b> '
            f'<span style="color:#777">{", ".join(a)}</span></span>'
            for m in sorted(by_model) for a in [by_model[m]]
        ]
        return mark_safe('<br>'.join(lines))


admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)


# Сотрудники

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display    = ['employee_number', 'full_name', 'hire_date', 'dismissal_date',
                       'production', 'workshop', 'position', 'employee_category', 'get_status']
    list_filter     = ['production', 'workshop', 'employee_category', 'position', 'dismissal_reason']
    search_fields   = ['full_name', 'employee_number']
    date_hierarchy  = 'hire_date'
    readonly_fields = ['created_at', 'updated_at', 'production']
    list_per_page   = 100

    fieldsets = (
        ('Основное',     {'fields': ('full_name', 'employee_number', 'birth_date')}),
        ('Даты работы',  {'fields': ('hire_date', 'dismissal_date', 'dismissal_reason'),
                          'description': 'Если сотрудник работает — поле «Дата увольнения» оставьте пустым.'}),
        ('Место работы', {'fields': ('workshop', 'production', 'position', 'employee_category'),
                          'description': 'Производство заполняется автоматически по цеху.'}),
        ('Служебное',    {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(boolean=True, description='Работает')
    def get_status(self, obj):
        return obj.dismissal_date is None

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'production', 'workshop', 'position', 'employee_category', 'dismissal_reason'
        )


# Справочники

@admin.register(Production)
class ProductionAdmin(admin.ModelAdmin):
    list_display  = ['name', 'get_workshop_count', 'get_employee_count']
    search_fields = ['name']

    @admin.display(description='Цехов')
    def get_workshop_count(self, obj):
        return obj.workshops.count()

    @admin.display(description='Сотрудников')
    def get_employee_count(self, obj):
        return obj.production_employees.count()


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display        = ['number', 'name', 'production', 'get_employee_count']
    list_filter         = ['production']
    search_fields       = ['number', 'name']
    list_select_related = ['production']

    @admin.display(description='Сотрудников')
    def get_employee_count(self, obj):
        return obj.workshop_employees.count()


@admin.register(DismissalReason)
class DismissalReasonAdmin(admin.ModelAdmin):
    list_display  = ['name', 'get_count']
    search_fields = ['name']

    @admin.display(description='Использований')
    def get_count(self, obj):
        return obj.dismissal_employees.count()


@admin.register(EmployeeCategory)
class EmployeeCategoryAdmin(admin.ModelAdmin):
    list_display  = ['name', 'get_count']
    search_fields = ['name']

    @admin.display(description='Сотрудников')
    def get_count(self, obj):
        return obj.category_employees.count()


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display  = ['name', 'get_count']
    search_fields = ['name']

    @admin.display(description='Сотрудников')
    def get_count(self, obj):
        return obj.position_employees.count()
