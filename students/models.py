from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models


def academic_year_of(day):
    """Год начала учебного года, в который попадает дата: 15.03.2027 -> 2026 (2026/2027)."""
    return day.year if day.month >= 9 else day.year - 1


def current_academic_year(today=None):
    """Год начала текущего учебного года."""
    return academic_year_of(today or date.today())


# Справочники

class EducationalInstitution(models.Model):
    # Справочник учебных заведений
    name = models.CharField(
        max_length=500,
        unique=True,
        verbose_name="Полное наименование ОО (по Уставу)",
        db_index=True
    )
    short_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Краткое наименование"
    )

    class Meta:
        verbose_name = "Учебное заведение"
        verbose_name_plural = "Учебные заведения"
        ordering = ['name']

    def __str__(self):
        return self.short_name or self.name


class Specialty(models.Model):
    # Справочник специальностей (приказы Минобрнауки №1061 и №1199).
    # Заполним позже из таблицы; уровень/наименование/квалификация
    # в отчёт подтягиваются отсюда по коду.
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Код направления",
        db_index=True
    )
    name = models.CharField(max_length=500, verbose_name="Наименование")
    level = models.CharField(max_length=255, blank=True, verbose_name="Уровень образования")
    qualification = models.CharField(max_length=255, blank=True, verbose_name="Квалификация")

    class Meta:
        verbose_name = "Специальность"
        verbose_name_plural = "Специальности"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} {self.name}"


# Студент

