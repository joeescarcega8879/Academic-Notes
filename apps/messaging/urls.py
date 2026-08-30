from django.urls import path
from django.views.generic import TemplateView

app_name = 'messaging'

# Placeholder hasta la Fase 5.
urlpatterns = [
    path('mensajes/', TemplateView.as_view(template_name='placeholder.html'), name='list'),
]
