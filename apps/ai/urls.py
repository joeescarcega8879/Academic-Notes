from django.urls import path

from . import review_views, views

app_name = 'ai'

urlpatterns = [
    path('grupo/<int:pk>/ia/quiz/', views.QuizGenerateView.as_view(), name='quiz_generate'),
    path('grupo/<int:pk>/ia/tarea/', views.AssignmentGenerateView.as_view(), name='assignment_generate'),
    path('grupo/<int:pk>/ia/semanas/', views.SplitGenerateView.as_view(), name='split_generate'),
    path('ia/propuestas/<int:pk>/', views.DraftView.as_view(), name='draft'),
    path('ia/tareas/<int:pk>/', views.AssignmentDraftView.as_view(), name='assignment_draft'),
    path('ia/propuestas/<int:pk>/estado/', views.DraftStatusView.as_view(), name='draft_status'),
    path('actividad/<int:pk>/ia/revision/', review_views.ReviewView.as_view(), name='review'),
    path('actividad/<int:pk>/ia/revision/estado/', review_views.ReviewStatusView.as_view(), name='review_status'),
    path('actividad/<int:pk>/ia/revision/confirmar-todas/', review_views.ReviewBulkView.as_view(), name='review_bulk'),
    path('ia/revisiones/<int:pk>/confirmar/', review_views.ReviewActionView.as_view(action='confirm'), name='review_confirm'),
    path('ia/revisiones/<int:pk>/descartar/', review_views.ReviewActionView.as_view(action='discard'), name='review_discard'),
    path('ia/revisiones/<int:pk>/reintentar/', review_views.ReviewActionView.as_view(action='retry'), name='review_retry'),
]
