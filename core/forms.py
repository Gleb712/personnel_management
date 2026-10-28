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
        help_text="Поддерживаемые форматы: XLSX, XLS",
        widget=forms.ClearableFileInput(attrs={
            'accept': '.xlsx,.xls',
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
            raise forms.ValidationError(f"Неподдерживаемый формат. Разрешены: xlsx, xls")
        
        # Проверка размера файла
        if file.size > 100 * 1024 * 1024:
            raise forms.ValidationError("Размер файла не должен превышать 100 МБ")
        return file


class EmployeeEditForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'full_name', 'birth_date', 'hire_date', 'dismissal_date',
            'workshop', 'position', 'employee_category', 'dismissal_reason'
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
        
METHOD_CHOICES = [
    ('GET', 'GET'),
    ('PATCH', 'PATCH'),
]

# Правильные настройки из API
SETTING_CHOICES = [
    ('poll_interval_seconds', 'Poll Interval Seconds'),
    ('cron_hours', 'Cron Hours'),
    ('cron_minutes', 'Cron Minutes'),
    ('external_queue_interval_seconds', 'External Queue Interval Seconds'),
]

class ApiRequestForm(forms.Form):
    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        label='Метод запроса',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    setting_key = forms.ChoiceField(
        choices=SETTING_CHOICES,
        label='Настройка',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'setting_key'})
    )
    
    token = forms.CharField(
        required=True,
        label='Токен доступа',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите api-ключ'
        })
    )
    
    value = forms.IntegerField(
        required=False,
        label='Значение',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите число (только для PATCH)',
            'id': 'value_field'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        value = cleaned_data.get('value')
        
        if method == 'PATCH':
            if value is None or value == '':
                self.add_error('value', 'Для PATCH запроса необходимо указать значение')
        
        token = cleaned_data.get('token')
        if not token:
            self.add_error('token', 'Токен доступа обязателен')
        
        return cleaned_data
    
    def get_full_key(self):
        return self.cleaned_data.get('setting_key')