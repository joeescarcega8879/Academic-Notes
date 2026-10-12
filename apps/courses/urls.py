from django.urls import path
from django.views.generic import TemplateView
from . import views

# Placeholders hasta la Fase 3; los nombres los usa partials/sidebar.html.
placeholder = TemplateView.as_view(template_name='placeholder.html')

urlpatterns = [
    path('profesor/dashboard/', views.ProfessorDashboardView.as_view(), name='professor_dashboard'),
    path('alumno/dashboard/', views.StudentDashboardView.as_view(), name='student_dashboard'),
    path('materia/nueva/', views.CourseCreateView.as_view(), name='course_create'),
    path('materia/<int:pk>/', views.CourseDetailView.as_view(), name='course_detail'),
    path('materia/<int:pk>/editar/', views.CourseUpdateView.as_view(), name='course_update'),
    path('materia/<int:pk>/archivar/', views.CourseArchiveView.as_view(), name='course_archive'),
    path('materia/<int:pk>/desarchivar/', views.CourseUnarchiveView.as_view(), name='course_unarchive'),
    path('materia/<int:pk>/duplicar/', views.CourseCloneView.as_view(), name='course_clone'),
    path('ciclos/', views.AcademicYearListView.as_view(), name='academic_years'),
    path('ciclos/<int:pk>/actual/', views.AcademicYearCurrentView.as_view(), name='academic_year_current'),
]
