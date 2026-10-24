from django.urls import path

from . import views

app_name = 'ai'

urlpatterns = [
    path('grupo/<int:pk>/ia/quiz/', views.QuizGenerateView.as_view(), name='quiz_generate'),
    path('grupo/<int:pk>/ia/semanas/', views.SplitGenerateView.as_view(), name='split_generate'),
    path('ia/propuestas/<int:pk>/', views.DraftView.as_view(), name='draft'),
    path('ia/propuestas/<int:pk>/estado/', views.DraftStatusView.as_view(), name='draft_status'),
]
