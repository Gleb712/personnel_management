from django import forms


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

    # Пропуск дубликатов
    skip_duplicates = forms.BooleanField(
        label='Пропускать дубликаты',
        required=False,
        initial=False,
        help_text="Если сотрудник с таким табельным номером уже существует - пропустить"
    )

    # Обновление существующих записей
    update_existing = forms.BooleanField(
        label='Обновлять сущствующие записи',
        required=False,
        initial=True,
        help_text="Если сотрудник уже существует - обновить его данные"
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
        allowed_extensions = ['csv', 'xlsx', 'xls']
        file_extension = file.name.split('.')[-1].lower()

        if file_extension not in allowed_extensions:
            raise forms.ValidationError(
                f"Неподдерживаемый формат файла. "
                f"Разрешенные форматы файлов: {','.join(allowed_extensions)}"
            )
        
        # Проверка размера файла
        max_size = 10 * 1024 * 1024
        if file.size > max_size:
            raise forms.ValidationError("Размер загружаемого файла не должен превышать 10Мб")
        
        return file
    