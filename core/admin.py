from django.contrib import admin
from .models import Employee, Production, Workshop, DismissalReason, EmployeeCategory, Position


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_number', 'full_name', 'hire_date', 'dismissal_date',
                    'production', 'workshop', 'position', 'is_active']
    list_filter = ['production', 'workshop', 'employee_category', 'position']
    search_fields = ['full_name', 'employee_number']
    date_hierarchy = 'hire_date'
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 100
    fieldsets = (
        ('Основное', {'fields': ('full_name', 'employee_number')}),
        ('Даты', {'fields': ('birth_date', 'hire_date', 'dismissal_date', 'dismissal_reason')}),
        ('Место работы', {'fields': ('production', 'workshop', 'position', 'employee_category')}),
        ('Служебное', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(boolean=True, description='Работает')
    def is_active(self, obj):
        return obj.dismissal_date is None


@admin.register(Production)
class ProductionAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ['number', 'name', 'production']
    list_filter = ['production']
    search_fields = ['number', 'name']


@admin.register(DismissalReason)
class DismissalReasonAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(EmployeeCategory)
class EmployeeCategoryAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']