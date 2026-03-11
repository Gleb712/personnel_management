from django import forms
from .models import Employee


class FileUploadForm(forms.Form):
    """Форма для загрузки файла с данными о сотрудниках

    Args:
        forms (_type_): _description_
    """

    # Поле для загрузки файла
    file = forms.FileField(
        label="Выберите файл",
        help_text="Поддерживаемые форматы: CSV, XLSX, XLS",
        widget=forms.ClearableFileInput(attrs={
            'accept': '.csv,.xlsx,.xls',
            'class': 'form-control'
        })
    )

    def clean_file(self):
        """
        Метод валидации данных из Django Forms
        """
        file = self.cleaned_data.get('file')
        
        # Проверка загружен ли файл
        if not file:
            raise forms.ValidationError('Файл не загружен')
        
        # Проверка расширения файла
        ext = file.name.split('.')[-1].lower()
        if ext not in ['csv', 'xlsx', 'xls']:
            raise forms.ValidationError(f"Неподдерживаемый формат. Разрешены: csv, xlsx, xls")
        
        # Проверка размера файла
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Размер файла не должен превышать 10 МБ")
        return file


class EmployeeEditForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'full_name', 'birth_date', 'hire_date', 'dismissal_date',
            'production', 'workshop', 'position', 'employee_category', 'dismissal_reason'
        ]
        widgets = {
            'full_name': forms.TextInput(
                attrs={'class': 'form-control'}
            ),
            'birth_date': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}
            ),
            'hire_date': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}
            ),
            'dismissal_date': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}
            ),
            'production': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'workshop': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'position': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'employee_category': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'dismissal_reason': forms.Select(
                attrs={'class': 'form-select'}
            ),
        }
        