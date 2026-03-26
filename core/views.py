import json
 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
 
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
 
from .forms import FileUploadForm, EmployeeEditForm
from .permissions import can_upload, can_edit, can_view
from core.services.file_processor import EmployeeFileProcessor
from core.services.report_service import get_headcount_report
from .models import Employee, Production, Workshop

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
      Суперпользователь        → core:report_headcount
      Администратор            → core:report_headcount
      Директор по персоналу   → core:report_headcount
      Редактор                 → core:upload_file
      Просмотр                 → core:report_headcount
      Без группы               → core:report_headcount
    """
    if user.is_superuser:
        return redirect('core:report_headcount')
 
    group_names = set(user.groups.values_list('name', flat=True))
 
    if 'Администратор' in group_names:
        return redirect('core:report_headcount')
 
    if 'Редактор' in group_names:
        return redirect('core:upload_file')
 
    # Директор по персоналу, Просмотр, без группы — на отчёты
    return redirect('core:report_headcount')


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
    if request.method == 'POST':
        # Создаём форму с данными
        form = FileUploadForm(request.POST, request.FILES)

        if form.is_valid():
            # Получаем очищенные данные
            uploaded_file = request.FILES['file']
            try:
                # Создаём обработчик и обрабатываем файл
                processor = EmployeeFileProcessor(uploaded_file)
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
                    request.session['upload_errors'] = result['errors'][:100]

                return redirect('core:upload_file')
            except Exception as e:
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
        'required_columns': ['ФИО', 'Табельный номер', 'Дата приема на работу'],
        'optional_columns': [
            'Дата рождения', 'Дата увольнения', 'Производство',
            'Цех', 'Причина увольнения', 'Категория рабочего', 'Должность'
        ],
    })


@can_view
def employee_list(request):
    """
    Просмотр списка всех сотрудников

    Args:
        request: HTTP запрос

    Returns:
        render: Шаблон со списком сотрудников
    """
    employees = Employee.objects.select_related(
        'production',
        'workshop',
        'dismissal_reason',
        'employee_category',
        'position'
    )

    search        = request.GET.get('search', '').strip()
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    status        = request.GET.get('status', '')

    # Количество строк на странице — допустимые значения фиксированы во избежание злоупотреблений
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
    if production_id:
        employees = employees.filter(production_id=production_id)
    if workshop_id:
        employees = employees.filter(workshop_id=workshop_id)
    if status == 'active':
        employees = employees.filter(dismissal_date__isnull=True)
    elif status == 'dismissed':
        employees = employees.filter(dismissal_date__isnull=False)

    employees = employees.order_by('full_name')

    # Считаем до пагинации, чтобы total_count всегда отражал результат фильтрации
    total_count = employees.count()

    paginator = Paginator(employees, per_page)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':           page_obj,
        'total_count':        total_count,
        'productions':        Production.objects.all(),
        'workshops':          Workshop.objects.all(),
        'search':             search,
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
        'selected_status':     status,
        'per_page':            per_page,
        'per_page_options':    ALLOWED_PER_PAGE,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'core/employee/partials/employee_table.html', context)

    return render(request, 'core/employee/employee_list.html', context)


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


# ---------
#  Отчёты
# ---------

@can_view
def report_headcount(request):
    """
    Отчёт «Численность по подразделениям»
    Поддерживает фильтрацию по производству и цеху
    """
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')

    # Приводим к int или None — сервис ожидает int|None
    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None

    data = get_headcount_report(production_id=prod_id, workshop_id=ws_id)

    # Данные для Chart.js — сериализуем здесь, чтобы шаблон оставался чистым
    charts = {
        # Пончик: активные vs уволенные
        'status': {
            'labels': ['Работают', 'Уволены'],
            'values': [data['total_active'], data['total_dismissed']],
        },
        # Горизонтальный стэкированный бар: топ-10 производств
        'production': {
            'labels':    [p.name for p in data['by_production'][:10]],
            'active':    [p.active    for p in data['by_production'][:10]],
            'dismissed': [p.dismissed for p in data['by_production'][:10]],
        },
        # Горизонтальный стэкированный бар: топ-10 должностей
        'position': {
            'labels':    [p.name for p in data['by_position'][:10]],
            'active':    [p.active    for p in data['by_position'][:10]],
            'dismissed': [p.dismissed for p in data['by_position'][:10]],
        },
        # Пончик: по категориям работников
        'category': {
            'labels': [c.name  for c in data['by_category']],
            'values': [c.total for c in data['by_category']],
        },
    }

    return render(request, 'core/reports/headcount.html', {
        'data':                data,
        'charts_json':         json.dumps(charts, ensure_ascii=False),
        'productions':         Production.objects.all(),
        'workshops':           Workshop.objects.all(),
        'selected_production': production_id,
        'selected_workshop':   workshop_id,
    })


@can_view
def report_headcount_export(request):
    """
    Экспорт отчёта «Численность по подразделениям» в Excel
    Создаёт многолистовую книгу: по одному листу на каждый срез данных
    """
    production_id = request.GET.get('production', '')
    workshop_id   = request.GET.get('workshop', '')
    prod_id = int(production_id) if production_id else None
    ws_id   = int(workshop_id)   if workshop_id   else None

    data = get_headcount_report(production_id=prod_id, workshop_id=ws_id)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Убираем дефолтный пустой лист

    # Стили 
    header_font    = Font(bold=True, color='FFFFFF', size=11, name='Arial')
    data_font      = Font(size=11, name='Arial')
    bold_font      = Font(bold=True, size=11, name='Arial')
    header_fill    = PatternFill('solid', start_color='1E2535')
    title_fill     = PatternFill('solid', start_color='3B82F6')
    footer_fill    = PatternFill('solid', start_color='252D3D')
    alt_fill       = PatternFill('solid', start_color='1A2030')
    center         = Alignment(horizontal='center', vertical='center')
    left           = Alignment(horizontal='left',   vertical='center')
    thin           = Side(style='thin', color='2D3748')
    border         = Border(bottom=thin, right=thin, left=thin, top=thin)

    def add_sheet(title, headers, rows_data):
        """Создаёт лист с заголовком, шапкой, данными и строкой итогов"""
        ws = wb.create_sheet(title=title)

        # Заголовок листа (строка 1, объединённые ячейки)
        last_col = get_column_letter(len(headers))
        ws.merge_cells(f'A1:{last_col}1')
        ws['A1'] = title
        ws['A1'].font      = Font(bold=True, size=14, color='FFFFFF', name='Arial')
        ws['A1'].fill      = title_fill
        ws['A1'].alignment = center
        ws.row_dimensions[1].height = 30

        # Шапка таблицы (строка 2)
        for col, h in enumerate(headers, start=1):
            cell            = ws.cell(row=2, column=col, value=h)
            cell.font       = header_font
            cell.fill       = header_fill
            cell.alignment  = center
            cell.border     = border
        ws.row_dimensions[2].height = 22

        # Данные (строки 3+)
        for r_idx, row in enumerate(rows_data, start=3):
            for c_idx, val in enumerate(row, start=1):
                cell           = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.font      = data_font
                cell.alignment = left if c_idx == 1 else center
                cell.border    = border
                # Чередование фона строк для читабельности
                if r_idx % 2 == 0:
                    cell.fill = alt_fill

        last_data_row = 2 + len(rows_data)

        # Строка итогов (формулы Excel)
        foot_row = last_data_row + 1
        ws.cell(row=foot_row, column=1, value='Итого').font = bold_font
        ws.cell(row=foot_row, column=1).fill      = footer_fill
        ws.cell(row=foot_row, column=1).alignment = left
        ws.cell(row=foot_row, column=1).border    = border
        for col in range(2, len(headers) + 1):
            cl   = get_column_letter(col)
            cell = ws.cell(row=foot_row, column=col,
                           value=f'=SUM({cl}3:{cl}{last_data_row})')
            cell.font      = bold_font
            cell.fill      = footer_fill
            cell.alignment = center
            cell.border    = border

        # Ширина колонок
        ws.column_dimensions['A'].width = 38
        for col in range(2, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 15

        return ws

    # Лист 1: по производствам
    add_sheet(
        'По производствам',
        ['Производство', 'Работают', 'Уволены', 'Всего'],
        [(p.name, p.active, p.dismissed, p.total) for p in data['by_production']],
    )

    # Лист 2: по цехам
    add_sheet(
        'По цехам',
        ['Цех', 'Производство', 'Работают', 'Уволены', 'Всего'],
        [
            (f'Цех {w.number}', w.production.name if w.production else '—',
             w.active, w.dismissed, w.total)
            for w in data['by_workshop']
        ],
    )

    # Лист 3: по должностям
    add_sheet(
        'По должностям',
        ['Должность', 'Работают', 'Уволены', 'Всего'],
        [(p.name, p.active, p.dismissed, p.total) for p in data['by_position']],
    )

    # Лист 4: по категориям работников
    add_sheet(
        'По категориям',
        ['Категория работника', 'Работают', 'Уволены', 'Всего'],
        [(c.name, c.active, c.dismissed, c.total) for c in data['by_category']],
    )

    # Отдаём файл как вложение
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="headcount_report.xlsx"'
    wb.save(response)
    return response
