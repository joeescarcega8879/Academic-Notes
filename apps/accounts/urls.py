from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('correo/confirmar/<str:token>/', views.VerifyEmailView.as_view(), name='verify_email'),
    path('correo/reenviar/', views.ResendVerificationView.as_view(), name='resend_verification'),
    path('contrasena/olvide/', views.ForgotPasswordView.as_view(), name='password_reset'),
    path('contrasena/olvide/enviado/', TemplateView.as_view(template_name='auth/forgot_sent.html'), name='password_reset_sent'),
    path('contrasena/restablecer/<uidb64>/<token>/', views.PasswordResetConfirm.as_view(), name='password_reset_confirm'),
    path('contrasena/restablecer/listo/', views.PasswordResetComplete.as_view(), name='password_reset_complete'),
    path('contrasena/cambiar/', views.ChangePasswordView.as_view(), name='password_change'),
]
