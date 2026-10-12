import pandas as pd
from io import StringIO
from datetime import datetime, date
from django.core.exceptions import ValidationError
from django.db import transaction
from collections import defaultdict
from core.models import (
    Employee, Production, Workshop, DismissalReason,
    EmployeeCategory, Position, HireSource, EmployeeGrades,
    EmployeeTransfers, HireCategory, EmployeeHistory, ReportTable,
    Salary,
)


class EmployeeFileProcessor:
    """
    Класс для обработки файлов с данными о сотрудниках.
    С оптимизацией для быстрой загрузки больших файлов.

    Логика: новые записи — добавление, существующие — обновление.

    Два режима обновления (переключается в _parse_row и process):
    - СТРОГОЕ обновление (активно): пустое поле в файле ЗАПИСЫВАЕТ None поверх
      существующего значения в БД. Нужно когда: работник заново устроился,
      дата увольнения должна стереться из БД.
    - МЯГКОЕ обновление (закомментировано): пустое поле в файле НЕ затирает
      существующее значение в БД. Нужно когда: в выгрузке забыли указать
      дату увольнения, но она уже есть в БД — трогать не нужно.
    """

    COLUMN_MAPPING = {
        'фио':                       'full_name',
        'табельный номер':           'employee_number',
        'дата рождения':             'birth_date',
        'дата приема на работу':     'hire_date',
        'дата увольнения (приказ)':  'dismissal_date',
        'производство':              'production',
        'цех':                       'workshop',
        'причина увольнения':        'dismissal_reason',
        'категория рабочего':        'employee_category',
        'должность':                 'position',
        'разряд':                    'grade',
        'откуда работник':           'hire_source',
        'адрес регистрации':         'reg_address',
        'пол':                       'gender',
        'дата увольнения':           'dismissal_date_fact',
        'вид приёма':                'hire_category',
        'номер приказа о приёме':    'hire_order_num',
    }

    # Поля, по которым проходимся для обновления
    UPDATE_FIELDS = [
        'full_name', 'birth_date', 'hire_date', 'dismissal_date',
        'production_id', 'workshop_id', 'dismissal_reason_id',
        'employee_category_id', 'position_id', 'grade_id', 'hire_source_id',
        'reg_address', 'gender', 'hire_category_id', 'dismissal_date_fact',
        'hire_order_num',
    ]

    def __init__(self, file):
        """
        Инициализация обработчика файлов

        Args:
            file: Загруженный файл
        """
        self.file = file
        self.success_count = 0
        self.update_count = 0
        self.error_count = 0
        self.errors = []

        # Кэши для справочников — загружаются один раз
        self._production_cache = {}
        self._workshop_cache = {}
        self._dismissal_reason_cache = {}
        self._category_cache = {}
        self._position_cache = {}
        self._hire_source_cache = {}
        self._grade_cache = {}
        self._hire_category_cache = {}

    # ========== Чтение файла ==========

    def read_file(self):
        """
        Чтение файлов Excel и CSV

        Returns:
            pandas.DataFrame: Таблица с данными
        """
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)

                if 'Табельный номер' in df.columns:
                    df['Табельный номер'] = df['Табельный номер'].astype(str).str.replace(r'\.0$', '', regex=True)
                    df['Табельный номер'] = df['Табельный номер'].astype(str).str.zfill(7)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df

    # ========== Парсинг дат ==========

    def parse_date(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'nat', 'none', ''):
            return None
        for fmt in (
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y.%m.%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Неверный формат даты: {value}")

    # ========== Справочники ==========

    def _load_caches(self):
        self._production_cache = {o.name: o for o in Production.objects.all()}
        self._workshop_cache = {o.number: o for o in Workshop.objects.all()}
        self._dismissal_reason_cache = {o.name: o for o in DismissalReason.objects.all()}
        self._category_cache = {o.name: o for o in EmployeeCategory.objects.all()}
        self._position_cache = {o.name: o for o in Position.objects.all()}
        self._hire_source_cache = {o.name: o for o in HireSource.objects.all()}
        self._grade_cache = {o.name: o for o in EmployeeGrades.objects.all()}
        self._hire_category_cache = {o.name: o for o in HireCategory.objects.all()}

    def _get_or_create(self, cache, model, value, field='name'):
        """
        Получить запись из кэша или создать новую запись в БД

        Args:
            cache: Словарь кэша для конкретного справочника
            model: класс модели Django
            value: Значение для поиска
            field: Название поля для поиска. По умолчанию 'name'

        Returns:
            Объект модели или None
        """
        if not value:
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'none'):
            return None
        if value not in cache:
            obj, _ = model.objects.get_or_create(**{field: value})
            cache[value] = obj
        return cache[value]

    def _get_or_create_workshop(self, number_val, production_obj):
        """
        Получить или создать цех, при создании сразу привязывая производство.

        Если цех уже существует без производства — обновляем production.
        Это гарантирует что справочник Workshop.production заполнен корректно
        после загрузки файла.

        Args:
            number_val:     номер цеха (строка)
            production_obj: объект Production или None

        Returns:
            Workshop или None
        """
        if not number_val:
            return None
        number_val = str(number_val).strip()
        if not number_val or number_val.lower() in ('nan', 'none'):
            return None

        if number_val not in self._workshop_cache:
            ws, created = Workshop.objects.get_or_create(number=number_val)
            # Если цех только что создан или у него не заполнено производство —
            # привязываем production из текущей строки файла
            if production_obj and ws.production_id != production_obj.pk:
                ws.production = production_obj
                ws.save(update_fields=['production'])
            self._workshop_cache[number_val] = ws

        return self._workshop_cache[number_val]

        # if number_val not in self._workshop_cache:
        #     ws, created = Workshop.objects.get_or_create(number=number_val)
        #     self._workshop_cache[number_val] = ws
        
        # ws = self._workshop_cache[number_val]

        # if production_obj and ws.production_id != production_obj.pk:
        #     ws.production = production_obj
        #     ws.save(update_fields=['production'])

        # return ws

    # ========== Парсинг одной строки ==========

    def _parse_row(self, row, row_num):
        """
        Разобрать строку файла в словарь данных.
        Возвращает dict или None если строку нужно пропустить.
        """
        # Приводим ключи к нижнему регистру для поиска
        keys = {str(k).strip().lower(): k for k in row.keys()}

        def get(col):
            k = keys.get(col)
            if k is None:
                return None
            v = row[k]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            v = str(v).strip()
            return v if v and v.lower() not in ('nan', 'none', 'nat') else None

        # Обязательные поля
        employee_number = get('табельный номер')
        full_name = get('фио')
        hire_date_raw = get('дата приема на работу')
        gender = get('пол')
        hire_category = get('вид приёма')

        # Необзательные поля
        reg_address = get('адрес регистрации')
        hire_order_num = get('номер приказа о приёме')

        if not employee_number:
            self.errors.append(f"Строка {row_num}: нет табельного номера — пропущена")
            return None
        if not full_name:
            self.errors.append(f"Строка {row_num}: нет ФИО — пропущена")
            return None
        if not hire_date_raw:
            self.errors.append(f"Строка {row_num}: нет даты приёма — пропущена")
            return None
        if not gender:
            self.errors.append(f"Строка {row_num}: пол не указан — пропущена")
            return None
        if not hire_category:
            self.errors.append(f"Строка {row_num}: нет вида приема — пропущена")
            return None

        try:
            hire_date = self.parse_date(hire_date_raw)
        except ValueError as e:
            self.errors.append(f"Строка {row_num}: {e}")
            return None

        data = {
            'employee_number': employee_number,
            'full_name': full_name,
            'hire_date': hire_date,
            'gender': gender,
            'reg_address': reg_address,
            'hire_order_num': hire_order_num,
        }

        # НЕОБЯЗАТЕЛЬНЫЕ ДАТЫ
        #
        # СТРОГОЕ обновление (активно):
        # Пустая ячейка в файле записывает None в БД.
        # Нужно: работник заново устроился — дата увольнения стирается.
        for col, field in [('дата рождения', 'birth_date'), ('дата увольнения(приказ)', 'dismissal_date'), ('дата увольнения', 'dismissal_date_fact')]:
            if col in keys:  # колонка присутствует в файле
                raw = get(col)
                if raw:
                    try:
                        data[field] = self.parse_date(raw)
                    except ValueError as e:
                        self.errors.append(f"Строка {row_num}: {e}")
                        data[field] = None  # ошибка парсинга = нет данных
                else:
                    data[field] = None  # пустая ячейка → None

        # МЯГКОЕ обновление (закомментировано):
        # Пустая ячейка в файле НЕ затирает существующее значение в БД.
        # Нужно: в выгрузке забыли указать дату увольнения — не трогаем БД.
        # for col, field in [('дата рождения', 'birth_date'), ('дата увольнения', 'dismissal_date')]:
        #     raw = get(col)
        #     if raw:
        #         try:
        #             data[field] = self.parse_date(raw)
        #         except ValueError as e:
        #             self.errors.append(f"Строка {row_num}: {e}")

        # НЕОБЯЗАТЕЛЬНЫЕ СПРАВОЧНИКИ
        #
        # СТРОГОЕ обновление (активно):
        # Пустая ячейка в файле записывает None (связь с справочником обнуляется).

        # if 'производство' in keys:
        #     production_val = get('производство')
        #     data['production'] = self._get_or_create(
        #         self._production_cache, Production, production_val
        #     ) if production_val else None
        # if 'производство' in keys:
        #     production_val = get('производство')
        #     obj = self._get_or_create(
        #         self._production_cache, 
        #         Production, 
        #         production_val
        #     ) if production_val else None
        #     data['production_id'] = obj.pk if obj else None  
        if 'производство' in keys:
            production_val = get('производство')
            production_obj = self._get_or_create(self._production_cache, Production, production_val) if production_val else None
            data['production_id'] = self._production_cache[production_val].pk if production_val and production_val in self._production_cache else None    

        # if 'цех' in keys:
        #     workshop_val = get('цех')
        #     # Передаём production_obj чтобы при создании цеха сразу привязать производство
        #     data['workshop'] = self._get_or_create_workshop(
        #         workshop_val,
        #         data.get('production'),
        #     ) if workshop_val else None
        if 'цех' in keys:
            workshop_val = get('цех')
            data['workshop_id'] = self._get_or_create_workshop(
                workshop_val,
                production_obj,
            ).pk if workshop_val else None

        # if 'причина увольнения' in keys:
        #     dismissal_val = get('причина увольнения')
        #     data['dismissal_reason'] = self._get_or_create(
        #         self._dismissal_reason_cache, DismissalReason, dismissal_val
        #     ) if dismissal_val else None
        if 'причина увольнения' in keys:
            dismissal_val = get('причина увольнения')
            obj = self._get_or_create(
                self._dismissal_reason_cache, 
                DismissalReason, 
                dismissal_val
            ) if dismissal_val else None
            data['dismissal_reason_id'] = obj.pk if obj else None    

        # if 'категория рабочего' in keys:
        #     category_val = get('категория рабочего')
        #     data['employee_category'] = self._get_or_create(
        #         self._category_cache, EmployeeCategory, category_val
        #     ) if category_val else None
        if 'категория рабочего' in keys:
            category_val = get('категория рабочего')
            obj = self._get_or_create(
                self._category_cache, 
                EmployeeCategory, 
                category_val
            ) if category_val else None
            data['employee_category_id'] = obj.pk if obj else None 

        # if 'должность' in keys:
        #     position_val = get('должность')
        #     data['position'] = self._get_or_create(
        #         self._position_cache, Position, position_val
        #     ) if position_val else None
        if 'должность' in keys:
            position_val = get('должность')
            obj = self._get_or_create(
                self._position_cache, 
                Position, 
                position_val
            ) if position_val else None
            data['position_id'] = obj.pk if obj else None    

        # if 'откуда работник' in keys:
        #     hire_source_val = get('откуда работник')
        #     data['hire_source'] = self._get_or_create(
        #         self._hire_source_cache, HireSource, hire_source_val
        #     ) if hire_source_val else None
        if 'откуда работник' in keys:
            hire_source_val = get('откуда работник')
            obj = self._get_or_create(
                self._hire_source_cache, 
                HireSource, 
                hire_source_val
            ) if hire_source_val else None
            data['hire_source_id'] = obj.pk if obj else None    

        # if 'разряд' in keys:
        #     grade_val = get('разряд')
        #     data['grade'] = self._get_or_create(
        #         self._grade_cache, EmployeeGrades, grade_val
        #     ) if grade_val else None
        if 'разряд' in keys:
            grade_val = get('разряд')
            obj = self._get_or_create(
                self._grade_cache, 
                EmployeeGrades, 
                grade_val
            ) if grade_val else None
            data['grade_id'] = obj.pk if obj else None  

        if 'вид приёма' in keys:
            hire_category_val = get('вид приёма')
            obj = self._get_or_create(
                self._hire_category_cache, 
                HireCategory, 
                hire_category_val
            ) if hire_category_val else None
            data['hire_category_id'] = obj.pk if obj else None  

        # МЯГКОЕ обновление:
        # Обновляем только если значение пришло из файла (не пустое).
        # production_val = get('производство')
        # if production_val:
        #     data['production'] = self._get_or_create(self._production_cache, Production, production_val)
        #
        # workshop_val = get('цех')
        # if workshop_val:
        #     data['workshop'] = self._get_or_create(self._workshop_cache, Workshop, workshop_val, field='number')
        #
        # dismissal_val = get('причина увольнения')
        # if dismissal_val:
        #     data['dismissal_reason'] = self._get_or_create(self._dismissal_reason_cache, DismissalReason, dismissal_val)
        #
        # category_val = get('категория рабочего')
        # if category_val:
        #     data['employee_category'] = self._get_or_create(self._category_cache, EmployeeCategory, category_val)
        #
        # position_val = get('должность')
        # if position_val:
        #     data['position'] = self._get_or_create(self._position_cache, Position, position_val)

        return data

    # ========== Основной метод ==========

    @transaction.atomic
    def process(self):
        """
        Основной метод обработки файла с оптимизацией

        Returns:
            dict: Статистика обработки
        """
        start = datetime.now()

        df = self.read_file()
        if df.empty:
            raise ValidationError("Файл пустой")

        # Нормализуем заголовки
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Убираем строки-заголовки попавшие в данные
        first_col = df.iloc[:, 0].astype(str).str.strip().str.lower()
        df = df[~first_col.isin(['фио', '---', 'nan'])].reset_index(drop=True)

        # Проверка обязательных колонок
        required = {'фио', 'табельный номер', 'дата приема на работу', 'пол', 'вид приёма'}
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        # Загружаем справочники в кэш
        self._load_caches()

        # Загружаем существующих сотрудников одним запросом
        # existing_employees = {
        #     e.employee_number: e
        #     for e in Employee.objects.all()
        # }

        employee_numbers = set()

        for idx, row in df.iterrows():
            num = str(row.get('табельный номер', '') or '').strip()
            if num:
                employee_numbers.add(num)

        existing_employees = {
            e.employee_number: e
            for e in Employee.objects.filter(employee_number__in=employee_numbers)
        }

        # Разбираем строки
        to_create = []  # новые — Employee объекты
        to_update = []  # существующие — (employee_obj, data_dict)

        for idx, row in df.iterrows():
            data = self._parse_row(row.to_dict(), idx + 2)
            if data is None:
                self.error_count += 1
                continue

            emp_number = data['employee_number']

            if emp_number in existing_employees:
                to_update.append((existing_employees[emp_number], data))
            else:
                # Новый сотрудник
                to_create.append(Employee(**data))

        # Создаём новых сотрудников одним запросом
        if to_create:
            Employee.objects.bulk_create(to_create, batch_size=500)
            self.success_count = len(to_create)

        # Обновление существующих данных
        if to_update:
            updated_objects = []
            for emp, data in to_update:
                changed = False

                # СТРОГОЕ обновление (активно):
                # Если значение в файле и БД расходятся — приоритет у файла.
                # None из файла тоже записывается (стирает старое значение).
                # Нужно: работник заново устроился — дата увольнения стирается из БД.
                for field in self.UPDATE_FIELDS:
                    if field in data:
                        new_val = data[field]  # может быть None
                        if getattr(emp, field) != new_val:
                            setattr(emp, field, new_val)
                            changed = True

                # МЯГКОЕ обновление (закомментировано):
                # Обновляем только поля, которые явно пришли из файла (не None).
                # Нужно: в выгрузке нет даты увольнения — существующая в БД сохраняется.
                # for field in self.UPDATE_FIELDS:
                #     if field in data and data[field] is not None:
                #         setattr(emp, field, data[field])
                #         changed = True

                if changed:
                    updated_objects.append(emp)

            if updated_objects:
                Employee.objects.bulk_update(
                    updated_objects,
                    self.UPDATE_FIELDS,
                    batch_size=500
                )
                self.update_count = len(updated_objects)

        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        }

