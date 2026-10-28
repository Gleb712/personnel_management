from django.contrib import admin

from .models import (
    AcademicCertificate, EducationalInstitution, Scholarship,
    Specialty, Student, StudentHistory, StudentSyncLog,
)


admin.site.register(EducationalInstitution)
admin.site.register(Specialty)
admin.site.register(StudentHistory)
admin.site.register(AcademicCertificate)
admin.site.register(Scholarship)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('employee_number', 'full_name', 'admission_kind', 'institution', 'dismissal_date')
    list_filter = ('admission_kind', 'payment_method', 'institution')
    search_fields = ('employee_number', 'last_name', 'first_name')


@admin.register(StudentSyncLog)
class StudentSyncLogAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'status', 'triggered_by', 'total_rows', 'created', 'updated', 'skipped')
    list_filter = ('status',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
