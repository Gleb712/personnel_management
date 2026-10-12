import json
 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Q, F, ExpressionWrapper, IntegerField, fields
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from datetime import datetime
from django.utils.decorators import method_decorator
 
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
 
from .forms import FileUploadForm, EmployeeEditForm
from .permissions import can_upload, can_edit, can_view, can_view_additional_info
from core.services.file_processor import *
from core.services.report_service import get_movement_report
from .models import Employee, Production, Workshop, EmployeeTransfers, EmployeeCategory, Salary

from core.permissions import login_required_custom

def _style_excel_sheet(ws, header_row=1):
    """
    Применяет оформление к листу Excel:
    Заголовок: приглушённый фон + полужирный шрифт
    Все ячейки: тонкая рамка + выравнивание
    Автоширина колонок
    """
    thin_border = Border(
        left=Side(style='thin', color='C0C0C0'),
        right=Side(style='thin', color='C0C0C0'),
        top=Side(style='thin', color='C0C0C0'),
        bottom=Side(style='thin', color='C0C0C0'),
    )
    header_font = Font(bold=True, size=10, color='333333')
    header_fill = PatternFill(start_color='EDEDED', end_color='EDEDED', fill_type='solid')
    body_font = Font(size=10, color='444444')
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left = Alignment(horizontal='left', vertical='center', wrap_text=True)

    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.border = thin_border
            if cell.row == header_row:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center
            else:
                cell.font = body_font
                # Первые 2 колонки — текст, остальные — по центру
                cell.alignment = left if cell.column <= 2 else center

    # Автоширина
    for col_idx in range(1, ws.max_column + 1):
        max_len = 0
        col_letter = get_column_letter(col_idx)
        for cell in ws[col_letter]:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 4, 30)

def _style_total_row(ws, row_num):
    """Выделяет строку итогов: полужирный шрифт + темный фон."""
    total_font = Font(bold=True, size=10, color='222222')
    total_fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
    for cell in ws[row_num]:
        cell.font = total_font
        cell.fill = total_fill

def login_view(request):
    """Страница входа. После успешной авторизации редиректит по роли."""
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)
 
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return _redirect_by_role(user)
        else:
            messages.error(request, 'Неверный логин или пароль')
    else:
        form = AuthenticationForm()
 
    return render(request, 'authorization/login.html', {'form': form})
 
def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('core:login')
 
def access_denied(request):
    """Страница 403 — недостаточно прав"""
    return render(request, 'authorization/access_denied.html', status=403)
 
def _redirect_by_role(user):
    """
    Редирект после авторизации в зависимости от роли:
      Суперпользователь        → core:upload_file
      Администратор            → core:upload_file
      Директор по персоналу    → core:dashboard
      Редактор                 → core:upload_file
      Просмотр                 → core:dashboard
      Без группы               → core:employee_list
    """
    if user.is_superuser:
        return redirect('core:upload_file')
 
    group_names = set(user.groups.values_list('name', flat=True))
 
    if 'Администратор' in group_names:
        return redirect('core:upload_file')
 
    if 'Редактор' in group_names:
        return redirect('core:upload_file')
    
    if 'Директор по персоналу' in group_names:
        return redirect('core:dashboard')
    
    if 'Просмотр' in group_names:
        return redirect('core:dashboard')
 
    # Директор по персоналу, Просмотр, без группы — на отчёты
    return redirect('core:employee_list')


# Основные view

def home_redirect(request):
    """Редирект с главной: авторизованных — по роли, остальных — на вход"""
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)
    return redirect('core:login')

