from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from .forms import FileUploadForm
from core.services.file_processor import EmployeeFileProcessor
from .models import Employee


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
            skip_duplicates = form.cleaned_data.get('skip_duplicates', True)
            update_existing = form.cleaned_data.get('update_existing', False)
            
            try:
                # Создаём обработчик и обрабатываем файл
                processor = EmployeeFileProcessor(
                    uploaded_file,
                    skip_duplicates=skip_duplicates,
                    update_existing=update_existing
                )
                result = processor.process()
                
                # Сообщения об успехе
                if result['success'] > 0:
                    messages.success(
                        request,
                        f"Успешно загружено: {result['success']} сотрудников. "
                        f"Пропущено: {result['skipped']}. "
                        f"Обновлено: {result['updated']}."
                    )
                
                # Сообщения об ошибках
                if result['errors']:
                    messages.warning(
                        request,
                        f"Ошибок при загрузке: {len(result['errors'])}. "
                        f"Проверьте список ниже."
                    )
                    # Сохраняем ошибки в сессии для отображения
                    request.session['upload_errors'] = result['errors']
                
                # Перенаправляем на эту же страницу (PRG паттерн), чтобы при обновлении страницы форма не отправлялась снова
                return redirect('core:upload_file')
            
            except Exception as e:
                messages.error(request, f"Ошибка при обработке файла: {str(e)}")
        else:
            messages.error(request, "Ошибка в форме загрузки")
    else:
        # GET запрос - создаём пустую форму
        form = FileUploadForm()
    
    # Получаем ошибки из сессии и удаляем их
    errors = request.session.pop('upload_errors', [])
    
    context = {
        'form': form,
        'errors': errors,
    }
    
    return render(request, 'core/upload/upload_file.html', context)

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
    ).order_by('full_name')

    # Пагинация
    paginator = Paginator(employees, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'total_count': employees.count(),
    }

    return render(request, 'core/employee/employee_list.html')

def employee_edit(request, employee_number):

    employee = get_object_or_404(Employee, employee_number=employee_number)
    if request.method == 'POST':
        # Обновление полей формы
        employee.full_name = request.POST.get('full_name')
        employee.birth_date = request.POST.get('birth_date') or None
        employee.hire_date = request.POST.get('hire_date')
        employee.dismissal_reason = request.POST.get('dismissal_reason') or None

        # Сохранение
        try:
            employee.save()
            messages.success(request, f"Сотрудник {employee.full_name} обновлен")
            return redirect('core:employee_list')
        except Exception as e:
            messages.error(request, f"Ошибка сохранения: {str(e)}")

    context = {
        'employee': employee,
    }

    return render(request, 'core/employee/employee_edit.html', context)

def employee_delete(request, employee_number):
    employee = get_object_or_404(Employee, employee_number=employee_number)

    if request.method == 'POST':
        full_name = employee.full_name
        employee.delete()
        messages.success(request, f"Сотрудник {full_name} удален")
        return redirect('employee_list')
    
    context = {
        'employee': employee,
    }

    return render(request, 'core/employee/employee_confirm_delete.html', context)

def home_redirect(request):
    """
    Редирект с главной страницы на загрузку файлов
    """
    return redirect('core:upload_file')
