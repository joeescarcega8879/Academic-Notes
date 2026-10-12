from django.urls import path

from . import builder_views, views

app_name = 'quizzes'

urlpatterns = [
    path('actividades/<int:pk>/quiz/', builder_views.BuilderView.as_view(), name='builder'),
    path('banco/', views.BankView.as_view(), name='bank'),
    path('banco/nueva/<str:kind>/', views.QuestionCreateView.as_view(), name='question_create'),
    path('banco/<int:pk>/', views.QuestionDetailView.as_view(), name='question_detail'),
    path('banco/<int:pk>/editar/', views.QuestionUpdateView.as_view(), name='question_update'),
    path('banco/<int:pk>/duplicar/', views.QuestionDuplicateView.as_view(), name='question_duplicate'),
    path('banco/<int:pk>/archivar/', views.QuestionArchiveView.as_view(), name='question_archive'),
    path('banco/<int:pk>/eliminar/', views.QuestionDeleteView.as_view(), name='question_delete'),
]
