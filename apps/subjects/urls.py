from django.urls import path
from django.views.generic import TemplateView
from . import views

# Placeholders hasta la Fase 3; los nombres los usa partials/sidebar.html.
placeholder = TemplateView.as_view(template_name='placeholder.html')

urlpatterns = [
    path('profesor/dashboard/', views.ProfessorDashboardView.as_view(), name='professor_dashboard'),
    path('alumno/dashboard/', views.StudentDashboardView.as_view(), name='student_dashboard'),
    path('materia/<int:pk>/', views.SubjectDetailView.as_view(), name='subject_detail'),
]
