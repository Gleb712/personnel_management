from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Очистка таблиц сотрудников и справочников'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Очистить также все справочники (производства, цеха, должности и т.д.)'
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Пропустить подтверждение'
        )

    def handle(self, *args, **options):
        clear_all = options['all']
        skip_confirm = options['yes']

        if clear_all:
            msg = 'Будут удалены ВСЕ данные: сотрудники + все справочники.'
        else:
            msg = 'Будут удалены все сотрудники. Справочники сохранятся.'

        self.stdout.write(self.style.WARNING(msg))

        if not skip_confirm:
            confirm = input('Продолжить? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write('Отменено.')
                return

        with connection.cursor() as cursor:
            # Отключаем проверку FK чтобы порядок удаления не был важен
            cursor.execute('TRUNCATE TABLE core_employee RESTART IDENTITY CASCADE;')
            self.stdout.write(self.style.SUCCESS('✓ Таблица сотрудников очищена'))

            if clear_all:
                for table in [
                    'core_workshop',
                    'core_production',
                    'core_dismissalreason',
                    'core_employeecategory',
                    'core_position',
                ]:
                    cursor.execute(f'TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;')
                    self.stdout.write(self.style.SUCCESS(f'✓ {table} очищена'))

        self.stdout.write(self.style.SUCCESS('\nГотово.'))
        