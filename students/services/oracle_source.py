"""Чтение студентов из вьюхи Oracle."""
from django.conf import settings


VIEW_NAME = 'HR_UVZ.UOV_STUDENTS'

# 'Колонка вьюхи': 'поле модели Student'
COLUMNS = {
    'TAB_N': 'employee_number', # Табельный
    'L_NAME': 'last_name', # Фамилия
    'F_NAME': 'first_name', # Имя
    'M_NAME': 'middle_name', # Отчество
    'D_BIRTH': 'birth_date', # Дата рождения
    'D_IN': 'hiring_date', # Дата приёма
    'D_OUT': 'dismissal_date', # Дата увольнения (31.12.2099 = учится)
    'EMP_STAT': 'admission_kind', # Вид приема
    'PASSP_SER': 'passport_series', # Серия паспорта
    'PASSP_NUM': 'passport_number',      # Номер паспорта
    'PASSP_DATE': 'passport_issue_date',  # Дата выдачи паспорта
    'PASSP_GRANT': 'passport_issued_by',   # Место выдачи паспорта
    'SNN': 'snils', # СНИЛС
    'INN': 'inn', # ИНН
    'ADDR': 'address', # Адрес регистрации
}

_client_initialized = False


def _init_client():
    """Thick-режим, если задан ORACLE_CLIENT_LIB_DIR, иначе без драйверов
    init_oracle_client можно вызвать только 1 раз за процесс"""
    global _client_initialized
    lib_dir = settings.ORACLE_STUDENTS.get('CLIENT_LIB_DIR')
    if lib_dir and not _client_initialized:
        import oracledb
        oracledb.init_oracle_client(lib_dir=lib_dir)
        _client_initialized = True


def connect():
    import oracledb

    _init_client()
    conf = settings.ORACLE_STUDENTS
    try:
        return oracledb.connect(
            user=conf['USER'],
            password=conf['PASSWORD'],
            dsn=conf['DSN'],
            tcp_connect_timeout=10,
        )
    except oracledb.Error as exc:
        mode = 'thin' if oracledb.is_thin_mode() else 'thick'
        lib_dir = conf.get('CLIENT_LIB_DIR') or 'не задан'
        raise RuntimeError(f'{exc} [режим: {mode}, ORACLE_LIB_DIR: {lib_dir}]') from exc
    

def column_positions(description):
    """{номер_колонки_в_ответе: поле_модели}
    Ошибка, если колонки нет"""
    names = [d[0].upper() for d in description]
    positions = {}
    missing = []
    for column, field in COLUMNS.items():
        if column.upper() in names:
            positions[names.index(column.upper())] = field
        else:
            missing.append(column)
    if missing:
        raise RuntimeError(
            f'Во вьюхе нет колонок: {", ".join(missing)}.'
            f'Есть: {", ".join(d[0] for d in description)}'
        )
    return positions

def fetch_rows():
    """Отдает строки вьюхи как словари формата {поле модели: значение}"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT * FROM {VIEW_NAME}')
            positions = column_positions(cur.description)
            for row in cur:
                yield {field: row[i] for i, field in positions.items()}
