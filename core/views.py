from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from .forms import FileUploadForm, EmployeeEditForm
from core.services.file_processor import EmployeeFileProcessor
from .models import Employee, Production, Workshop


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

    search = request.GET.get('search', '').strip()
    production_id = request.GET.get('production', '')
    workshop_id = request.GET.get('workshop', '')
    status = request.GET.get('status', '')

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
    paginator = Paginator(employees, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'total_count': employees.count(),
        'productions': Production.objects.all(),
        'workshops': Workshop.objects.all(),
        'search': search,
        'selected_production': production_id,
        'selected_workshop': workshop_id,
        'selected_status': status,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'core/employee/partials/employee_table.html', context)

    return render(request, 'core/employee/employee_list.html', context)


def employee_edit(request, employee_number):
    employee = get_object_or_404(Employee, employee_number=employee_number)

    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, f"Сотрудник {employee.full_name} обновлён")
            return redirect('core:employee_list')
        else:
            messages.error(request, "Проверьте правильность заполнения формы")
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, 'core/employee/employee_edit.html', {
        'form': form,
        'employee': employee,
    })


def employee_delete(request, employee_number):
    employee = get_object_or_404(Employee, employee_number=employee_number)

    if request.method == 'POST':
        full_name = employee.full_name
        employee.delete()
        messages.success(request, f"Сотрудник {full_name} удалён")
        return redirect('core:employee_list')

    return render(request, 'core/employee/employee_confirm_delete.html', {'employee': employee})


def home_redirect(request):
    """
    Редирект с главной страницы на загрузку файлов
    """
    return redirect('core:upload_file')