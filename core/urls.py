from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Авторизация
    path('login/',  views.login_view,    name='login'),
    path('logout/', views.logout_view,   name='logout'),
    path('403/',    views.access_denied, name='access_denied'),
 
    # Основные страницы
    path('',        views.home_redirect, name='home'),
    path('upload/', views.upload_file,   name='upload_file'),
    path('profile/', views.profile_view, name='profile'),
 
    # Сотрудники
    path('employees/',                              views.employee_list,   name='employee_list'),
    path('employees/<str:employee_number>/',        views.employee_detail, name='employee_detail'),
    path('employees/<str:employee_number>/edit/',   views.employee_edit,   name='employee_edit'),
    path('employees/<str:employee_number>/delete/', views.employee_delete, name='employee_delete'),
 
    # Отчёты
    path('dashboard/',                views.dashboard,               name='dashboard'),
    path('reports/headcount/',        views.report_headcount,        name='report_headcount'),
    path('reports/headcount/export/', views.report_headcount_export, name='report_headcount_export'),
    path('reports/movement/',         views.report_movement,         name='report_movement'),
    path('reports/movement/export/',  views.report_movement_export,  name='report_movement_export'),
]