class TransfersFileProcessor:
    def __init__(self, file):
        self.file = file
        self.missing_employees = []

        self.success_count = 0
        self.update_count = 0
        self.error_count = 0
        self.errors = []
    
    def _load_maps(self):
        self.employee_map = dict(
            Employee.objects.values_list('employee_number', 'id')
        )
        self.workshop_map = dict(
            Workshop.objects.values_list('number', 'id')
        )
        self.position_map = dict(
            Position.objects.values_list('name', 'id')
        )
        self.grade_map = dict(
            EmployeeGrades.objects.values_list('name', 'id')
        )
        self.category_map = dict(
            EmployeeCategory.objects.values_list('name', 'id')
        )

    def _get(self, mapping, key, field_name):
        value = mapping.get(str(key).strip())
        # if value is None:
        #     self.missing_employees.append(key)
        #     raise ValueError(f"Значение '{key}'('{value}') не найдено в {field_name}")

        return value

    def _get_or_create(self, mapping, model, value, field_name="name"):
        key = str(value).strip()

        if not key:
            return None
        
        obj_id = mapping.get(key)
        if obj_id:
            return obj_id
        
        obj = model.objects.filter(**{field_name: key})
        if not obj:
            obj = model.objects.create(**{field_name: key})

        mapping[key] = obj.id
        return obj.id

    def _read_file(self):
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)

                if 'Табельный' in df.columns:
                    df['Табельный'] = df['Табельный'].astype(str).str.replace(r'\.0$', '', regex=True)
                    df['Табельный'] = df['Табельный'].astype(str).str.zfill(7)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df

    def _parse_date(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'nat', 'none', ''):
            return None
        for fmt in (
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y.%m.%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Неверный формат даты: {value}")

    def save_missing(self, path='missing.txt'):
        unique = sorted(set(self.missing_employees))
        path = f'missing{date.today()}.txt'

        with open(path, 'w', encoding='cp1251') as f:
            for i, pn in enumerate(unique, start=1):
                f.write(f"{i}. {pn}\n")

    @transaction.atomic
    def process(self):
        start = datetime.now()

        df = self._read_file()
        df = df.fillna('')

        required = {
            'Табельный', 
            'Номер приказа', 
            'Дата назначения', 
            'Цех до перевода',
            'Должность до перевода',
            'Цех после перевода',
            'Должность после перевода',
            'Категория до перевода',
            'Категория после перевода',
        }
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        self._load_maps()

        transfers = []

        for _, row in df.iterrows():
            try:
                employee_id = self._get(self.employee_map, row['Табельный'], 'employee_number')
                if employee_id is None:
                    self.missing_employees.append(row['Табельный'])
                    continue

                transfer = EmployeeTransfers(
                    employee_id         =   employee_id,
                    order_number        =   str(row['Номер приказа']).strip(),
                    transfer_date       =   self._parse_date(row['Дата назначения']),

                    from_workshop_id    =   self._get_or_create(self.workshop_map, Workshop, row['Цех до перевода'], 'number'),
                    from_position_id    =   self._get_or_create(self.position_map, Position, row['Должность до перевода']),
                    from_grade_id       =   self._get_or_create(self.grade_map, EmployeeGrades, row['Разряд до перевода']),
                    from_category_id       =   self._get_or_create(self.category_map, EmployeeCategory, row['Категория до перевода']),

                    to_workshop_id      =   self._get_or_create(self.workshop_map, Workshop, row['Цех после перевода'], 'number'),
                    to_position_id      =   self._get_or_create(self.position_map, Position, row['Должность после перевода']),
                    to_grade_id         =   self._get_or_create(self.grade_map, EmployeeGrades, row['Разряд после перевода']),
                    to_category_id         =   self._get_or_create(self.category_map, EmployeeCategory, row['Категория после перевода']),
                )

                transfers.append(transfer)
                self.success_count += 1

            except Exception as e:
                print(f'Ошибка в строке {e}')
                self.error_count += 1

        EmployeeTransfers.objects.bulk_create(
            transfers,
            ignore_conflicts=True,
            # update_conflicts=True,
            # update_fields=[
            #     'from_workshop',
            #     'from_position',
            #     'from_grade',
            #     'to_workshop',
            #     'to_position',
            #     'to_grade',
            # ],
            # unique_fields=['employee', 'order_number', 'transfer_date'],
            batch_size=1000,
        )

        self.save_missing()
        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        }

