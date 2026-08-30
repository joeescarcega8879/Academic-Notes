from django.urls import path
from django.views.generic import TemplateView

app_name = 'grades'

# Placeholder hasta la Fase 4.
urlpatterns = [
    path('calificaciones/', TemplateView.as_view(template_name='placeholder.html'), name='list'),
]
