from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('mensajes/', views.ConversationListView.as_view(), name='list'),
    path('mensajes/<int:pk>/', views.ConversationDetailView.as_view(), name='detail'),
    path('mensajes/<int:pk>/enviar/', views.MessageCreateView.as_view(), name='send'),
]
