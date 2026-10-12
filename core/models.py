from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
 
 
class Production(models.Model):
    # Справочник производств
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Название производства",
        db_index=True
    )

    class Meta:
        verbose_name = "Производство"
        verbose_name_plural = "Производства"
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
class Workshop(models.Model):
    # Справочник цехов
    number = models.CharField(
        unique=True,
        verbose_name="Номер цеха",
        db_index=True
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Название цеха",
        blank=True,
        help_text="Полное название цеха (необязательное поле)"
    )
    production = models.ForeignKey(
        Production,
        on_delete=models.PROTECT,
        related_name='workshops',
        verbose_name="Производство",
        null=True,
        blank=True
    )
    
    class Meta:
        verbose_name = "Цех"
        verbose_name_plural = "Цеха"
        ordering = ['number']
    
    def __str__(self):
        return f"Цех {self.number}"
    
class DismissalReason(models.Model):
    # Справочник причин увольнений
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Причина увольнения",
        db_index=True
    )

    class Meta:
        verbose_name = "Причина увольнения"
        verbose_name_plural = "Причины увольнения"
        ordering = ['name']

    def __str__(self):
        return self.name

class HireSource(models.Model):
    # Источники приема
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Источник приема",
        db_index=True
    )

    class Meta:
        verbose_name = "Источник приема"
        verbose_name_plural = "Источники приема"
        ordering = ['name']

    def __str__(self):
        return self.name

class EmployeeCategory(models.Model):
    # Справочник категорий работников
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Категория работника",
        db_index=True
    )
    
    class Meta:
        verbose_name = "Категория работника"
        verbose_name_plural = "Категории работников"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Position(models.Model):
    # Справочник должностей работников
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Должность",
        db_index=True
    )

    class Meta:
        verbose_name = "Должность"
        verbose_name_plural = "Должности"
        ordering = ['name']

    def __str__(self):
        return self.name

