from django.urls import path
from sso_client import views as sso_views
from . import views

app_name = 'core'

urlpatterns = [
    # Авторизация
    # Вход и выход - в сервисе авторизации (см. sso_client); имена маршрутов сохранены
    path('login/',  sso_views.login,     name='login'),
    path('logout/', sso_views.logout,    name='logout'),
    path('403/',    views.access_denied, name='access_denied'),
 
    # Основные страницы
    path('',        views.home_redirect, name='home'),
    path('upload/', views.upload_file,   name='upload_file'),
    path('profile/', views.profile_view, name='profile'),
 
    # Сотрудники
    path('employees/',                                    views.employee_list,               name='employee_list'),
    path('employees_ext/',                                views.employee_list_extended,      name='employee_list_extended'),
    path('employees/<str:employee_number>/',              views.employee_detail,             name='employee_detail'),
    path('employees/<str:employee_number>/edit/',         views.employee_edit,               name='employee_edit'),
    path('employees/<str:employee_number>/delete/',       views.employee_delete,             name='employee_delete'),
    path('employees/<str:employee_number>/transfers',     views.employee_transfers,          name='employee_transfers'),
    path('employees/<str:employee_number>/salary',        views.employee_salary,             name='employee_salary'),
    path('employee_ext/export/excel/',                    views.export_employees_excel,      name='export_employees_excel'),  
 
    # Зарплаты
    path('salary/', views.salary_list, name='salary_list'),
    path('salary/<str:employee_number>/modal/', views.salary_modal_data, name='salary_modal_data'),

    # Отчёты
    path('dashboard/',                                   views.dashboard,               name='dashboard'),
    path('reports/headcount/',                           views.report_headcount,        name='report_headcount'),
    path('reports/headcount/export/',                    views.report_headcount_export, name='report_headcount_export'),
    path('reports/movement/',                            views.report_movement,         name='report_movement'),
    path('reports/movement/export/',                     views.report_movement_export,  name='report_movement_export'),
    path('reports/daily_report/',                        views.daily_report,            name='daily_report'),

    # Подробности по карточкам "Работает сейчас", "Принято", "Уволено", "Переводы" в дашборде
    path('reports/currently_working/',                                                        views.currently_working,        name='currently_working'),
    path('reports/dashboard_details/<int:details_type>/',                                     views.dashboard_details,        name='dashboard_details'),
    path('reports/reason_details/<int:reason_id>/<str:action>/<str:period>/<str:employee_type>/<str:details_date>/', views.dashboard_reason_details, name='reason_details'), 
    path('reports/reason_details/<str:action>/<str:period>/<str:employee_type>/<str:details_date>/',                 views.dashboard_reason_details, name='reason_details'),
    path('reports/transfers_details/',                                                        views.transfers_details,        name='transfers_details'), 

    # Подробности по карточкам с категориями
    path('reports/cats_details/<str:emp_category>',     views.categories_details,       name='cats_details'),

    path('reports/table/', views.report_table, name='report_table'),

    # API
    path('api/employee/<str:tab_number>/', views.api_get_employee),

    # Внешний сервис Бастиона
    path('bastion/',     views.bastion,          name='bastion'),
    path('api/status/',  views.api_status_json,  name='api_status_json'),
]