class Student(models.Model):

    class AdmissionKind(models.TextChoices):
        TARGET = 'target', 'Студент-целевик'
        UPC = 'upc', 'Ученик УПЦ'

    class PaymentMethod(models.TextChoices):
        BANK = 'bank', 'Банк'
        CASH = 'cash', 'Касса'

    class ContractParty(models.TextChoices):
        APPLICANT = 'applicant', 'Абитуриент (в рамках квот целевого приема)'
        SENIOR = 'senior', 'Студент (старшекурсник)'

    class StudyForm(models.TextChoices):
        FULL_TIME = 'full_time', 'Очная'
        PART_TIME = 'part_time', 'Очно-заочная'
        EXTRAMURAL = 'extramural', 'Заочная'
        EVENING = 'evening', 'Вечерняя'

    class StudyStatus(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'В процессе обучения'
        COMPLETED = 'completed', 'Обучение завершено'
        NOT_COMPLETED = 'not_completed', 'Обучение не завершено'

    # Данные из Oracle
    # Даты приёма/увольнения синхронизация обновляет всегда, остальные поля — только если они пустые (ручные правки главнее).
    employee_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Табельный номер",
        db_index=True
    )
    last_name = models.CharField(max_length=100, verbose_name="Фамилия")
    first_name = models.CharField(max_length=100, verbose_name="Имя")
    middle_name = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")

    hiring_date = models.DateField(verbose_name="Дата приёма")
    dismissal_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата отчисления",
        help_text="Пусто — обучается (в Oracle это 31.12.2099)"
    )
    admission_kind = models.CharField(
        max_length=20,
        choices=AdmissionKind.choices,
        verbose_name="Вид приёма",
        db_index=True
    )

    passport_series = models.CharField(max_length=10, blank=True, verbose_name="Серия паспорта")
    passport_number = models.CharField(max_length=20, blank=True, verbose_name="Номер паспорта")
    passport_issue_date = models.DateField(null=True, blank=True, verbose_name="Дата выдачи")
    passport_issued_by = models.CharField(max_length=500, blank=True, verbose_name="Кем выдан")
    snils = models.CharField(max_length=14, blank=True, verbose_name="СНИЛС")
    inn = models.CharField(max_length=12, blank=True, default='', verbose_name='ИНН')
    address = models.CharField(max_length=500, blank=True, default='', verbose_name='Адрес регистрации')

    # Заполняется вручную
    institution = models.ForeignKey(
        EducationalInstitution,
        on_delete=models.PROTECT,
        related_name='students',
        verbose_name="Учебное заведение",
        null=True,
        blank=True
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        verbose_name="Способ получения"
    )

    # Поля для отчёта
    specialty = models.ForeignKey(
        Specialty,
        on_delete=models.PROTECT,
        related_name='students',
        verbose_name="Специальность",
        null=True,
        blank=True
    )
    training_program = models.CharField(max_length=255, blank=True, verbose_name="Программа подготовки")
    contract_party = models.CharField(
        max_length=20,
        choices=ContractParty.choices,
        blank=True,
        verbose_name="Договор целевого обучения (сторона)"
    )
    study_form = models.CharField(
        max_length=20,
        choices=StudyForm.choices,
        blank=True,
        verbose_name="Форма обучения"
    )
    study_status = models.CharField(
        max_length=20,
        choices=StudyStatus.choices,
        blank=True,
        verbose_name="Статус обучения"
    )
    admission_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Год поступления")
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Год окончания")
    contract_expenses = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Расходы по договору нарастающим итогом (тыс. руб.)"
    )
    employment_position = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Трудоустройство (профессия/должность)"
    )
    employment_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Год трудоустройства")
    current_employee_status = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Текущий статус работника"
    )
    non_fulfillment_reasons = models.TextField(blank=True, verbose_name="Причины неисполнения обязательств")
    measures_taken = models.TextField(blank=True, verbose_name="Принятые меры")
    contract_number = models.CharField(max_length=100, blank=True, verbose_name="№ договора")
    contract_date = models.DateField(null=True, blank=True, verbose_name="Дата договора")
    has_additional_agreement = models.BooleanField(default=False, verbose_name="Доп. соглашение")
    additional_agreement_number = models.CharField(max_length=100, blank=True, verbose_name="№ доп. соглашения")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Студент"
        verbose_name_plural = "Студенты"
        ordering = ['last_name', 'first_name', 'middle_name']

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def is_studying(self):
        return self.dismissal_date is None

    @property
    def current_course(self):
        """Курс в текущем учебном году (только для обучающихся)."""
        if not self.is_studying:
            return None
        return self.course_for(current_academic_year())

    def course_for(self, academic_year_start):
        """Курс в учебном году academic_year_start/academic_year_start+1.
        None — если год поступления не заполнен или студент в этом году не учился."""
        if not self.admission_year:
            return None
        course = academic_year_start - self.admission_year + 1
        if course < 1:
            return None
        if self.graduation_year and academic_year_start >= self.graduation_year:
            return None
        return course


class StudentHistory(models.Model):
    # История поступлений/отчислений (табельный может повторяться при перепоступлении)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='history',
        verbose_name="Студент"
    )
    hiring_date = models.DateField(verbose_name="Дата приёма")
    dismissal_date = models.DateField(null=True, blank=True, verbose_name="Дата отчисления")

    class Meta:
        verbose_name = "Поступление/отчисление"
        verbose_name_plural = "История поступлений/отчислений"
        ordering = ['-hiring_date']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'hiring_date'],
                name='unique_student_hiring_date',
            )
        ]

    def __str__(self):
        return f"{self.student} {self.hiring_date} — {self.dismissal_date or 'обучается'}"


# Справки об успеваемости

