import pandas as pd
from datetime import datetime, date
from django.core.exceptions import ValidationError
from django.db import transaction
from core.models import (
    Employee, Production, Workshop, DismissalReason,
    EmployeeCategory, Position
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
        'фио': 'full_name',
        'табельный номер': 'employee_number',
        'дата рождения': 'birth_date',
        'дата приема на работу': 'hire_date',
        'дата увольнения': 'dismissal_date',
        'производство': 'production',
        'цех': 'workshop',
        'причина увольнения': 'dismissal_reason',
        'категория рабочего': 'employee_category',
        'должность': 'position',
    }

    # Поля, по которым проходимся для обновления
    UPDATE_FIELDS = [
        'full_name', 'birth_date', 'hire_date', 'dismissal_date',
        'production', 'workshop', 'dismissal_reason',
        'employee_category', 'position',
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
                        from io import StringIO
                        df = pd.read_csv(
                            StringIO(decoded),
                            dtype=str,
                            sep=None,
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

        if not employee_number:
            self.errors.append(f"Строка {row_num}: нет табельного номера — пропущена")
            return None
        if not full_name:
            self.errors.append(f"Строка {row_num}: нет ФИО — пропущена")
            return None
        if not hire_date_raw:
            self.errors.append(f"Строка {row_num}: нет даты приёма — пропущена")
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
        }

        # НЕОБЯЗАТЕЛЬНЫЕ ДАТЫ
        #
        # СТРОГОЕ обновление (активно):
        # Пустая ячейка в файле записывает None в БД.
        # Нужно: работник заново устроился — дата увольнения стирается.
        for col, field in [('дата рождения', 'birth_date'), ('дата увольнения', 'dismissal_date')]:
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
        if 'производство' in keys:
            production_val = get('производство')
            data['production'] = self._get_or_create(
                self._production_cache, Production, production_val
            ) if production_val else None

        if 'цех' in keys:
            workshop_val = get('цех')
            # Передаём production_obj чтобы при создании цеха сразу привязать производство
            data['workshop'] = self._get_or_create_workshop(
                workshop_val,
                data.get('production'),
            ) if workshop_val else None

        if 'причина увольнения' in keys:
            dismissal_val = get('причина увольнения')
            data['dismissal_reason'] = self._get_or_create(
                self._dismissal_reason_cache, DismissalReason, dismissal_val
            ) if dismissal_val else None

        if 'категория рабочего' in keys:
            category_val = get('категория рабочего')
            data['employee_category'] = self._get_or_create(
                self._category_cache, EmployeeCategory, category_val
            ) if category_val else None

        if 'должность' in keys:
            position_val = get('должность')
            data['position'] = self._get_or_create(
                self._position_cache, Position, position_val
            ) if position_val else None

        # МЯГКОЕ обновление (закомментировано):
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
        required = {'фио', 'табельный номер', 'дата приема на работу'}
        missing = required - set(df.columns)
        if missing:
            raise ValidationError(f"Отсутствуют колонки: {', '.join(missing)}")

        # Загружаем справочники в кэш
        self._load_caches()

        # Загружаем существующих сотрудников одним запросом
        existing_employees = {
            e.employee_number: e
            for e in Employee.objects.all()
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
