from django.urls import path
from . import scheme_views, views

app_name = 'grades'

urlpatterns = [
    path('calificaciones/', views.GradeListView.as_view(), name='list'),
    path('calificaciones/nueva/', views.GradeCreateView.as_view(), name='create'),
    path('calificaciones/exportar/', views.GradeExportView.as_view(), name='export'),
    path('calificaciones/esquema/<int:pk>/', scheme_views.SchemeView.as_view(), name='scheme'),
    path('calificaciones/<int:pk>/editar/', views.GradeUpdateView.as_view(), name='update'),
    path('calificaciones/<int:pk>/eliminar/', views.GradeDeleteView.as_view(), name='delete'),
]
