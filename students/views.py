import os
from datetime import date

from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .forms import CertificateForm, StudentGeneralForm, StudentReportForm
from .models import (
    AcademicCertificate, EducationalInstitution, Student,
    StudentSyncLog, academic_year_of, current_academic_year,
)
from .permissions import can_access_students
from .services.sync import run_sync


PER_PAGE = 50

# Поля из Oracle: в карточке только для чтения
ORACLE_FIELDS = [
    'employee_number', 'last_name', 'first_name', 'middle_name',
    'hiring_date', 'dismissal_date',
]

# Вкладки карточки: ключ -> (название, форма, разделы с полями)
# Поля, которых нет в модели (new_institution), показываются только в форме.
TABS = {
    'general': ('Общее', StudentGeneralForm, [
        ('Обучение', ['admission_kind', 'institution', 'new_institution', 'payment_method']),
        ('Личные данные', ['birth_date', 'snils', 'inn']),
        ('Паспорт', ['passport_series', 'passport_number', 'passport_issue_date', 'passport_issued_by']),
        ('Адрес регистрации', ['address']),
    ]),
    'study': ('Успеваемость', None, []),
    'scholarship': ('Стипендия', None, []),
    'report': ('Отчёт', StudentReportForm, [
        ('Специальность и обучение', ['specialty', 'training_program', 'contract_party',
                                      'study_form', 'study_status',
                                      'admission_year', 'graduation_year']),
        ('Договор', ['contract_number', 'contract_date', 'has_additional_agreement',
                     'additional_agreement_number', 'contract_expenses']),
        ('Трудоустройство', ['employment_position', 'employment_year',
                             'current_employee_status']),
        ('Исполнение обязательств', ['non_fulfillment_reasons', 'measures_taken']),
    ]),
}


# Вспомогательное

def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _students_queryset():
    last_grade = (
        AcademicCertificate.objects
        .filter(student=OuterRef('pk'))
        .order_by('-academic_year', '-semester')
        .values('grade')[:1]
    )
    return Student.objects.select_related('institution').annotate(last_grade=Subquery(last_grade))


def _add_grade_labels(students):
    for s in students:
        s.last_grade_label = AcademicCertificate.Grade(s.last_grade).label if s.last_grade else None


def _display(student, name):
    """(подпись, значение) поля для режима просмотра; None — поля нет в модели."""
    try:
        field = Student._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    value = getattr(student, name)
    if field.choices:
        value = getattr(student, f'get_{name}_display')()
    if isinstance(value, bool):
        value = 'Да' if value else 'Нет'
    elif isinstance(value, date):
        value = value.strftime('%d.%m.%Y')
    if value in (None, ''):
        value = '—'
    return field.verbose_name, value


def _tab_context(student, tab, form=None):
    title, form_class, sections = TABS[tab]
    context = {
        'student': student,
        'tab': tab,
        'form': form,
        'editable': form_class is not None,
        'oracle': [_display(student, f) for f in ORACLE_FIELDS] if tab == 'general' else [],
    }
    if form is not None:
        context['sections'] = [
            (section, [form[name] for name in names]) for section, names in sections
        ]
    else:
        context['sections'] = [
            (section, [d for d in (_display(student, n) for n in names) if d])
            for section, names in sections
        ]
    return context


def _tab_template(tab, form):
    if TABS[tab][1] is None:
        return 'students/partials/tab_placeholder.html'
    return 'students/partials/tab_form.html' if form is not None else 'students/partials/tab_view.html'


# Список

@can_access_students
def student_list(request):
    params = request.GET
    students = _students_queryset()

    for word in params.get('search', '').split():
        students = students.filter(
            Q(last_name__icontains=word) | Q(first_name__icontains=word)
            | Q(middle_name__icontains=word) | Q(employee_number__icontains=word)
        )

    institution = _int(params.get('institution'))
    if institution:
        students = students.filter(institution_id=institution)
    for name in ('admission_kind', 'study_form', 'payment_method'):
        if params.get(name):
            students = students.filter(**{name: params[name]})

    status = params.get('status')
    if status == 'studying':
        students = students.filter(dismissal_date__isnull=True)
    elif status == 'dismissed':
        students = students.filter(dismissal_date__isnull=False)

    course = _int(params.get('course'))
    if course:
        students = students.filter(
            admission_year=current_academic_year() - course + 1,
            dismissal_date__isnull=True,
        )

    grade = params.get('grade')
    if grade == 'none':
        students = students.filter(last_grade__isnull=True)
    elif _int(grade):
        students = students.filter(last_grade=_int(grade))

    page_obj = Paginator(students.order_by('last_name', 'first_name', 'middle_name'), PER_PAGE) \
        .get_page(params.get('page'))
    _add_grade_labels(page_obj)

    query = params.copy()
    query.pop('page', None)

    context = {
        'page_obj': page_obj,
        'filter_query': query.urlencode(),
        'f': params,
        'institutions': EducationalInstitution.objects.all(),
        'admission_kinds': Student.AdmissionKind.choices,
        'study_forms': Student.StudyForm.choices,
        'payment_methods': Student.PaymentMethod.choices,
        'grades': AcademicCertificate.Grade.choices,
        'courses': range(1, 7),
        'last_sync': StudentSyncLog.objects.exclude(status=StudentSyncLog.Status.RUNNING).first(),
    }
    if request.headers.get('HX-Target') == 'table-wrap':
        return render(request, 'students/partials/student_table.html', context)
    return render(request, 'students/student_list.html', context)


