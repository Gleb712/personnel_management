from django.urls import path

from . import views

app_name = 'students'

urlpatterns = [
    path('', views.student_list, name='list'),
    path('<int:pk>/row/', views.student_row, name='row'),
    path('<int:pk>/card/', views.student_card, name='card'),
    path('<int:pk>/tab/<str:tab>/', views.student_tab, name='tab'),
    path('<int:pk>/certificates/new/', views.certificate_form, name='certificate_new'),
    path('<int:pk>/certificates/<int:cert_pk>/edit/', views.certificate_form, name='certificate_edit'),
    path('<int:pk>/certificates/<int:cert_pk>/delete/', views.certificate_delete, name='certificate_delete'),
    path('certificates/<int:cert_pk>/scan/', views.certificate_scan, name='certificate_scan'),
    path('sync/', views.sync_now, name='sync'),
]
