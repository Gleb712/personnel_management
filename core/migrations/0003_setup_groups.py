"""
Содержимое для core/migrations/0003_setup_groups.py

Создать пустую миграцию:
    python manage.py makemigrations core --empty --name=setup_groups

Затем вставить этот код в созданный файл.
"""
from django.db import migrations


def create_groups(apps, schema_editor):
    Group       = apps.get_model('auth', 'Group')
    Permission  = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    def perms(app_label, model_name, *actions):
        try:
            ct = ContentType.objects.get(app_label=app_label, model=model_name)
        except ContentType.DoesNotExist:
            return []
        codenames = [f'{a}_{model_name}' for a in actions]
        return list(Permission.objects.filter(content_type=ct, codename__in=codenames))

    GROUPS = {

        'Директор по персоналу': (
            perms('core', 'employee',         'view', 'add', 'change', 'delete') +
            perms('core', 'production',       'view', 'add', 'change') +
            perms('core', 'workshop',         'view', 'add', 'change') +
            perms('core', 'dismissalreason',  'view', 'add', 'change') +
            perms('core', 'employeecategory', 'view', 'add', 'change') +
            perms('core', 'position',         'view', 'add', 'change')
        ),

        'Редактор': (
            perms('core', 'employee',         'view', 'add', 'change') +
            perms('core', 'production',       'view') +
            perms('core', 'workshop',         'view') +
            perms('core', 'dismissalreason',  'view') +
            perms('core', 'employeecategory', 'view') +
            perms('core', 'position',         'view')
        ),

        'Просмотр': (
            perms('core', 'employee',         'view') +
            perms('core', 'production',       'view') +
            perms('core', 'workshop',         'view') +
            perms('core', 'dismissalreason',  'view') +
            perms('core', 'employeecategory', 'view') +
            perms('core', 'position',         'view')
        ),

        # Администратор:
        # — полный доступ к данным core
        # — view/change/add на auth.user (видит список, редактирует, меняет пароль)
        # — НЕТ прав на auth.group (не может менять состав групп)
        'Администратор': (
            perms('core', 'employee',         'view', 'add', 'change', 'delete') +
            perms('core', 'production',       'view', 'add', 'change', 'delete') +
            perms('core', 'workshop',         'view', 'add', 'change', 'delete') +
            perms('core', 'dismissalreason',  'view', 'add', 'change', 'delete') +
            perms('core', 'employeecategory', 'view', 'add', 'change', 'delete') +
            perms('core', 'position',         'view', 'add', 'change', 'delete') +
            # Права на пользователей: просмотр, редактирование, добавление
            # (добавление нужно чтобы сбрасывать пароль через форму Django)
            perms('auth', 'user',             'view', 'add', 'change')
        ),
    }

    for group_name, permissions in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        if permissions:
            group.permissions.add(*permissions)


def remove_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=[
        'Директор по персоналу', 'Редактор', 'Просмотр', 'Администратор',
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_userprofile'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
