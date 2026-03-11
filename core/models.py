from django.db import models
from django.core.exceptions import ValidationError

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
        max_length=4,
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
    
class Employee(models.Model):
    # Основная таблица с работниками
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
        on_delete=models.PROTECT,
        related_name='production_employees',
        verbose_name="Производство",
        null=True,
        blank=True
    )
    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.PROTECT,
        related_name='workshop_employees',
        verbose_name="Цех",
        null=True,
        blank=True
    )
    dismissal_reason = models.ForeignKey(
        DismissalReason,
        on_delete=models.PROTECT,
        related_name='dismissal_employees',
        verbose_name="Причина увольнения",
        null=True,
        blank=True
    )
    employee_category = models.ForeignKey(
        EmployeeCategory,
        on_delete=models.PROTECT,
        related_name='category_employees',
        verbose_name="Категория работника",
        null=True,
        blank=True
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name='position_employees',
        verbose_name="Должность",
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

    def clean(self):
        """Валидация перед сохранением"""
        if self.hire_date and self.dismissal_date:
            if self.dismissal_date < self.hire_date:
                raise ValidationError(
                    "Дата увольнения не может быть раньше даты приема"
                )
            
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ['full_name']
        indexes = [models.Index(fields=['dismissal_date'])]

    def __str__(self):
        return f"{self.full_name} №({self.employee_number})"
    