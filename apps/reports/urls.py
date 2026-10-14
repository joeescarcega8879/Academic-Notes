from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('grupo/<int:course_pk>/boletas.pdf', views.TranscriptsView.as_view(), name='transcripts'),
    path('grupo/<int:course_pk>/boletas/<int:student_pk>.pdf', views.TranscriptsView.as_view(), name='transcript'),
    path('grupo/<int:course_pk>/concentrado/', views.WorkbookConfigView.as_view(), name='workbook'),
    path('grupo/<int:course_pk>/concentrado.xlsx', views.WorkbookDownloadView.as_view(), name='workbook_download'),
    path('grupo/<int:course_pk>/riesgo/', views.RiskView.as_view(), name='risk'),
]