@can_access_students
def student_row(request, pk):
    student = get_object_or_404(_students_queryset(), pk=pk)
    _add_grade_labels([student])
    return render(request, 'students/partials/student_row.html', {'s': student})


# Карточка

@can_access_students
def student_card(request, pk):
    student = get_object_or_404(Student, pk=pk)
    context = _tab_context(student, 'general')
    context['tabs'] = [(key, value[0]) for key, value in TABS.items()]
    context['tab_template'] = _tab_template('general', None)
    return render(request, 'students/partials/card.html', context)


@can_access_students
def student_tab(request, pk, tab):
    if tab not in TABS:
        raise Http404
    student = get_object_or_404(Student, pk=pk)
    if tab == 'study':
        return _render_study(request, student)
    form_class = TABS[tab][1]
    form = None

    if form_class and request.method == 'POST':
        form = form_class(request.POST, instance=student)
        if form.is_valid():
            form.save()
            response = render(request, _tab_template(tab, None), _tab_context(student, tab))
            response['HX-Trigger'] = f'student-updated-{student.pk}'  # обновить строку в списке
            return response
    elif form_class and request.GET.get('edit'):
        form = form_class(instance=student)

    return render(request, _tab_template(tab, form), _tab_context(student, tab, form))


# Успеваемость

MAX_STUDY_YEARS = 10  # защита от кривых дат


def _study_years(student, certificates):
    """Учебные годы студента: от поступления до окончания (или до текущего)."""
    first = student.admission_year or academic_year_of(student.hiring_date)
    if student.graduation_year:
        last = student.graduation_year - 1
    elif student.dismissal_date:
        last = academic_year_of(student.dismissal_date)
    else:
        last = current_academic_year()
    last = min(max(last, first), first + MAX_STUDY_YEARS)
    years = set(range(first, last + 1)) | {c.academic_year for c in certificates}
    return sorted(years)


def _render_study(request, student, trigger=False):
    certificates = list(student.certificates.all())
    by_cell = {(c.academic_year, c.semester): c for c in certificates}
    semesters = AcademicCertificate.Semester.choices
    rows = [
        {
            'year': year,
            'course': student.course_for(year),
            'cells': [(number, by_cell.get((year, number))) for number, _ in semesters],
        }
        for year in _study_years(student, certificates)
    ]
    response = render(request, 'students/partials/tab_study.html', {
        'student': student,
        'rows': rows,
        'semesters': semesters,
        'count': len(certificates),
    })
    if trigger:
        response['HX-Trigger'] = f'student-updated-{student.pk}'  # обновить оценку в строке
    return response


@can_access_students
def certificate_form(request, pk, cert_pk=None):
    student = get_object_or_404(Student, pk=pk)
    if cert_pk:
        certificate = get_object_or_404(AcademicCertificate, pk=cert_pk, student=student)
    else:
        certificate = AcademicCertificate(
            student=student,
            academic_year=_int(request.GET.get('year')),
            semester=_int(request.GET.get('semester')),
        )
    years = _study_years(student, student.certificates.all())

    if request.method == 'POST':
        form = CertificateForm(request.POST, request.FILES, instance=certificate, years=years)
        if form.is_valid():
            form.save()
            return _render_study(request, student, trigger=True)
    else:
        form = CertificateForm(instance=certificate, years=years)

    return render(request, 'students/partials/certificate_form.html', {
        'student': student,
        'certificate': certificate,
        'form': form,
    })


@require_POST
@can_access_students
def certificate_delete(request, pk, cert_pk):
    certificate = get_object_or_404(AcademicCertificate, pk=cert_pk, student_id=pk)
    certificate.scan.delete(save=False)
    certificate.delete()
    return _render_study(request, certificate.student, trigger=True)


@can_access_students
def certificate_scan(request, cert_pk):
    """Скан отдаётся только пользователям раздела, а не напрямую из /media/."""
    certificate = get_object_or_404(AcademicCertificate, pk=cert_pk)
    if not certificate.scan:
        raise Http404
    return FileResponse(certificate.scan.open('rb'), filename=os.path.basename(certificate.scan.name))


# Синхронизация

@require_POST
@can_access_students
def sync_now(request):
    log = run_sync(user=request.user)
    response = render(request, 'students/partials/sync_result.html', {'log': log})
    if log.status == StudentSyncLog.Status.SUCCESS:
        response['HX-Trigger'] = 'students-synced'  # перерисовать таблицу
    return response
