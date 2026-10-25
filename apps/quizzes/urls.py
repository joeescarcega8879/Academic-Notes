from django.urls import path

from . import builder_views, import_views, results_views, take_views, views

app_name = 'quizzes'

urlpatterns = [
    path('actividades/<int:pk>/quiz/', builder_views.BuilderView.as_view(), name='builder'),
    path('actividades/<int:pk>/examen-en-linea/', builder_views.ExamOnlineView.as_view(), name='exam_online'),
    path('actividades/<int:pk>/quiz/resultados/', results_views.QuizResultsView.as_view(), name='results'),
    path('intentos/<int:pk>/revision/', results_views.AttemptReviewView.as_view(), name='review'),
    path('intentos/<int:pk>/eliminar/', results_views.AttemptDeleteView.as_view(), name='attempt_delete'),
    path('actividades/<int:pk>/resolver/', take_views.QuizOverviewView.as_view(), name='overview'),
    path('intentos/<int:pk>/', take_views.QuizTakeView.as_view(), name='take'),
    path('intentos/<int:pk>/guardar/', take_views.QuizAutosaveView.as_view(), name='autosave'),
    path('intentos/<int:pk>/resultado/', take_views.QuizResultView.as_view(), name='result'),
    path('banco/', views.BankView.as_view(), name='bank'),
    path('banco/importar/', import_views.QuestionImportView.as_view(), name='import'),
    path('banco/importar/vista-previa/', import_views.QuestionImportPreviewView.as_view(), name='import_preview'),
    path('banco/importar/plantilla.csv', import_views.QuestionImportTemplateView.as_view(), name='import_template'),
    path('banco/nueva/<str:kind>/', views.QuestionCreateView.as_view(), name='question_create'),
    path('banco/<int:pk>/', views.QuestionDetailView.as_view(), name='question_detail'),
    path('banco/<int:pk>/editar/', views.QuestionUpdateView.as_view(), name='question_update'),
    path('banco/<int:pk>/duplicar/', views.QuestionDuplicateView.as_view(), name='question_duplicate'),
    path('banco/<int:pk>/archivar/', views.QuestionArchiveView.as_view(), name='question_archive'),
    path('banco/<int:pk>/eliminar/', views.QuestionDeleteView.as_view(), name='question_delete'),
]