class HistoryFileProcessor:
    def __init__(self, file):
        self.file = file
        self.missing_employees = []

        self.success_count = 0
        self.update_count = 0
        self.error_count = 0
        self.errors = []  

    def _load_maps(self):
        self.employee_map = dict(
            Employee.objects.values_list('employee_number', 'id')
        )
        # self.employee_map = list(
        #     EmployeeHistory.objects.filter(
        #         hiring_date__year=2026,
        #         hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
        #     ).values_list('employee__employee_number', flat=True)
        # )
        self.dismissal_reason_map = dict(
            DismissalReason.objects.values_list('name', 'id')
        )
        self.hire_souce_map = dict(
            HireSource.objects.values_list('name', 'id')
        )
        self.hire_cat_map = dict(
            HireCategory.objects.values_list('name', 'id')
        )

    def _get(self, mapping, key, field_name):
        value = mapping.get(str(key).strip())
        # if value is None:
        #     self.missing_employees.append(key)
        #     raise ValueError(f"Значение '{key}'('{value}') не найдено в {field_name}")

        return value     

    def _read_file(self):
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)

                if 'Таб' in df.columns:
                    df['Таб'] = df['Таб'].astype(str).str.replace(r'\.0$', '', regex=True)
                    df['Таб'] = df['Таб'].astype(str).str.zfill(7)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df

    def _parse_date(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'nat', 'none', ''):
            return None
        for fmt in (
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y.%m.%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Неверный формат даты: {value}")

    def save_missing(self, path='missing.txt'):
        unique = sorted(set(self.missing_employees))
        path = f'missing{date.today()}.txt'

        with open(path, 'w', encoding='cp1251') as f:
            for i, pn in enumerate(unique, start=1):
                f.write(f"{i}. {pn}\n")

    @transaction.atomic
    def process(self):
        start = datetime.now()

        df = self._read_file()
        df = df.fillna('')

        required = {
            'Таб', 
            'Дата приема', 
            'Дата приказа увольнения', 
            'Откуда работник',
            'Причина увольнения',
            'Статус работника',
        }
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        self._load_maps()
        # file_nums = set(df['Таб'].tolist())
        # missing_nums = file_nums - set(self.employee_map)
        # for s in missing_nums:
        #     self.missing_employees.append(s)
        #     self.error_count += 1
        #     self.errors.append(f"Сотрудник {s} не найден в базе.")

        EmployeeHistory.objects.all().delete()

        histories = []
        seen_keys = set()

        for _, row in df.iterrows():
            try:
                employee_id = self._get(self.employee_map, row['Таб'], 'employee_number')
                hs_id = self._get(self.hire_souce_map, row['Откуда работник'], 'name')
                dr_id = self._get(self.dismissal_reason_map, row['Причина увольнения'], 'name')
                hire_cat_id = self._get(self.hire_cat_map, row['Статус работника'], 'name')
                if employee_id is None:
                    self.missing_employees.append(row['Таб'])
                    self.error_count += 1
                    self.errors.append(f"Сотрудник {row['Таб']} не найден в базе.")
                    continue
                key = (
                        row['Таб'], 
                        row['Дата приема'], 
                        row['Дата приказа увольнения'], 
                        row['Откуда работник'], 
                        row['Причина увольнения'],
                        row['Статус работника'],
                    )
                if key in seen_keys:
                    self.error_count += 1
                    self.errors.append(f"Дубликат в файле: {key}")
                    continue
                seen_keys.add(key)

                history = EmployeeHistory(
                    employee_id         =   employee_id,
                    hiring_date         =   self._parse_date(row['Дата приема']),
                    dismissal_date      =   self._parse_date(row['Дата приказа увольнения']),
                    hire_source_id      =   hs_id,
                    dismissal_reason_id =   dr_id,
                    hire_category_id    =   hire_cat_id,
                )

                histories.append(history)
                self.success_count += 1

            except Exception as e:
                print(f'Ошибка в строке {e}')
                self.error_count += 1

        EmployeeHistory.objects.bulk_create(
            histories,
            # ignore_conflicts=True,
            update_conflicts=True,
            update_fields=[
                'hiring_date',
                'dismissal_date',
                'hire_source_id',
                'dismissal_reason_id',
                'hire_category_id',
            ],
            unique_fields=['employee', 'hiring_date', 'dismissal_date', 'hire_source_id', 'dismissal_reason_id', 'hire_category_id'],
            batch_size=3000 ,
        )

        self.save_missing()
        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        } 

