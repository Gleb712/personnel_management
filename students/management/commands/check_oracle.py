from django.core.management.base import BaseCommand, CommandError

from students.services import oracle_source as src


class Command(BaseCommand):
    help = 'Проверить подключение к вьюхе Oracle: колонки, сопоставление, число строк, значения «Вид приема»'

    def handle(self, *args, **options):
        try:
            conn = src.connect()
        except Exception as exc:
            raise CommandError(f'Не удалось подключиться: {exc}')

        with conn, conn.cursor() as cur:
            cur.execute(f'SELECT * FROM {src.VIEW_NAME} WHERE ROWNUM <= 1')
            description = cur.description
            cur.fetchall()

            self.stdout.write('Колонки вьюхи (имя — тип):')
            for d in description:
                self.stdout.write(f'  {d[0]} — {getattr(d[1], "name", d[1])}')

            try:
                src.column_positions(description)
                self.stdout.write(self.style.SUCCESS('Все колонки из COLUMNS найдены.'))
            except RuntimeError as exc:
                self.stdout.write(self.style.ERROR(str(exc)))
                return

            cur.execute(f'SELECT COUNT(*) FROM {src.VIEW_NAME}')
            self.stdout.write(f'Строк во вьюхе: {cur.fetchone()[0]}')

            # Значения вида приёма — чтобы сверить с ADMISSION_KINDS в sync.py
            kind_column = next(c for c, f in src.COLUMNS.items() if f == 'admission_kind')
            actual = next(d[0] for d in description if d[0].upper() == kind_column.upper())
            cur.execute(f'SELECT DISTINCT "{actual}" FROM {src.VIEW_NAME}')
            self.stdout.write('Значения «Вид приема»:')
            for (value,) in cur:
                self.stdout.write(f'  {value!r}')