class AcademicCertificate(models.Model):

    class Semester(models.IntegerChoices):
        WINTER = 1, '1 семестр (зима)'
        SUMMER = 2, '2 семестр (лето)'

    class Grade(models.IntegerChoices):
        EXCELLENT = 5, 'Отлично'
        GOOD = 4, 'Хорошо'
        SATISFACTORY = 3, 'Удовлетворительно'
        UNSATISFACTORY = 2, 'Неудовлетворительно'

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='certificates',
        verbose_name="Студент"
    )
    academic_year = models.PositiveSmallIntegerField(
        verbose_name="Учебный год",
        help_text="Год начала: 2025 = 2025/2026"
    )
    semester = models.PositiveSmallIntegerField(choices=Semester.choices, verbose_name="Семестр")
    number = models.CharField(max_length=100, verbose_name="Номер справки")
    grade = models.PositiveSmallIntegerField(choices=Grade.choices, verbose_name="Оценка")
    valid_from = models.DateField(verbose_name="Действует с")
    valid_to = models.DateField(verbose_name="Действует по")
    scan = models.FileField(
        upload_to='students/certificates/%Y/',
        blank=True,
        validators=[FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png'])],
        verbose_name="Скан справки"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Справка об успеваемости"
        verbose_name_plural = "Справки об успеваемости"
        ordering = ['-academic_year', '-semester']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'academic_year', 'semester'],
                name='unique_student_semester_certificate',
            )
        ]

    def __str__(self):
        return f"{self.student} — {self.academic_year}/{self.academic_year + 1}, {self.semester} сем."

    @property
    def is_current(self):
        """Действует на сегодня."""
        return self.valid_from <= date.today() <= self.valid_to
    
    def clean(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({'valid_to': 'Дата окончания раньше даты начала'})


# Стипендия (помесячно)

KOPECK = Decimal('0.01')
INCREASE_RATE = Decimal('1.5')   # 150%
TAX_RATE = Decimal('0.13')       # НДФЛ


class Scholarship(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='scholarships',
        verbose_name="Студент"
    )
    period = models.DateField(
        verbose_name="Месяц",
        help_text="Всегда первое число месяца"
    )
    academic_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Академическая стипендия (с ур. коэф.)"
    )
    adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name="Надбавка (+) / вычет (−)"
    )

    class Meta:
        verbose_name = "Стипендия"
        verbose_name_plural = "Стипендии"
        ordering = ['-period']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'period'],
                name='unique_student_scholarship_period',
            )
        ]

    def __str__(self):
        return f"{self.student} — {self.period:%m.%Y}"

    def save(self, *args, **kwargs):
        # Нормализуем период к первому числу месяца
        if self.period:
            self.period = self.period.replace(day=1)
        super().save(*args, **kwargs)

    @property
    def increased_amount(self):
        return (self.academic_amount * INCREASE_RATE).quantize(KOPECK, ROUND_HALF_UP)

    @property
    def tax(self):
        return (self.increased_amount * TAX_RATE).quantize(KOPECK, ROUND_HALF_UP)

    @property
    def total(self):
        return self.increased_amount - self.tax + self.adjustment


# Журнал синхронизаций с Oracle

class StudentSyncLog(models.Model):

    class Status(models.TextChoices):
        RUNNING = 'running', 'Выполняется'
        SUCCESS = 'success', 'Успешно'
        FAILED = 'failed', 'Ошибка'

    started_at = models.DateTimeField(auto_now_add=True, verbose_name="Начало")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Окончание")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.RUNNING,
        verbose_name="Статус"
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='+',
        null=True,
        blank=True,
        verbose_name="Запустил",
        help_text="Пусто — по расписанию"
    )
    total_rows = models.PositiveIntegerField(default=0, verbose_name="Строк во вьюхе")
    created = models.PositiveIntegerField(default=0, verbose_name="Создано")
    updated = models.PositiveIntegerField(default=0, verbose_name="Изменено")
    unchanged = models.PositiveIntegerField(default=0, verbose_name="Без изменений")
    skipped = models.PositiveIntegerField(default=0, verbose_name="Пропущено (отчислены до порога)")
    errors = models.JSONField(default=list, blank=True, verbose_name="Ошибки в строках")
    message = models.TextField(blank=True, verbose_name="Сообщение об ошибке")

    class Meta:
        verbose_name = "Синхронизация с Oracle"
        verbose_name_plural = "Журнал синхронизаций с Oracle"
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.started_at:%d.%m.%Y %H:%M} — {self.get_status_display()}"
