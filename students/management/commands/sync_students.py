from django.core.management.base import BaseCommand, CommandError

from students.models import StudentSyncLog
from students.services.sync import run_sync


class Command(BaseCommand):
    help = 'Загрузить студентов из вьюхи Oracle'

    def handle(self, *args, **options):
        log = run_sync()
        if log.status == StudentSyncLog.Status.FAILED:
            raise CommandError(log.message)

        self.stdout.write(self.style.SUCCESS(
            f'Строк: {log.total_rows}. Создано: {log.created}, изменено: {log.updated}, '
            f'без изменений: {log.unchanged}, пропущено: {log.skipped}.'
        ))
        for error in log.errors:
            self.stdout.write(self.style.WARNING(error))