@can_upload
def upload_file(request):
    """
    View для загрузки файла с сотрудниками
    """

    file_type = dict({
        'main':     'Данные сотрудников',
        'trans':    'Переводы',
        'hist':     'Прием/Увольнения',
        'table':    'Данные по сверхурочным',
        'salary':   'Зарплата',
    })

    if request.user.is_superuser:
        file_type['debug'] = 'Отладка'

    if request.method == 'POST':
        # Создаём форму с данными
        form = FileUploadForm(request.POST, request.FILES)

        if form.is_valid():
            # Получаем очищенные данные
            uploaded_file = request.FILES['file']
            selected_type = request.POST.get('file_type')
            try:
                # Создаём обработчик и обрабатываем файл
                match selected_type:
                    case 'main':
                        processor = EmployeeFileProcessor(uploaded_file)
                    case 'trans':
                        processor = TransfersFileProcessor(uploaded_file)
                    case 'hist':
                        processor = HistoryFileProcessor(uploaded_file)
                    case 'debug':
                        processor = DebugFileProcessor(uploaded_file)
                    case 'table':
                        processor = ReportTableFileProcessor(uploaded_file)
                    case 'salary':
                        processor = SalaryFileProcessor(uploaded_file)
                
                result = processor.process()

                # Результаты загрузки
                parts = []
                if result['success'] > 0:
                    parts.append(f"добавлено {result['success']}")
                if result['updated'] > 0:
                    parts.append(f"обновлено {result['updated']}")
                if result['error_count'] > 0:
                    parts.append(f"пропущено с ошибками {result['error_count']}")

                if parts:
                    msg = f"Загрузка завершена за {result['duration']:.1f} сек: {', '.join(parts)}."
                    if result['error_count'] > 0:
                        messages.warning(request, msg)
                    else:
                        messages.success(request, msg)
                else:
                    messages.info(request, "Файл обработан, новых изменений нет.")

                # Сообщение при ошибке загрузки
                if result['errors']:
                    request.session['upload_errors'] = result['errors'][:1000]

                return redirect('core:upload_file')
            except Exception as e:
                if str(e) != "'NoneType' object is not subscriptable":
                    messages.error(request, f"Ошибка: {str(e)}")
        else:
            messages.error(request, "Ошибка в форме загрузки")
    else:
        # Создаем пустую форму
        form = FileUploadForm()

    # Получаем ошибки из сессии и удаляем их
    errors = request.session.pop('upload_errors', [])

    return render(request, 'core/upload/upload_file.html', {
        'form': form,
        'errors': errors,
        'required_columns': ['ФИО', 'Табельный номер', 'Дата приема на работу', 'Пол', 'Вид приема'],
        'optional_columns': [
            'Дата рождения', 'Дата увольнения', 'Производство',
            'Цех', 'Причина увольнения', 'Категория рабочего', 'Должность', 
            'Источник приема', 'Разряд', 'Адрес регистрации',
        ],
        'file_type':      file_type,
    })

def _build_employee_queryset_and_context(request):
    """
    Общая логика фильтрации/пагинации сотрудников.
    Возвращает готовый context-словарь.
    """
    employees = Employee.objects.select_related(
        'production',
        'workshop',
        'dismissal_reason',
        'employee_category',
        'position'
    )

    search        = request.GET.get('search', '').strip()
    position      = request.GET.get('position', '').strip()
    category_id   = request.GET.get('category', '')
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    status        = request.GET.get('status', '')

    ALLOWED_PER_PAGE = [25, 50, 100, 200]
    try:
        per_page = int(request.GET.get('per_page', 50))
        if per_page not in ALLOWED_PER_PAGE:
            per_page = 50
    except (ValueError, TypeError):
        per_page = 50

    if search:
        employees = employees.filter(
            Q(full_name__icontains=search) | Q(employee_number__icontains=search)
        )
    if position:
        employees = employees.filter(position__name__icontains=position)
    if category_id:
        employees = employees.filter(employee_category_id=category_id)
    if production_id:
        employees = employees.filter(production_id=production_id)
    if workshop_id:
        employees = employees.filter(workshop_id=workshop_id)
    if status == 'active':
        employees = employees.filter(dismissal_date__isnull=True)
    elif status == 'dismissed':
        employees = employees.filter(dismissal_date__isnull=False)

    employees = employees.order_by('full_name')
    total_count = employees.count()

    paginator = Paginator(employees, per_page)
    page_obj  = paginator.get_page(request.GET.get('page'))

    return {
        'page_obj':            page_obj,
        'total_count':         total_count,
        'productions':         Production.objects.all(),
        'workshops':           Workshop.objects.all(),
        'search':              search,
        'position':            position,
        'employee_categories': EmployeeCategory.objects.all(),
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
        'selected_status':     status,
        'per_page':            per_page,
        'per_page_options':    ALLOWED_PER_PAGE,
    }

@can_view
def employee_list(request):
    context = _build_employee_queryset_and_context(request)

    if request.headers.get('HX-Request'):
        return render(request, 'core/employee/partials/employee_table.html', context)

    return render(request, 'core/employee/employee_list.html', context)

