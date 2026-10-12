from django.urls import path
from . import views

urlpatterns = [
    path('notificaciones/marcar-leidas/', views.NotificationsReadView.as_view(), name='notifications_read'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('perfil/', views.ProfileView.as_view(), name='profile'),
    
]