class EmployeeGrades(models.Model):
    # Справочник разрядов
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Разряд",
        db_index=True
    )

    class Meta:
        verbose_name = "Разряд"
        verbose_name_plural = "Разряды"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class HireCategory(models.Model):
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="Категория приема",
        db_index=True
    )

    class Meta:
        verbose_name = "Категория приема"
        verbose_name_plural = "Категории приема"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Employee(models.Model):
    # Основная таблица с работниками

    GENDER_CHOICES = [
        ('Мужской', 'Мужской'),
        ('Женский', 'Женский'),
    ]

    full_name = models.CharField(
        max_length=255,
        verbose_name="ФИО",
        db_index=True
    )
    employee_number = models.CharField(
        max_length=10,
        unique=True,
        verbose_name="Табельный номер",
        db_index=True
    )
    birth_date = models.DateField(
        verbose_name="Дата рождения",
        null=True,
        blank=True
    )
    hire_date = models.DateField(
        verbose_name="Дата приема на работу",
        null=False,
        blank=False
    )
    dismissal_date = models.DateField(
        verbose_name="Дата увольнения",
        null=True,
        blank=True
    )
    production = models.ForeignKey(
        Production,
        on_delete=models.SET_NULL,
        related_name='production_employees',
        verbose_name="Производство",
        null=True,
        blank=True
    )
    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.SET_NULL,
        related_name='workshop_employees',
        verbose_name="Цех",
        null=True,
        blank=True
    )
    dismissal_reason = models.ForeignKey(
        DismissalReason,
        on_delete=models.SET_NULL,
        related_name='dismissal_employees',
        verbose_name="Причина увольнения",
        null=True,
        blank=True
    )
    hire_source = models.ForeignKey(
        HireSource,
        on_delete=models.SET_NULL,
        related_name='hire_source_employees',
        verbose_name="Источник приема",
        null=True,
        blank=True
    )
    employee_category = models.ForeignKey(
        EmployeeCategory,
        on_delete=models.SET_NULL,
        related_name='category_employees',
        verbose_name="Категория работника",
        null=True,
        blank=True
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        related_name='position_employees',
        verbose_name="Должность",
        null=True,
        blank=True
    )
    grade = models.ForeignKey(
        EmployeeGrades,
        on_delete=models.SET_NULL,
        related_name='employee_grades',
        verbose_name="Разряд",
        null=True,
        blank=True
    )
    reg_address = models.CharField(
        verbose_name="Адрес регистрации",
        null=True,
        blank=True
    )
    gender = models.CharField(
        max_length=8,
        verbose_name='Пол',
        null=False,
        blank=False,
    )
    hire_category = models.ForeignKey(
        HireCategory,
        on_delete=models.SET_NULL,
        related_name='hire_category',
        verbose_name='Категория приема',
        null=True,
        blank=True
    )
    dismissal_date_fact = models.DateField(
        verbose_name="Дата увольнения(факт)",
        null=True,
        blank=True        
    )
    hire_order_num = models.CharField(
        max_length=20,
        verbose_name="Номер приказа о приёме",
        null=True,
        blank=True 
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания записи",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Даат обновления записи"
    )

    @property
    def expirence(self):
        from datetime import date
        from dateutil.relativedelta import relativedelta

        if self.dismissal_date is None:
            today = date.today()
        else:
            today = self.dismissal_date

        delta = relativedelta(today, self.hire_date)

        parts = []
        if delta.years:
            parts.append(f"{delta.years}{' год' if delta.years == 1 else ' года' if delta.years < 5 else ' лет'}")
        if delta.months:
            parts.append(f"{delta.months} мес.")
        if not parts:
            parts.append(f'Менее месяца')

        return ' '.join(parts)

    @property
    def age(self):
        from datetime import date

        today = date.today()
        _age = today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

        if _age % 10 == 1 and _age % 100 != 11:
            return f'{_age} год'
        elif 2 <= _age % 10 <= 4 and (_age % 100 < 10 or _age % 100 >= 20):
            return f'{_age} года'
        else:
            return f'{_age} лет'

    def clean(self):
        """Валидация перед сохранением"""
        if self.hire_date and self.dismissal_date:
            if self.dismissal_date < self.hire_date:
                raise ValidationError(
                    "Дата увольнения не может быть раньше даты приема"
                )
            
    def save(self, *args, **kwargs):
        # Производство автоматически подтягивается из цеха
        if self.workshop and self.workshop.production:
            self.production = self.workshop.production
        elif self.workshop and not self.workshop.production:
            self.production = None
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ['full_name']
        indexes = [models.Index(fields=['dismissal_date'])]

    def __str__(self):
        return f"{self.full_name} №({self.employee_number})"
    
class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Пользователь'
    )
    role = models.CharField(
        max_length=20,
        choices=[
            ('admin', 'Администратор'),
            ('hr', 'Директор по персоналу'),
            ('editor', 'Редактор'),
            ('viewer', 'Просмотр'),
        ],
        default='viewer',
        verbose_name='Роль'
    )
    # Полное ФИО сотрудника: "Иванов Иван Иванович"
    # Заполняется вручную при создании пользователя в /admin/
    full_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='ФИО',
        help_text='Полное ФИО: Иванов Иван Иванович'
    )
 
    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'
 
    def __str__(self):
        return f'Профиль: {self.user.username}'
 
    def get_short_name(self):
        """
        Возвращает ФИО в формате "Фамилия И.О."
        Примеры:
            "Иванов Иван Иванович» - "Иванов И.И."
            "Иванов Иван - "Иванов И."
            "" - "username"
        """
        name = self.full_name.strip()
        if not name:
            return self.user.username
        parts = name.split()
        if len(parts) >= 3:
            return f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
        if len(parts) == 2:
            return f"{parts[0]} {parts[1][0]}."
        return name
 
    def get_display_name(self):
        """Возвращает полное ФИО или username если ФИО не заполнено."""
        return self.full_name.strip() or self.user.username

