from django.urls import path

from . import views

app_name = 'syllabus'

urlpatterns = [
    path('grupo/<int:pk>/temario/', views.SyllabusView.as_view(), name='index'),
    path('grupo/<int:pk>/temario/archivo/', views.SyllabusFileView.as_view(), name='file'),
]
