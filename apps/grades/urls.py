from django.urls import path
from . import activity_views, scheme_views, views

app_name = 'grades'

urlpatterns = [
    path('calificaciones/', views.GradeListView.as_view(), name='list'),
    path('calificaciones/nueva/', views.GradeCreateView.as_view(), name='create'),
    path('calificaciones/exportar/', views.GradeExportView.as_view(), name='export'),
    path('calificaciones/esquema/<int:pk>/', scheme_views.SchemeView.as_view(), name='scheme'),
    path('materia/<int:course_pk>/actividades/nueva/', activity_views.ActivityCreateView.as_view(), name='activity_create'),
    path('actividades/<int:pk>/', activity_views.ActivityDetailView.as_view(), name='activity_detail'),
    path('actividades/<int:pk>/calificar/', activity_views.GradingView.as_view(), name='activity_grading'),
    path('actividades/<int:pk>/historial/', activity_views.GradeHistoryView.as_view(), name='activity_history'),
    path('actividades/<int:pk>/entregar/', activity_views.SubmitActivityView.as_view(), name='activity_submit'),
    path('entregas/<int:pk>/', activity_views.SubmissionDetailView.as_view(), name='submission_detail'),
    path('entregas/<int:pk>/archivo/', activity_views.SubmissionFileView.as_view(), name='submission_file'),
    path('actividades/<int:pk>/editar/', activity_views.ActivityUpdateView.as_view(), name='activity_update'),
    path('actividades/<int:pk>/publicar/', activity_views.ActivityPublishView.as_view(), name='activity_publish'),
    path('actividades/<int:pk>/eliminar/', activity_views.ActivityDeleteView.as_view(), name='activity_delete'),
    path('calificaciones/<int:pk>/editar/', views.GradeUpdateView.as_view(), name='update'),
    path('calificaciones/<int:pk>/eliminar/', views.GradeDeleteView.as_view(), name='delete'),
]