class EmployeeTransfers(models.Model):
    # Переводы
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name='transfers_employee',
        verbose_name="Переводы",
        # null=True,
        # blank=True,
    )

    order_number = models.CharField(
        max_length=64,
        verbose_name="Номер приказа",
        db_index=True        
    )

    transfer_date = models.DateField(
        verbose_name="Дата рождения",
    )

    from_workshop = models.ForeignKey(
        Workshop,
        on_delete=models.PROTECT,
        related_name='from_workshop',
        verbose_name='Из цеха',
        # null=True,
        # blank=True,
    )

    from_position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name='from_position',
        verbose_name='С должности',
        # null=True,
        # blank=True,
    )

    from_grade = models.ForeignKey(
        EmployeeGrades,
        on_delete=models.PROTECT,
        related_name='from_grade',
        verbose_name='С разряда',
        null=True,
        blank=True,
    )

    to_workshop = models.ForeignKey(
        Workshop,
        on_delete=models.PROTECT,
        related_name='to_workshop',
        verbose_name='В цех',
        # null=True,
        # blank=True,
    )

    to_position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name='to_position',
        verbose_name='На должность',
        # null=True,
        # blank=True,
    )

    to_grade = models.ForeignKey(
        EmployeeGrades,
        on_delete=models.PROTECT,
        related_name='to_grade',
        verbose_name='На разряд',
        null=True,
        blank=True,
    )

    from_category = models.ForeignKey(
        EmployeeCategory,
        on_delete=models.PROTECT,
        related_name='from_category',
        verbose_name='Категория до перевода',
        null=True,
    )

    to_category = models.ForeignKey(
        EmployeeCategory,
        on_delete=models.PROTECT,
        related_name='to_category',
        verbose_name='Категория после перевода',
        null=True,
    )

    class Meta:
        verbose_name = "Перевод"
        verbose_name_plural = "Переводы"
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'order_number', 'transfer_date'],
                name='unique_employee_transfers',
            )
        ]

class EmployeeHistory(models.Model):
    # История приемов/увольнений
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name='employee_history',
        verbose_name="id Работника",
    )
    hiring_date = models.DateField(
        verbose_name='Дата приема'
    )
    dismissal_date = models.DateField(
        verbose_name='Дата увольнения',
        null=True,
        blank=True
    )
    dismissal_reason = models.ForeignKey(
        DismissalReason,
        on_delete=models.SET_NULL,
        related_name='history_dismissal_employees',
        verbose_name="Причина увольнения",
        null=True,
        blank=True
    )
    hire_source = models.ForeignKey(
        HireSource,
        on_delete=models.SET_NULL,
        related_name='history_hire_source_employees',
        verbose_name="Источник приема",
        null=True,
        blank=True
    )
    hire_category = models.ForeignKey(
        HireCategory,
        on_delete=models.SET_NULL,
        related_name='hire_category_history',
        verbose_name='Категория приема',
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = "Приемы/увольнения"
        verbose_name_plural = "Прием/увольнение"
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'hiring_date', 'dismissal_date', 'dismissal_reason', 'hire_source', 'hire_category'],
                name='unique_employee_history',
            )
        ]

class ReportTable(models.Model): # Временно
    dep = models.CharField(null=True)
    prod = models.CharField()
    f_3 = models.IntegerField()
    f_4 = models.IntegerField()
    f_5 = models.FloatField()
    f_6 = models.IntegerField()
    f_7 = models.IntegerField()
    f_8 = models.FloatField()
    f_9 = models.FloatField()
    f_10 = models.IntegerField()
    f_11 = models.IntegerField()
    f_12 = models.FloatField()
    f_13 = models.FloatField()
    f_14 = models.FloatField()
    table_date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['dep', 'prod', 'f_3', 'f_4', 'f_5', 'f_6', 'f_7', 'f_8', 'f_9', 'f_10', 'f_11', 'f_12', 'f_13', 'f_14', 'table_date'],
                name='unique_table_report',
            )
        ]

class Salary(models.Model):
    # Зарплата
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name='employee_salary',
        verbose_name="id Работника",
    )   
    hours = models.FloatField(
        null=False,
        default=0,
        verbose_name='Часы',
    )
    main_sum = models.FloatField(
        null=False,
        default=0,
        verbose_name='Сумма',
    )
    vacation_sum = models.FloatField(
        null=False,
        default=0,
        verbose_name='Отпускные'
    )
    salary_date = models.DateField(
        null=False,
        verbose_name='Дата'
    )

    class Meta:
        verbose_name = "Зарплаты"
        verbose_name_plural = "Зарплата"
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'salary_date',],
                name='unique_employee_salary',
            )
        ]

    def __str__(self):
        return f'{self.employee} - {self.main_sum + self.vacation_sum}'