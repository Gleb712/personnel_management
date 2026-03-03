from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home_redirect, name='home'),
    path('upload/', views.upload_file, name='upload_file'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/<str:employee_number>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<str:employee_number>/delete/', views.employee_delete, name='employee_delete'),
]