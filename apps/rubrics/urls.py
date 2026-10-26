from django.urls import path

from . import views

app_name = 'rubrics'

urlpatterns = [
    path('rubricas/', views.RubricListView.as_view(), name='list'),
    path('rubricas/nueva/', views.RubricEditorView.as_view(), name='create'),
    path('rubricas/<int:pk>/', views.RubricDetailView.as_view(), name='detail'),
    path('rubricas/<int:pk>/editar/', views.RubricEditorView.as_view(), name='update'),
    path('rubricas/<int:pk>/duplicar/', views.RubricDuplicateView.as_view(), name='duplicate'),
    path('rubricas/<int:pk>/archivar/', views.RubricArchiveView.as_view(), name='archive'),
    path('rubricas/<int:pk>/eliminar/', views.RubricDeleteView.as_view(), name='delete'),
    path('actividades/<int:pk>/calificar/rubrica/', views.RubricGradeListView.as_view(), name='grade_list'),
    path('actividades/<int:pk>/calificar/rubrica/<int:student_pk>/', views.RubricGradeStudentView.as_view(), name='grade_student'),
]