def _parse_int_or_none(value: str):
    """Возвращает int если строка — корректное целое, иначе None."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

@can_view
def employee_list_extended(request):
    """
    Расширенный список сотрудников - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ
    """
    from django.db.models import F, Case, When
    from django.db.models.functions import Now
    from datetime import date, timedelta

    # Получаем параметры фильтрации
    search        = request.GET.get('search', '').strip()
    position      = request.GET.get('position', '').strip()
    category_id   = request.GET.get('category', '')
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    status        = request.GET.get('status', '')
    gender        = request.GET.get('gender', '').strip()
    age_from      = _parse_int_or_none(request.GET.get('age_from'))
    age_to        = _parse_int_or_none(request.GET.get('age_to'))
    tenure_from   = _parse_int_or_none(request.GET.get('tenure_from'))
    tenure_to     = _parse_int_or_none(request.GET.get('tenure_to'))
    
    # Строим базовый queryset
    employees = Employee.objects.select_related(
        'production',
        'workshop',
        'dismissal_reason',
        'employee_category',
        'position'
    )
    
    # Применяем базовые фильтры
    if search:
        employees = employees.filter(
            Q(full_name__icontains=search) | Q(employee_number__icontains=search)
        )
    if position:
        employees = employees.filter(position__name__icontains=position)
    if category_id:
        employees = employees.filter(employee_category_id=category_id)
    if production_id:
        employees = employees.filter(production_id=production_id)
    if workshop_id:
        employees = employees.filter(workshop_id=workshop_id)
    if status == 'active':
        employees = employees.filter(dismissal_date__isnull=True)
    elif status == 'dismissed':
        employees = employees.filter(dismissal_date__isnull=False)
    if gender:
        employees = employees.filter(gender=gender)
    
    # Фильтрация по возрасту (работает через дату рождения)
    today = date.today()
    
    if age_from is not None:
        max_birth_date = date(today.year - age_from, today.month, today.day)
        employees = employees.filter(birth_date__lte=max_birth_date)
    
    if age_to is not None:
        min_birth_date = date(today.year - age_to - 1, today.month, today.day)
        employees = employees.filter(birth_date__gte=min_birth_date)
    
    # Фильтрация по стажу (с учетом даты увольнения)
    if tenure_from is not None or tenure_to is not None:
        # Используем аннотацию для вычисления стажа в днях
        from django.db.models import DurationField
        
        # Вычисляем стаж в днях
        tenure_expr = ExpressionWrapper(
            Case(
                # Для уволенных: dismissal_date - hire_date
                When(dismissal_date__isnull=False, 
                     then=F('dismissal_date') - F('hire_date')),
                # Для работающих: сегодня - hire_date
                default=Now() - F('hire_date'),
                output_field=DurationField()
            ),
            output_field=DurationField()
        )
        
        employees = employees.annotate(tenure_days=tenure_expr)
        
        # Фильтруем по стажу в годах
        if tenure_from is not None:
            min_days = tenure_from * 365
            employees = employees.filter(tenure_days__gte=timedelta(days=min_days))
        
        if tenure_to is not None:
            max_days = (tenure_to + 1) * 365  # +1 для корректного "до"
            employees = employees.filter(tenure_days__lte=timedelta(days=max_days))
    
    # Сортируем
    employees = employees.order_by('full_name')
    
    # Общее количество
    total_count = employees.count()
    
    # Пагинация
    ALLOWED_PER_PAGE = [25, 50, 100, 200]
    try:
        per_page = int(request.GET.get('per_page', 50))
        if per_page not in ALLOWED_PER_PAGE:
            per_page = 50
    except (ValueError, TypeError):
        per_page = 50
    
    paginator = Paginator(employees, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # Добавляем вычисляемые поля для отображения в шаблоне
    for emp in page_obj:
        # Вычисляем возраст
        if emp.birth_date:
            age = today.year - emp.birth_date.year
            if (today.month, today.day) < (emp.birth_date.month, emp.birth_date.day):
                age -= 1
            emp.age_years = age
        else:
            emp.age_years = None
        
        # Вычисляем стаж в годах
        if emp.hire_date:
            end_date = emp.dismissal_date if emp.dismissal_date else today
            tenure_days = (end_date - emp.hire_date).days
            emp.tenure_years = int(tenure_days / 365.25)
        else:
            emp.tenure_years = None
    
    # Получаем списки для фильтров (с кэшированием)
    from django.core.cache import cache
    
    cache_key_productions = 'productions_list'
    cache_key_workshops = 'workshops_list'
    cache_key_categories = 'categories_list'
    
    productions = cache.get(cache_key_productions)
    if productions is None:
        productions = Production.objects.all()
        cache.set(cache_key_productions, productions, 3600)
    
    workshops = cache.get(cache_key_workshops)
    if workshops is None:
        workshops = Workshop.objects.all()
        cache.set(cache_key_workshops, workshops, 3600)
    
    employee_categories = cache.get(cache_key_categories)
    if employee_categories is None:
        employee_categories = EmployeeCategory.objects.all()
        cache.set(cache_key_categories, employee_categories, 3600)
    
    # Формируем контекст
    context = {
        'page_obj':            page_obj,
        'total_count':         total_count,
        'productions':         productions,
        'workshops':           workshops,
        'search':              search,
        'position':            position,
        'employee_categories': employee_categories,
        'selected_category':   category_id,
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
        'selected_status':     status,
        'per_page':            per_page,
        'per_page_options':    ALLOWED_PER_PAGE,
        'gender':              gender,
        'age_from':            age_from,
        'age_to':              age_to,
        'tenure_from':         tenure_from,
        'tenure_to':           tenure_to,
    }
    
    if request.headers.get('HX-Request'):
        return render(request, 'core/employee/partials/employee_table_extended.html', context)
    return render(request, 'core/employee/employee_list_extended.html', context)

@can_view
def export_employees_excel(request):
    """
    Экспорт сотрудников в Excel с учетом текущих фильтров
    """
    from datetime import date, timedelta
    from django.db.models import F, Case, When
    from django.db.models.functions import Now

    # Получаем все параметры фильтрации (как в employee_list_extended)
    search        = request.GET.get('search', '').strip()
    position      = request.GET.get('position', '').strip()
    category_id   = request.GET.get('category', '')
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    status        = request.GET.get('status', '')
    gender        = request.GET.get('gender', '').strip()
    age_from      = _parse_int_or_none(request.GET.get('age_from'))
    age_to        = _parse_int_or_none(request.GET.get('age_to'))
    tenure_from   = _parse_int_or_none(request.GET.get('tenure_from'))
    tenure_to     = _parse_int_or_none(request.GET.get('tenure_to'))
    
    # Строим queryset с теми же фильтрами
    employees = Employee.objects.select_related(
        'production',
        'workshop',
        'dismissal_reason',
        'employee_category',
        'position'
    )
    
    # Применяем фильтры (полностью копируем логику из employee_list_extended)
    if search:
        employees = employees.filter(
            Q(full_name__icontains=search) | Q(employee_number__icontains=search)
        )
    if position:
        employees = employees.filter(position__name__icontains=position)
    if category_id:
        employees = employees.filter(employee_category_id=category_id)
    if production_id:
        employees = employees.filter(production_id=production_id)
    if workshop_id:
        employees = employees.filter(workshop_id=workshop_id)
    if status == 'active':
        employees = employees.filter(dismissal_date__isnull=True)
    elif status == 'dismissed':
        employees = employees.filter(dismissal_date__isnull=False)
    if gender:
        employees = employees.filter(gender=gender)
    
    # Фильтр по возрасту
    today = date.today()
    if age_from is not None:
        max_birth_date = date(today.year - age_from, today.month, today.day)
        employees = employees.filter(birth_date__lte=max_birth_date)
    if age_to is not None:
        min_birth_date = date(today.year - age_to - 1, today.month, today.day)
        employees = employees.filter(birth_date__gte=min_birth_date)

    # Фильтрация по стажу (с учетом даты увольнения)
    if tenure_from is not None or tenure_to is not None:
        # Используем аннотацию для вычисления стажа в днях
        from django.db.models import DurationField
        
        # Вычисляем стаж в днях
        tenure_expr = ExpressionWrapper(
            Case(
                # Для уволенных: dismissal_date - hire_date
                When(dismissal_date__isnull=False, 
                     then=F('dismissal_date') - F('hire_date')),
                # Для работающих: сегодня - hire_date
                default=Now() - F('hire_date'),
                output_field=DurationField()
            ),
            output_field=DurationField()
        )
        
        employees = employees.annotate(tenure_days=tenure_expr)
        
        # Фильтруем по стажу в годах
        if tenure_from is not None:
            min_days = tenure_from * 365
            employees = employees.filter(tenure_days__gte=timedelta(days=min_days))
        
        if tenure_to is not None:
            max_days = (tenure_to + 1) * 365  # +1 для корректного "до"
            employees = employees.filter(tenure_days__lte=timedelta(days=max_days))
    
    # Получаем все записи (без пагинации)
    employees = employees.order_by('full_name')
    
    # Создаем workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сотрудники"
    
    # Стили
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="E07B2A", end_color="E07B2A", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Заголовки
    headers = [
        "Табельный номер", "ФИО", "Пол", "Дата рождения", "Возраст",
        "Дата приема", "Стаж (лет)", "Дата увольнения", "Производство",
        "Цех", "Должность", "Категория", "Статус",
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = border
    
    # Заполняем данные
    for row_idx, emp in enumerate(employees.iterator(), 2):
        # Вычисляем возраст
        age = emp.age
        # if emp.birth_date:
        #     age = today.year - emp.birth_date.year
        #     if (today.month, today.day) < (emp.birth_date.month, emp.birth_date.day):
        #         age -= 1
        
        # Вычисляем стаж
        tenure = emp.expirence
        # if emp.hire_date:
        #     end_date = emp.dismissal_date if emp.dismissal_date else today
        #     tenure_days = (end_date - emp.hire_date).days
        #     tenure = round(tenure_days / 365.25, 1)
        
        # Статус
        status_text = "Уволен" if emp.dismissal_date else "Работает"
        
        # Заполняем строку
        row_data = [
            emp.employee_number,
            emp.full_name,
            emp.gender or "",
            emp.birth_date.strftime("%d.%m.%Y") if emp.birth_date else "",
            age,
            emp.hire_date.strftime("%d.%m.%Y") if emp.hire_date else "",
            tenure,
            emp.dismissal_date.strftime("%d.%m.%Y") if emp.dismissal_date else "",
            emp.production.name if emp.production else "",
            emp.workshop.number if emp.workshop else "",
            emp.position.name if emp.position else "",
            emp.employee_category.name if emp.employee_category else "",
            status_text,
        ]
        
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = border
            cell.alignment = Alignment(horizontal="left", vertical="center")
            
            # Для числовых столбцов - выравнивание по центру
            if col_idx in [1, 4, 5, 6, 7]:  # таб.номер, даты, возраст, стаж
                cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Автоматическая ширина столбцов
    for col_idx, header in enumerate(headers, 1):
        max_length = len(header)
        column_letter = get_column_letter(col_idx)
        
        for row_idx in range(2, ws.max_row + 1):
            cell_value = ws.cell(row=row_idx, column=col_idx).value
            if cell_value:
                max_length = max(max_length, len(str(cell_value)))
        
        adjusted_width = min(max_length + 2, 30)
        ws.column_dimensions[column_letter].width = adjusted_width
    
    # Замораживаем заголовок
    ws.freeze_panes = 'A2'
    
    # Формируем имя файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"employees_{timestamp}.xlsx"
    
    # Создаем HTTP ответ
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response

@can_view
def employee_detail(request, employee_number):
    """
    Карточка сотрудника — только просмотр, без возможности изменений
    Точка входа перед редактированием: список → карточка → редактирование
    """
    employee = get_object_or_404(
        Employee.objects.select_related(
            'production', 'workshop', 'position',
            'employee_category', 'dismissal_reason'
        ),
        employee_number=employee_number
    )

    return render(request, 'core/employee/employee_detail.html', {
        'employee': employee,
    })

@can_view_additional_info
def employee_transfers(request, employee_number):
    data = EmployeeTransfers.objects.filter(
        employee__employee_number=employee_number,
    ).order_by('transfer_date')

    return render(request, 'core/employee/employee_transfers.html', {'data': data, 'employee_number': employee_number})

@can_view_additional_info
def employee_salary(request, employee_number):
    from datetime import date

    employee = get_object_or_404(Employee, employee_number=employee_number)
    
    # Все года, по которым у сотрудника есть данные
    available_years = (
        Salary.objects
        .filter(employee=employee)
        .values_list('salary_date__year', flat=True)
        .distinct()
    )
    available_years = sorted(set(available_years), reverse=True)

    # Выбранный год берется или 1) из GET-запроса или 2) самый новый из имеющихся или 3) текущий
    try:
        selected_year = int(request.GET.get('year', ''))
    except (ValueError, TypeError):
        selected_year = available_years[0] if available_years else date.today().year
    
    # Записи за выбранный год
    rows = list(
        Salary.objects
        .filter(employee=employee, salary_date__year=selected_year)
        .order_by('salary_date')
    )

    # Первый месяц сравниваем с последним месяцем прошого года
    prev_december = (
        Salary.objects
        .filter(employee=employee, salary_date__year=selected_year - 1, salary_date__month=12)
        .first()
    )

    # Считаем статус, сравнивая с концом прошлого года и собираем список по строкам
    prev_sum = prev_december.main_sum if prev_december else None
    table_rows = []
    for row in rows:
        if prev_sum is None:
            status = None
        elif row.main_sum > prev_sum:
            status = 'up'
        elif row.main_sum < prev_sum:
            status = 'down'
        else:
            status = 'equal'

        table_rows.append({
            'salary_date': row.salary_date,
            'hours': row.hours,
            'main_sum': row.main_sum,
            'vacation_sum': row.vacation_sum,
            'total_sum': row.main_sum + row.vacation_sum,
            'status': status,
        })
        prev_sum = row.main_sum

    return render(request, 'core/employee/employee_salary.html', {
        'employee': employee,
        'available_years': available_years,
        'selected_year': selected_year,
        'table_rows': table_rows,
    })

@can_view_additional_info
def salary_list(request):
    """Страница зарплаты со списком сотрудников"""
    context = _build_employee_queryset_and_context(request)
    if request.headers.get('HX-Request'):
        return render(request, 'core/salary/partials/salary_employee_table.html', context)
    return render(request, 'core/salary/salary_list.html', context)

@can_view_additional_info
def salary_modal_data(request, employee_number):
    """HTMX-запрос данных зарплаты для модального окна"""
    from datetime import date
    employee = get_object_or_404(Employee, employee_number=employee_number)

    # Все года, по которым у сотрудника есть данные
    available_years = (
        Salary.objects
        .filter(employee=employee)
        .values_list('salary_date__year', flat=True)
        .distinct()
    )
    available_years = sorted(set(available_years), reverse=True)

    # Выбранный год берется или 1) из GET-запроса или 2) самый новый из имеющихся или 3) текущий
    try:
        selected_year = int(request.GET.get('year', ''))
    except (ValueError, TypeError):
        selected_year = available_years[0] if available_years else date.today().year
    
    # Записи за выбранный год
    rows = list(
        Salary.objects
        .filter(employee=employee, salary_date__year=selected_year)
        .order_by('salary_date')
    )

    # Первый месяц сравниваем с последним месяцем прошого года
    prev_december = (
        Salary.objects
        .filter(employee=employee, salary_date__year=selected_year - 1, salary_date__month=12)
        .first()
    )

    # Считаем статус, сравнивая с концом прошлого года и собираем список по строкам
    prev_sum = prev_december.main_sum if prev_december else None
    table_rows = []
    for row in rows:
        if prev_sum is None:
            status = None
        elif row.main_sum > prev_sum:
            status = 'up'
        elif row.main_sum < prev_sum:
            status = 'down'
        else:
            status = 'equal'

        table_rows.append({
            'salary_date':  row.salary_date,
            'hours':        row.hours,
            'main_sum':     row.main_sum,
            'vacation_sum': row.vacation_sum,
            'total_sum':    row.main_sum + row.vacation_sum,
            'status':       status,
        })
        prev_sum = row.main_sum

    return render(request, 'core/salary/partials/salary_modal_body.html', {
        'employee':         employee,
        'available_years':  available_years,
        'selected_year':    selected_year,
        'table_rows':       table_rows,
    })

@can_edit
def employee_edit(request, employee_number):
    employee = get_object_or_404(Employee, employee_number=employee_number)

    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, f"Сотрудник {employee.full_name} обновлён")
            # После сохранения возвращаемся на карточку, а не в общий список
            return redirect('core:employee_detail', employee_number=employee.employee_number)
        else:
            messages.error(request, "Проверьте правильность заполнения формы")
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, 'core/employee/employee_edit.html', {
        'form': form,
        'employee': employee,
    })

@can_edit
def employee_delete(request, employee_number):
    employee = get_object_or_404(Employee, employee_number=employee_number)

    if request.method == 'POST':
        full_name = employee.full_name
        employee.delete()
        messages.success(request, f"Сотрудник {full_name} удалён")
        return redirect('core:employee_list')

    return render(request, 'core/employee/employee_confirm_delete.html', {'employee': employee})


# ==========
#  Отчёты
# ==========

@can_view
def report_headcount(request):
    """Отчёт «Численность» — срез на текущий момент."""
    from core.services.report_service import get_headcount_report, get_movement_report

    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '') 

    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None

    data = get_headcount_report(production_id=prod_id, workshop_id=ws_id)
    headcount = get_movement_report()['work_atm']

    return render(request, 'core/reports/headcount.html', {
        'data':                data,
        'productions':         Production.objects.all(),
        'workshops':           Workshop.objects.all(),
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
        'headcount':           headcount,
    })

@can_view
def report_headcount_export(request):
    """Экспорт отчёта «Численность» в Excel — без стилей, только данные."""
    from core.services.report_service import get_headcount_report

    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None

    data = get_headcount_report(production_id=prod_id, workshop_id=ws_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Численность'

    # Заголовок
    ws.append(['Производство', 'Цех', 'Всего'] + data['categories'])

    for prod in data['by_production']:
        for workshop in prod['workshops']:
            row = [prod['name'], f"Цех {workshop.number}", workshop.total]
            row += [workshop.cat_values.get(cat, 0) for cat in data['categories']]
            ws.append(row)
        row = [f"Итого {prod['name']}", '', prod['total']]
        row += [prod['categories'].get(cat, 0) for cat in data['categories']]
        ws.append(row)

    row = ['ИТОГО', '', data['grand_total']]
    row += [data['grand_categories'].get(cat, 0) for cat in data['categories']]
    ws.append(row)

    # Оформление
    _style_excel_sheet(ws)
    _style_total_row(ws, ws.max_row)
    # Строки промежуточных итогов по производствам
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row - 1):
        if row[0].value and str(row[0].value).startswith('Итого'):
            _style_total_row(ws, row[0].row)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    from datetime import date as _date
    from urllib.parse import quote
    today = _date.today()
    filename = f"Численность_на_{today.strftime('%d.%m.%y')}.xlsx"
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    wb.save(response)
    return response

@can_view
def report_movement(request):
    """Отчёт «Движение персонала» — динамика за год."""
    from core.services.report_service import get_movement_report
    from datetime import date as _date

    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    year_param    = request.GET.get('year', '')

    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None
    year    = int(year_param)    if year_param    else _date.today().year

    data = get_movement_report(production_id=prod_id, workshop_id=ws_id, year=year)

    return render(request, 'core/reports/movement.html', {
        'data':                data,
        'productions':         Production.objects.all(),
        'workshops':           Workshop.objects.all(),
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
        'selected_year':       str(year),
    })

@can_view
def report_movement_export(request):
    """Экспорт отчёта «Движение персонала» в Excel — без стилей, только данные."""
    from core.services.report_service import get_movement_report
    from datetime import date as _date

    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    year_param    = request.GET.get('year', '')
    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None
    year    = int(year_param)    if year_param    else _date.today().year

    data = get_movement_report(production_id=prod_id, workshop_id=ws_id, year=year)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # Лист 1: помесячная динамика
    ws1 = wb.create_sheet('Динамика по месяцам')
    ws1.append([f'Отчёт за {year} год'])
    ws1.append([])
    ws1.append(['Месяц', 'Принято', 'Уволено', 'Разница', 'Численность на конец'])
    for row in data['monthly_rows']:
        ws1.append([row['month'], row['hired'], row['dismissed'], row['diff'], row['headcount']])
    ws1.append(['ИТОГО', data['total_hired'], data['total_dismissed'], data['total_diff'], ''])

    # Лист 2: текучесть по цехам
    ws2 = wb.create_sheet('Текучесть по цехам')
    ws2.append([f'Отчёт за {year} год'])
    ws2.append([])
    ws2.append(['Производство', 'Цех', 'Среднесписочная', 'Принято', 'Уволено', 'Разница', 'Текучесть %'])
    for ws in data['workshop_rows']:
        ws2.append([
            ws.production.name if ws.production else '—',
            f"Цех {ws.number}",
            ws.avg_count,
            ws.hired,
            ws.dismissed,
            ws.diff,
            ws.turnover_rate,
        ])

    # Лист 3: причины увольнений
    ws3 = wb.create_sheet('Причины увольнений')
    ws3.append([f'Отчёт за {year} год'])
    ws3.append([])
    ws3.append(['Причина', 'Кол-во', '%'])
    for r in data['reasons_total']:
        ws3.append([r['dismissal_reason__name'], r['count'], r['pct']])

    # Лист 4: матрица цех × причина
    if data['matrix_rows']:
        ws4 = wb.create_sheet('Причины по цехам')
        ws4.append([f'Отчёт за {year} год'])
        ws4.append([])
        header = ['Цех', 'Производство'] + data['reason_order'] + ['Итого']
        ws4.append(header)
        for row in data['matrix_rows']:
            line = [f"Цех {row['workshop']}", row['production']]
            line += [row['reasons'].get(r, 0) for r in data['reason_order']]
            line += [row['total']]
            ws4.append(line)

    # Оформление всех листов
    for sheet in wb.worksheets:
        _style_excel_sheet(sheet)
        # Строка ИТОГО — последняя на листах 1-3
        if sheet.title in ('Динамика по месяцам', 'Причины увольнений'):
            _style_total_row(sheet, sheet.max_row)
            
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    from datetime import date as _date
    from urllib.parse import quote
    today = _date.today()
    filename = f"Движение_персонала_на_{today.strftime('%d.%m.%y')}_за_{year}.xlsx"
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    wb.save(response)
    return response

@login_required_custom
def profile_view(request):
    """
    Страница профиля пользователя.
    Показывает данные учётной записи и форму смены пароля.
    При успешной смене пароля пользователь остаётся залогинен.
    """
    from django.contrib.auth import update_session_auth_hash
    from core.models import UserProfile
 
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
 
    error = None
 
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password     = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
 
        if not user.check_password(current_password):
            error = 'Неверный текущий пароль'
        elif new_password != confirm_password:
            error = 'Новые пароли не совпадают'
        elif len(new_password) < 8:
            error = 'Пароль должен содержать не менее 8 символов'
        elif new_password.isdigit():
            error = 'Пароль не должен состоять только из цифр'
        elif user.check_password(new_password):
            error = 'Новый пароль не должен совпадать с текущим'
        else:
            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Пароль успешно изменён')
            return redirect('core:profile')
 
    return render(request, 'core/profile.html', {
        'profile': profile,
        'error':   error,
    })

@can_view
def dashboard(request):
    """Дашборд — сводная аналитика по персоналу."""
    from core.services.report_service import get_headcount_report, get_movement_report
    from datetime import date as _date
    from collections import OrderedDict
    import json

    year_param = request.GET.get('year', '')
    year = int(year_param) if year_param else _date.today().year

    headcount = get_headcount_report()
    movement = get_movement_report(year=year)

    # Общий коэффициент текучести = уволено / среднесписочная * 100
    avg_headcount = headcount['grand_total']
    turnover_rate = round(movement['total_dismissed'] / avg_headcount * 100, 1) if avg_headcount else 0

    # Топ-5 цехов по текучести (для таблицы внизу)
    top_workshops = sorted(
        movement['workshop_rows'],
        key=lambda ws: ws.turnover_rate,
        reverse=True
    )[:10]

    # Топ 5 причин увольнений (общее для диаграммы и легенды)
    all_reasons = movement['reasons_total']
    top_reasons = list(all_reasons[:5])
    other_count = sum(r['count'] for r in all_reasons[5:])
    if other_count:
        top_reasons.append({
            'dismissal_reason__name': 'Прочие причины',
            'count': other_count,
        })
    top_reasons_names = [r['dismissal_reason__name'] for r in top_reasons]

    # Численность по производствам - основных производств + прочее
    MAIN_PRODUCTIONS = [
        'Вагоносборочное производство',
        'Инструментальное производство',
        'Механосборочное производство',
        'Металлургическое производство',
        'Энергетическое пр-во',
    ]
    CHART_CATEGORIES = ['Вспомогательные', 'Основные', 'РСС']

    by_name = {p['name']: p for p in headcount['by_production']}
    chart_productions = []
    for name in MAIN_PRODUCTIONS:
        p = by_name.get(name)
        cats = {c: (p['categories'].get(c, 0) if p else 0) for c in CHART_CATEGORIES}
        chart_productions.append({
            'name':         name,
            'total':        sum(cats.values()),
            'categories':   cats,
        })
    
    other_cats = {c: 0 for c in CHART_CATEGORIES}
    for p in headcount['by_production']:
        if p['name'] in MAIN_PRODUCTIONS:
            continue
        for c in CHART_CATEGORIES:
            other_cats[c] += p['categories'].get(c, 0)
    chart_productions.append({
        'name':         'Прочие производства',
        'total':        sum(other_cats.values()),
        'categories':   other_cats,
    })

    chart_headcount_json = json.dumps({
        'categories': CHART_CATEGORIES,
        'productions': chart_productions,
    }, ensure_ascii=False)

    categories_json = json.dumps(headcount['categories'], ensure_ascii=False)

    return render(request, 'core/reports/dashboard.html', {
        'headcount':            headcount,
        'movement':             movement,
        'turnover_rate':        turnover_rate,
        'top_workshops':        top_workshops,
        'top_reasons':          top_reasons,
        'top_reasons_names':    top_reasons_names,
        'available_years':      movement['available_years'],
        'selected_year':        str(year),
        'categories_json':      categories_json,
        'chart_headcount_json': chart_headcount_json,
        'transfers_count':      movement['transfers_count'],
    })

@can_view
def dashboard_details(request, details_type):
    from core.services.report_service import get_dashboard_details_report
    from datetime import date, datetime, timedelta

    dtype = details_type
    ddate=request.GET.get('ddate', '')

    if ddate == '':
        ddate = date.today() - timedelta(days=1)
    else:
        ddate = datetime.strptime(ddate, '%Y-%m-%d').date()

    data = get_dashboard_details_report(details_type=dtype, details_date=ddate)
    return render(request, 'core/reports/dashboard_details.html', {'data': data, 'ddate': ddate})

@can_view
def dashboard_reason_details(request, action, period, employee_type, details_date, reason_id=None): 
    from core.services.report_service import get_dashboard_reason_details
    from datetime import date, datetime

    r_id = reason_id

    data = get_dashboard_reason_details(reason_id=r_id, action=action, period=period, employee_type=employee_type, details_date=datetime.strptime(details_date, '%Y-%m-%d').date())

    paginator = Paginator(data['reason_details'], 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'core/reports/reason_details.html', {'data': data, 'page_obj': page_obj})

@can_view
def currently_working(request):
    from core.services.report_service import get_dashboard_details_report

    month_num = datetime.now().month - 1

    data = get_dashboard_details_report(details_type=2)
    month_diff = get_movement_report()['monthly_rows'][month_num]['diff']
    year_diff = get_movement_report()['total_diff']

    return render(request, 'core/reports/currently_working.html', {'data': data, 'total_diff': year_diff, 'month_diff': month_diff})

@can_view
def daily_report(request, report_date=None):
    from core.services.report_service import get_daily_report
    from datetime import datetime

    ddate = request.GET.get('ddate', '')
    if ddate == '':
        ddate = None
    else:
        ddate = datetime.strptime(ddate, '%Y-%m-%d').date()

    data = get_daily_report(ddate)

    return render(request, 'core/reports/daily_report.html', {'data': data})

@can_view
def categories_details(request, emp_category):
    if emp_category in {'Вспомогательные', 'Основные', 'РСС'}:
        data = Employee.objects.filter(
            hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            dismissal_date__isnull=True, 
            employee_category__name=emp_category
        )
    elif emp_category == 'Ученики':
        data = Employee.objects.filter(
            dismissal_date__isnull=True,
            employee_category__name=emp_category
        ).exclude(
            hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
        )
    else: 
        data = Employee.objects.filter(dismissal_date__isnull=True, employee_category__name=emp_category)
    
    paginator = Paginator(data, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'core/reports/cats_details.html', {'data': page_obj, 'cat_name': emp_category})

@can_view
def transfers_details(request):
    from datetime import date, datetime, timedelta

    ddate=request.GET.get('ddate', '')

    if ddate == '':
        ddate = date.today() - timedelta(days=1)
    else:
        ddate = datetime.strptime(ddate, '%Y-%m-%d').date()

    if ddate.weekday() == 5:
        ddate -= timedelta(days=1)
    elif ddate.weekday() == 6:
        ddate -= timedelta(days=2)

    transfers_data = EmployeeTransfers.objects.filter(
        transfer_date=ddate,
    ).values(
        'employee__employee_number',
        'employee__full_name',
        'transfer_date',
        'order_number',
        'from_workshop__number',
        'from_position__name',
        'from_grade__name',
        'to_workshop__number',
        'to_position__name',
        'to_grade__name',
    ).order_by('employee__employee_number')

    paginator = Paginator(transfers_data, 20)
    page_number = request.GET.get('page', 1)
    tdata = paginator.get_page(page_number)

    data = {
        'details_date':     ddate,
        'tdata':   tdata,
    }

    return render(request, 'core/reports/transfers_details.html', {'data': data})

def report_table(request):
    from core.services.report_service import get_table_report
    from datetime import date, timedelta, datetime

    ddate=request.GET.get('ddate', '')
    if ddate == '':
        ddate = None
    else:
        ddate = datetime.strptime(ddate, '%Y-%m-%d').date() 

    data = get_table_report(ddate)   
    return render(request, 'core/reports/report_table.html', {'data': data})