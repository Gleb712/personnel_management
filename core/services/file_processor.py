import pandas as pd
from datetime import datetime, date
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from core.models import (
    Employee, Production, Workshop, DismissalReason, 
    EmployeeCategory, Position
)


class EmployeeFileProcessor:
    """
    Класс для обработки файлов с данными о сотрудниках
    С оптимизацией для быстрой загрузки больших файлов
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
    
    def __init__(self, file, skip_duplicates=True, update_existing=False):
        """
        Инициализация обработчика файлов
        
        Args:
            file: Загруженный файл
            skip_duplicates: Пропускать дубликаты
            update_existing: Обновлять существующие записи
        """
        self.file = file
        self.skip_duplicates = skip_duplicates
        self.update_existing = update_existing
        
        self.success_count = 0
        self.skip_count = 0
        self.update_count = 0
        self.errors = []
        
        # Кэши для справочников (загружаются один раз)
        self._production_cache = {}
        self._workshop_cache = {}
        self._dismissal_reason_cache = {}
        self._category_cache = {}
        self._position_cache = {}
        
        # Кэш существующих табельных номеров
        self._existing_employee_numbers = set()
    
    def read_file(self):
        """
        Чтение файлов Excel и CSV
        
        Returns:
            pandas.DataFrame: Таблица с данными
        """
        file_extension = self.file.name.split('.')[-1].lower()
        
        try:
            if file_extension == 'csv':
                encodings = ['utf-8', 'cp1251', 'utf-8-sig']
                df = None
                
                for encoding in encodings:
                    try:
                        self.file.seek(0)
                        df = pd.read_csv(
                            self.file,
                            encoding=encoding,
                            dtype={'табельный номер': str}
                        )
                        break
                    except UnicodeDecodeError:
                        continue
                
                if df is None:
                    raise ValidationError("Не удалось определить кодировку CSV файла")
            
            elif file_extension in ['xlsx', 'xls']:
                self.file.seek(0)
                df = pd.read_excel(self.file)
                
                # Преобразуем табельный номер в строку
                if 'табельный номер' in df.columns:
                    df['табельный номер'] = df['табельный номер'].astype(str)
                
                # Преобразуем цех в строку
                if 'цех' in df.columns:
                    df['цех'] = df['цех'].astype(str)
            
            else:
                raise ValidationError(f"Неподдерживаемый формат: {file_extension}")
            
            return df
        
        except Exception as e:
            raise ValidationError(f"Ошибка чтения файла: {str(e)}")
    
    def parse_date(self, date_value):
        """
        Преобразование значения в объект date
        
        Args:
            date_value: Значение для преобразование, может быть:
                - str
                - datetime
                - date
                - None/NaN
        
        Returns:
            date или None
        """
        if pd.isna(date_value) or date_value == '' or date_value is None:
            return None
        
        if isinstance(date_value, datetime):
            return date_value.date()
        
        if isinstance(date_value, date):
            return date_value
        
        if isinstance(date_value, str):
            date_formats = [
                '%Y-%m-%d',
                '%d.%m.%Y',
                '%d/%m/%Y',
                '%Y.%m.%d',
            ]
            
            for fmt in date_formats:
                try:
                    return datetime.strptime(date_value.strip(), fmt).date()
                except ValueError:
                    continue
            
            raise ValueError(f"Неверный формат даты: {date_value}")
        
        return None
    
    def _load_reference_cache(self):
        """
        Загрузка всех справочников в память.

        Выполняет 1 запрос к БД для каждого справочника и сохраняет результат в словари для быстрого доступа
        """
        # Загружаем все существующие записи одним запросом
        self._production_cache = {
            prod.name: prod 
            for prod in Production.objects.all()
        }
        self._workshop_cache = {
            ws.number: ws 
            for ws in Workshop.objects.all()
        }
        self._dismissal_reason_cache = {
            reason.name: reason 
            for reason in DismissalReason.objects.all()
        }
        self._category_cache = {
            cat.name: cat 
            for cat in EmployeeCategory.objects.all()
        }
        self._position_cache = {
            pos.name: pos 
            for pos in Position.objects.all()
        }
    
    def _get_or_create_reference(self, cache_dict, model, value, field_name='name'):
        """
        Получить запись из кэша или создать новую запись в БД

        Args:
            cache_dict: Словарь кэша для конкретного справочника
            model: класс модели Django
            value: Значение для поиска
            field_name: Название поля для поиска. По умолчанию 'name'

        Returns:
            Объект модели или None
        """
        if not value or pd.isna(value):
            return None
        
        value = str(value).strip()
        
        if not value:
            return None
        
        # Проверяем кэш
        if value in cache_dict:
            return cache_dict[value]
        
        # Создаём новую запись
        obj, created = model.objects.get_or_create(
            **{field_name: value}
        )
        
        # Добавляем в кэш
        cache_dict[value] = obj
        
        return obj
    
    def _load_existing_employee_numbers(self):
        """
        Загрузка всех существующих табельных номеров в память

        Выполняет 1 запрос к БД для получения все табельных номеров и сохраняет результат в множество для быстрой проверки дубликатов
        """
        self._existing_employee_numbers = set(
            Employee.objects.values_list('employee_number', flat=True)
        )
    
    def _get_reference_value(self, row_data, row_keys_lower, column_name):
        """
        Получение значения из строки по имени колонки

        Args:
            row_data: Словарь с данными строки
            row_keys_lower: Словарь mapping lowercase ключей
            column_name: Имя колонки для поиска в нижнем регистре

        Returns:
            _type_: str или None
        """
        key = row_keys_lower.get(column_name)
        if key:
            value = row_data[key]
            if value and not pd.isna(value):
                return str(value).strip()
        return None
    
    def process_row(self, row_data, row_number):
        """
        Обработка одной строки данных

        Извлекает данные, выполняет валидацию, проверяет дубликаты и создает объект Employee (без созранения в БД)
        Args:
            row_data: Словарь с данными  строки
            row_number: Номер строки в файле

        Raises:
            ValidationError: Если отсутствуют обязательные поля или не прошло валидацию

        Returns:
            _type_: Employee или None
        """
        try:
            employee_data = {}
            row_keys_lower = {str(k).strip().lower(): k for k in row_data.keys()}
            
            # Простые поля
            key = row_keys_lower.get('фио')
            if key:
                value = row_data[key]
                if isinstance(value, str):
                    value = value.strip()
                employee_data['full_name'] = value
            
            key = row_keys_lower.get('табельный номер')
            if key:
                value = row_data[key]
                if pd.isna(value) or value == '':
                    value = None
                elif isinstance(value, str):
                    value = value.strip()
                else:
                    value = str(value).strip()
                employee_data['employee_number'] = value
            
            key = row_keys_lower.get('дата рождения')
            if key:
                employee_data['birth_date'] = self.parse_date(row_data[key])
            
            key = row_keys_lower.get('дата приема на работу')
            if key:
                employee_data['hire_date'] = self.parse_date(row_data[key])
            
            key = row_keys_lower.get('дата увольнения')
            if key:
                employee_data['dismissal_date'] = self.parse_date(row_data[key])
            
            # Проверка обязательных полей
            if not employee_data.get('employee_number'):
                raise ValidationError(f"Строка {row_number}: Отсутствует табельный номер")
            
            if not employee_data.get('full_name'):
                raise ValidationError(f"Строка {row_number}: Отсутствует ФИО")
            
            if not employee_data.get('hire_date'):
                raise ValidationError(f"Строка {row_number}: Отсутствует дата приема")
            
            # Проверка дубликатов (через кэш, без запроса к БД)
            if employee_data['employee_number'] in self._existing_employee_numbers:
                if self.skip_duplicates:
                    self.skip_count += 1
                    return None
                elif self.update_existing:
                    # Для обновления нужно будет загрузить объект отдельно
                    self.skip_count += 1
                    return None
                else:
                    raise ValidationError(
                        f"Строка {row_number}: Сотрудник с табельным номером "
                        f"{employee_data['employee_number']} уже существует"
                    )
            
            # Справочники (из кэша или создание)
            production_value = self._get_reference_value(row_data, row_keys_lower, 'производство')
            if production_value:
                employee_data['production'] = self._get_or_create_reference(
                    self._production_cache, Production, production_value
                )
            
            workshop_value = self._get_reference_value(row_data, row_keys_lower, 'цех')
            if workshop_value:
                workshop = self._get_or_create_reference(
                    self._workshop_cache, Workshop, workshop_value, field_name='number'
                )
                employee_data['workshop'] = workshop
            
            dismissal_reason_value = self._get_reference_value(row_data, row_keys_lower, 'причина увольнения')
            if dismissal_reason_value:
                employee_data['dismissal_reason'] = self._get_or_create_reference(
                    self._dismissal_reason_cache, DismissalReason, dismissal_reason_value
                )
            
            category_value = self._get_reference_value(row_data, row_keys_lower, 'категория рабочего')
            if category_value:
                employee_data['employee_category'] = self._get_or_create_reference(
                    self._category_cache, EmployeeCategory, category_value
                )
            
            position_value = self._get_reference_value(row_data, row_keys_lower, 'должность')
            if position_value:
                employee_data['position'] = self._get_or_create_reference(
                    self._position_cache, Position, position_value
                )
            
            # Создаём объект (без сохранения)
            employee = Employee(**employee_data)
            
            return employee
            
        except ValidationError as e:
            self.errors.append(str(e))
            return None
        except Exception as e:
            self.errors.append(f"Строка {row_number}: {str(e)}")
            return None
    
    @transaction.atomic
    def process(self):
        """
        Основной метод обработки файла с оптимизацией
        
        Returns:
            dict: Статистика обработки
        """
        from django.db import connection
        start_time = datetime.now()
        
        # Чтение файла
        df = self.read_file()
        
        print(f"\nВСЕГО СТРОК В ФАЙЛЕ: {len(df)}")
        print(f"КОЛОНКИ: {df.columns.tolist()}")
        
        if df.empty:
            raise ValidationError("Файл пустой")
        
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        # Фильтрация
        if len(df) > 0:
            first_col = df.iloc[:, 0].astype(str).str.lower().str.strip()
            df = df[~first_col.isin(['фио', '---'])]
            df = df.reset_index(drop=True)
            print(f"ПОСЛЕ ОЧИСТКИ: {len(df)} строк")
        
        # Проверка колонок
        required_columns = [col.lower() for col in self.COLUMN_MAPPING.keys()]
        missing_columns = set(required_columns) - set(df.columns)
        
        if missing_columns:
            raise ValidationError(
                f"В файле отсутствуют необходимые колонки: {', '.join(missing_columns)}"
            )
        
        # === ОПТИМИЗАЦИЯ: Загружаем кэши ===
        print("\nЗагрузка справочников в память...")
        self._load_reference_cache()
        print(f"  Загружено производств: {len(self._production_cache)}")
        print(f"  Загружено цехов: {len(self._workshop_cache)}")
        
        print("Загрузка существующих табельных номеров...")
        self._load_existing_employee_numbers()
        print(f"  Найдено существующих сотрудников: {len(self._existing_employee_numbers)}")
        # =================================
        
        # Обработка всех строк (без сохранения)
        print("\nОбработка строк...")
        employees_to_create = []
        
        for index, row in df.iterrows():
            row_number = index + 2
            employee = self.process_row(row.to_dict(), row_number)
            if employee:
                employees_to_create.append(employee)
        
        # Оптимизация: Bulk create
        print(f"\nСохранение {len(employees_to_create)} записей...")
        
        if employees_to_create:
            Employee.objects.bulk_create(employees_to_create, batch_size=1000)
            self.success_count = len(employees_to_create)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        return {
            'success': self.success_count,
            'skipped': self.skip_count,
            'updated': self.update_count,
            'errors': self.errors,
            'total': len(df),
            'duration': duration
        }
    