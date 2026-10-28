from django import forms

from .models import AcademicCertificate, EducationalInstitution, Student


class BootstrapMixin:
    """Проставляет классы Bootstrap всем полям формы."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            # Пустой вариант в списках вместо «- Select an option -»
            if isinstance(field, forms.ModelChoiceField):
                field.empty_label = '—'
            elif getattr(field, 'choices', None) and field.choices[0][0] == '':
                field.choices = [('', '—')] + list(field.choices)[1:]
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-check-input'
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = 'form-select form-select-sm'
            else:
                widget.attrs['class'] = 'form-control form-control-sm'


DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class StudentGeneralForm(BootstrapMixin, forms.ModelForm):
    new_institution = forms.CharField(
        label='Новое учебное заведение',
        required=False,
        max_length=500,
        help_text='Если нет в списке — впишите полное наименование, оно добавится в справочник',
    )

    class Meta:
        model = Student
        fields = [
            'admission_kind', 'institution', 'payment_method',
            'birth_date', 'snils', 'inn',
            'passport_series', 'passport_number', 'passport_issue_date', 'passport_issued_by',
            'address',
        ]
        widgets = {
            'birth_date': DATE_WIDGET,
            'passport_issue_date': DATE_WIDGET,
            'address': forms.Textarea(attrs={'rows': 2}),
        }

    def save(self, commit=True):
        name = self.cleaned_data.get('new_institution', '').strip()
        if name:
            institution, _ = EducationalInstitution.objects.get_or_create(name=name)
            self.instance.institution = institution
        return super().save(commit)


class StudentReportForm(BootstrapMixin, forms.ModelForm):

    class Meta:
        model = Student
        fields = [
            'specialty', 'training_program', 'contract_party', 'study_form', 'study_status',
            'admission_year', 'graduation_year',
            'contract_number', 'contract_date', 'has_additional_agreement',
            'additional_agreement_number', 'contract_expenses',
            'employment_position', 'employment_year', 'current_employee_status',
            'non_fulfillment_reasons', 'measures_taken',
        ]
        widgets = {
            'contract_date': DATE_WIDGET,
            'non_fulfillment_reasons': forms.Textarea(attrs={'rows': 2}),
            'measures_taken': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('admission_year'), cleaned.get('graduation_year')
        if start and end and end < start:
            self.add_error('graduation_year', 'Год окончания раньше года поступления')
        return cleaned


MAX_SCAN_SIZE = 10 * 1024 * 1024  # 10 МБ


class CertificateForm(BootstrapMixin, forms.ModelForm):
    remove_scan = forms.BooleanField(label='Удалить скан', required=False)

    class Meta:
        model = AcademicCertificate
        fields = ['academic_year', 'semester', 'number', 'grade', 'valid_from', 'valid_to', 'scan']
        widgets = {
            'valid_from': DATE_WIDGET,
            'valid_to': DATE_WIDGET,
            'scan': forms.FileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png'}),
        }

    def __init__(self, *args, years=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.old_scan = self.instance.scan.name if self.instance.pk else ''
        # Учебный год — список годов обучения студента вместо ввода числа
        self.fields['academic_year'] = forms.TypedChoiceField(
            label='Учебный год',
            coerce=int,
            choices=[(y, f'{y}/{y + 1}') for y in years],
            widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
        )

    def clean_scan(self):
        scan = self.cleaned_data.get('scan')
        if scan and scan.size > MAX_SCAN_SIZE:
            raise forms.ValidationError('Файл больше 10 МБ')
        return scan

    def clean(self):
        cleaned = super().clean()
        year, semester = cleaned.get('academic_year'), cleaned.get('semester')
        if year and semester:
            duplicate = AcademicCertificate.objects.filter(
                student=self.instance.student, academic_year=year, semester=semester,
            ).exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError('За этот семестр справка уже есть — измените её')
        return cleaned

    def save(self, commit=True):
        certificate = super().save(commit=False)
        if self.cleaned_data.get('remove_scan') and 'scan' not in self.files:
            certificate.scan = ''
        certificate.save()
        # Старый файл больше не нужен — заменен или удален
        if self.old_scan and self.old_scan != certificate.scan.name:
            certificate.scan.storage.delete(self.old_scan)
        return certificate
