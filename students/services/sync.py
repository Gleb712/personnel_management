"""Синхронизация студентов из Oracle.

Правила:
- ключ — табельный номер; по каждому табельному берём только последний период;
- дата увольнения 31.12.2099 означает «ещё учится» и хранится как пустая;
- если отчислен раньше MIN_DISMISSAL_YEAR, строку пропускаем;
- поля из ALWAYS_UPDATE перезаписываются всегда, поля из FILL_IF_EMPTY
  заполняются, только если в сервисе они пустые (ручные правки главнее);
- студентов, пропавших из вьюхи, не трогаем.
"""
import logging
from datetime import date, datetime

from django.db import connection, transaction
from django.utils import timezone

from ..models import Student, StudentHistory, StudentSyncLog

logger = logging.getLogger(__name__)

STUDYING_YEAR = 2099        # год увольнения «ещё учится»
MIN_DISMISSAL_YEAR = 2026   # отчисленных раньше этого года не загружаем
LOCK_KEY = 7120001          # ключ блокировки PostgreSQL от двойного запуска

ADMISSION_KEYWORDS = (
    ('целев', Student.AdmissionKind.TARGET),
    ('упц', Student.AdmissionKind.UPC),
)
ALWAYS_UPDATE = (
    'last_name', 'first_name', 'middle_name',
    'hiring_date', 'dismissal_date',
)
FILL_IF_EMPTY = (
    'admission_kind', 'birth_date',
    'passport_series', 'passport_number', 'passport_issue_date', 'passport_issued_by',
    'snils', 'inn', 'address',
)
DATE_FIELDS = ('hiring_date', 'dismissal_date', 'birth_date', 'passport_issue_date')
DATE_FORMATS = ('%d.%m.%Y', '%Y.%m.%d',
                '%d.%m.%Y %H:%M:%S', '%Y.%m.%d %H:%M:%S',
                '%d-%m-%Y', '%Y-%m-%d',
                '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S',)


class RowError(Exception):
    """Ошибка в одной строке: строку пропускаем, остальные грузим."""


class SyncAlreadyRunning(Exception):
    pass


# ----- Нормализация -----

def _to_str(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _to_date(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RowError(f'не удалось разобрать дату {value!r}')


def _format_snils(value):
    digits = ''.join(ch for ch in value if ch.isdigit())
    if len(digits) != 11:
        return value
    return f'{digits[:3]}-{digits[3:6]}-{digits[6:9]} {digits[9:]}'


def _digits_padded(value, length):
    """Числовые поля из Oracle"""
    if value.isdigit() and len(value) < length:
        return value.zfill(length)
    return value


def _format_passport_series(value):
    digits = ''.join(ch for ch in value if ch.isdigit())
    if len(digits) != 4:
        return value
    return f'{digits[:2]} {digits[2:]}'


def _admission_kind(value):
    text = value.lower()
    for keyword, kind in ADMISSION_KEYWORDS:
        if keyword in text:
            return kind
    return None


def normalize(raw):
    row = {}
    for field, value in raw.items():
        row[field] = _to_date(value) if field in DATE_FIELDS else _to_str(value)

    if not row.get('employee_number'):
        raise RowError('нет табельного номера')
    if not row.get('last_name'):
        raise RowError('нет фамилии')
    if not row.get('hiring_date'):
        raise RowError('нет даты приёма')

    if row['dismissal_date'] and row['dismissal_date'].year >= STUDYING_YEAR:
        row['dismissal_date'] = None

    kind = _admission_kind(row.get('admission_kind', ''))
    if kind is None:
        raise RowError(f'неизвестный вид приёма {row.get("admission_kind")!r}')
    row['admission_kind'] = kind

    row['snils'] = _format_snils(row.get('snils', ''))
    row['passport_series'] = _format_passport_series(row.get('passport_series', ''))
    row['passport_number'] = _digits_padded(row.get('passport_number', ''), 6)
    row['inn'] = _digits_padded(row.get('inn', '').replace(' ', ''), 12)
    return row


# ----- Логика -----

def _period_key(row):
    # Позже принят — новее; при равной дате приёма новее открытый период
    return (row['hiring_date'], row['dismissal_date'] or date.max)


def _latest_by_employee(rows):
    latest = {}
    for row in rows:
        current = latest.get(row['employee_number'])
        if current is None or _period_key(row) > _period_key(current):
            latest[row['employee_number']] = row
    return latest


def _apply(student, row):
    """Переносит данные строки в студента, возвращает список изменённых полей."""
    changed = []
    for field in ALWAYS_UPDATE:
        if getattr(student, field) != row[field]:
            setattr(student, field, row[field])
            changed.append(field)
    for field in FILL_IF_EMPTY:
        if row[field] and not getattr(student, field):
            setattr(student, field, row[field])
            changed.append(field)
    return changed


def _acquire_lock():
    # Блокировка снимается сама в конце транзакции
    if connection.vendor != 'postgresql':
        return True
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_xact_lock(%s)', [LOCK_KEY])
        return cur.fetchone()[0]


def _sync(raw_rows, log):
    rows = []
    for i, raw in enumerate(raw_rows, start=1):
        try:
            rows.append(normalize(raw))
        except RowError as exc:
            who = _to_str(raw.get('employee_number')) or f'строка {i}'
            log.errors.append(f'{who}: {exc}')

    latest = _latest_by_employee(rows)
    existing = Student.objects.in_bulk(list(latest), field_name='employee_number')

    for number, row in latest.items():
        dismissal = row['dismissal_date']
        if dismissal and dismissal.year < MIN_DISMISSAL_YEAR:
            log.skipped += 1
            continue

        student = existing.get(number)
        if student is None:
            student = Student.objects.create(**row)
            log.created += 1
        else:
            changed = _apply(student, row)
            if changed:
                student.save(update_fields=changed + ['updated_at'])
                log.updated += 1
            else:
                log.unchanged += 1

        StudentHistory.objects.update_or_create(
            student=student,
            hiring_date=row['hiring_date'],
            defaults={'dismissal_date': dismissal},
        )


def run_sync(fetch_rows=None, user=None):
    """Запускает синхронизацию и возвращает запись журнала.

    fetch_rows — функция-источник строк (по умолчанию вьюха Oracle).
    user — кто запустил; None — расписание.
    """
    if fetch_rows is None:
        from .oracle_source import fetch_rows

    log = StudentSyncLog.objects.create(triggered_by=user)
    try:
        with transaction.atomic():
            if not _acquire_lock():
                raise SyncAlreadyRunning('синхронизация уже выполняется, попробуйте позже')
            raw_rows = list(fetch_rows())
            log.total_rows = len(raw_rows)
            _sync(raw_rows, log)
    except Exception as exc:
        logger.exception('Синхронизация студентов не выполнена')
        log.status = StudentSyncLog.Status.FAILED
        log.message = str(exc)
        # Транзакция откатилась — счетчики не соответствуют базе
        log.created = log.updated = log.unchanged = log.skipped = 0
    else:
        log.status = StudentSyncLog.Status.SUCCESS
    log.finished_at = timezone.now()
    log.save()
    return log
