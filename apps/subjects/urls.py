from django.urls import path
from django.views.generic import TemplateView

# Placeholders hasta la Fase 3; los nombres los usa partials/sidebar.html.
placeholder = TemplateView.as_view(template_name='placeholder.html')

urlpatterns = [
    path('profesor/dashboard/', placeholder, name='professor_dashboard'),
    path('alumno/dashboard/', placeholder, name='student_dashboard'),
]
