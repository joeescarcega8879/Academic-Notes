from django.urls import path
from . import views

app_name = 'grades'

urlpatterns = [
    path('calificaciones/', views.GradeListView.as_view(), name='list'),
    path('calificaciones/nueva/', views.GradeCreateView.as_view(), name='create'),
    path('calificaciones/exportar/', views.GradeExportView.as_view(), name='export'),
    path('calificaciones/<int:pk>/editar/', views.GradeUpdateView.as_view(), name='update'),
    path('calificaciones/<int:pk>/eliminar/', views.GradeDeleteView.as_view(), name='delete'),
]