class ReportTableFileProcessor: # Временно
    def __init__(self, file):
        self.file = file

        self.success_count = 0
        self.update_count = 0
        self.error_count = 0
        self.errors = []
        self.allowed_prods = ['МСП', 'ВСП', 'МП', 'ИП', 'ПНСО']

    def _get(value):
        if value is None:
            return None
        
        return value

    def _parse_date(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'nat', 'none', ''):
            return None
        for fmt in (
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y.%m.%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Неверный формат даты: {value}")

    def _read_file(self):
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df

    @transaction.atomic
    def process(self):
        start = datetime.now()

        df = self._read_file()
        df = df.fillna('')

        required = {
            'dep',
            'prod',
            'f_3',
            'f_4',
            'f_5',
            'f_6',
            'f_7',
            'f_8',
            'f_9',
            'f_10',
            'f_11',
            'f_12',
            'f_13',
            'f_14',
            'date',
        }
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")
        
        data = []
        # ReportTable.objects.all().delete()

        for _, row in df.iterrows():
            try:
                if row['prod'] not in self.allowed_prods:
                    continue

                i = 0.0
                if row['f_5'] in ('', '0') and row['f_8'] not in ('', '0'):
                    i = 1000
                else:
                    i = float(row['f_9']) * 100
                    
                r = ReportTable(
                    dep         = row['dep'],
                    prod        = row['prod'],
                    f_3         = row['f_3'],
                    f_4         = row['f_4'],
                    f_5         = round(float(row['f_5']), 1) if row['f_5'] != '' else 0,
                    f_6         = row['f_6'],
                    f_7         = row['f_7'],
                    f_8         = round(float(row['f_8']), 1) if row['f_8'] != '' else 0,
                    f_9         = i,
                    f_10        = row['f_10'],
                    f_11        = row['f_11'],
                    f_12        = row['f_12'],
                    f_13        = round(float(row['f_13']), 1) if row['f_13'] != '' else 0,
                    f_14        = round(float(row['f_14']), 1) if row['f_14'] != '' else 0,
                    table_date  = self._parse_date(row['date'])
                )

                data.append(r)
                self.success_count += 1

            except Exception as e:
                print(f'Ошибка в строке {e}')
                self.error_count += 1

        ReportTable.objects.bulk_create(
            data,
            ignore_conflicts=True,
            # update_conflicts=True,
            # update_fields=[
            #     'from_workshop',
            #     'from_position',
            #     'from_grade',
            #     'to_workshop',
            #     'to_position',
            #     'to_grade',
            # ],
            # unique_fields=['employee', 'order_number', 'transfer_date'],
            batch_size=1000,
        )

        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        }

