from django.urls import path

from . import views

app_name = 'batches'

urlpatterns = [
    path('actividades/<int:pk>/lote/', views.BatchView.as_view(), name='index'),
    path('actividades/<int:pk>/lote/estado/', views.BatchStatusView.as_view(), name='status'),
    path('actividades/<int:pk>/lote/guardar/', views.BatchApplyView.as_view(), name='apply'),
    path('lote/<int:pk>/asignar/', views.BatchAssignView.as_view(), name='assign'),
    path('lote/<int:pk>/descartar/', views.BatchDiscardView.as_view(), name='discard'),
    path('lote/<int:pk>/archivo/', views.BatchFileView.as_view(), name='file'),
]