class SalaryFileProcessor:
    def __init__(self, file):
        self.file = file
        self.missing_employees = []

        self.success_count = 0
        self.update_count = 0
        self.error_count = 0
        self.errors = []
    
    def _load_maps(self):
        self.employee_map = dict(
            Employee.objects.values_list('employee_number', 'id')
        )

    def _get(self, mapping, key, field_name):
        value = mapping.get(str(key).strip())
        # if value is None:
        #     self.missing_employees.append(key)
        #     raise ValueError(f"Значение '{key}'('{value}') не найдено в {field_name}")

        return value


    def _read_file(self):
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)

                if 'Таб' in df.columns:
                    df['Таб'] = df['Таб'].astype(str).str.replace(r'\.0$', '', regex=True)
                    df['Таб'] = df['Таб'].astype(str).str.zfill(7)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df

    def _parse_date(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        if not value or value.lower() in ('nan', 'nat', 'none', ''):
            return None
        for fmt in (
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y.%m.%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Неверный формат даты: {value}")

    def save_missing(self, path='missing.txt'):
        unique = sorted(set(self.missing_employees))
        path = f'missing{date.today()}.txt'

        with open(path, 'w', encoding='cp1251') as f:
            for i, pn in enumerate(unique, start=1):
                f.write(f"{i}. {pn}\n")

    @transaction.atomic
    def process(self):
        start = datetime.now()

        df = self._read_file()
        df = df.fillna('')

        required = {
            'Дата', 
            'Таб', 
            'Часы', 
            'Сумма',
            'Сумма отпуск',
        }
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        self._load_maps()

        salaries = []

        for _, row in df.iterrows():
            try:
                employee_id = self._get(self.employee_map, row['Таб'], 'employee_number')
                if employee_id is None:
                    self.missing_employees.append(row['Таб'])
                    continue

                salary = Salary(
                    employee_id = employee_id,
                    hours = row['Часы'] if row['Часы'] != '' else 0,
                    main_sum = row['Сумма'] if row['Сумма'] != '' else 0,
                    vacation_sum = row['Сумма отпуск'] if row['Сумма отпуск'] != '' else 0,
                    salary_date = self._parse_date(row['Дата']),
                )

                salaries.append(salary)
                self.success_count += 1

            except Exception as e:
                print(f'Ошибка в строке {e}')
                self.error_count += 1

        Salary.objects.bulk_create(
            salaries,
            ignore_conflicts=True,
            # update_conflicts=True,
            # update_fields=[
            #     'hours',
            #     'main_sum',
            #     'vacation_sum',
            # ],
            # unique_fields=['employee', 'salary_date'],
            batch_size=1000,
        )

        self.save_missing()
        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        }

class DebugFileProcessor:
    def __init__(self, file):
            self.file = file
            self.missing_employees = []

            self.success_count = 0
            self.update_count = 0
            self.error_count = 0
            self.errors = []  

    def _load_maps(self):
        self.employee_map = list(
            EmployeeHistory.objects.filter(
                hiring_date__year=2026,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).values_list('employee__employee_number', flat=True)
        )

    def _read_file(self):
        file_extension = self.file.name.split('.')[-1].lower()
        try:
            # Проверка для CSV
            if file_extension == 'csv':
                df = None
                last_error = None
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        self.file.seek(0)
                        raw = self.file.read()
                        decoded = raw.decode(encoding)
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=';',
                            engine='python'
                        )
                        break
                    except UnicodeDecodeError:
                        last_error = encoding
                        continue
                    except Exception as e:
                        last_error = f"Ошибка c {encoding}: {type(e).__name__}: {e}"
                        continue
                if df is None:
                    raise ValidationError(f"Не удалось прочитать файл. Ошибка: {last_error}")

            # Проверка для Excel
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file, dtype=str)

                if 'Таб' in df.columns:
                    df['Таб'] = df['Таб'].astype(str).str.replace(r'\.0$', '', regex=True)
                    df['Таб'] = df['Таб'].astype(str).str.zfill(7)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {e}")

        return df
    

    def save_missing(self, path='missing.txt'):
        unique = sorted(set(self.missing_employees))
        path = f'\\\\ftpuvz-1\\940-KSS\\Практика\\missing{date.today()}.txt'

        with open(path, 'w', encoding='cp1251') as f:
            for i, pn in enumerate(unique, start=1):
                f.write(f"{i}. {pn}\n")

    @transaction.atomic
    def process(self):
        start = datetime.now()

        df = self._read_file()
        df = df.fillna('')

        required = {
            'Таб', 
            'Дата приема', 
            'Дата приказа увольнения', 
            'Откуда работник',
            'Причина увольнения',
            'Статус работника',
        }
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        self._load_maps()
        file_nums = set(df['Таб'].tolist())
        missing_nums = file_nums - set(self.employee_map)
        for s in missing_nums:
            self.missing_employees.append(s)
            self.error_count += 1
            self.errors.append(f"Сотрудник {s} не найден в базе.")

        self.save_missing()
        duration = (datetime.now() - start).total_seconds()

        return {
            'success': self.success_count,
            'updated': self.update_count,
            'errors': self.errors,
            'error_count': self.error_count,
            'total': len(df),
            'duration': duration,
        }