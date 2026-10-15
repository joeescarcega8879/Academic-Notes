from django.urls import path

from . import views

urlpatterns = [
    path('', views.LandingView.as_view(), name='home'),
    path('precios/', views.PricingView.as_view(), name='pricing'),
    path('registro/', views.TeacherRegisterView.as_view(), name='register'),
    path('registro/alumno/', views.StudentRegisterView.as_view(), name='register_student'),
    path('terminos/', views.LegalView.as_view(template_name='onboarding/terms.html'), name='terms'),
    path('privacidad/', views.LegalView.as_view(template_name='onboarding/privacy.html'), name='privacy'),
    path('ayuda/', views.HelpView.as_view(), name='help'),
    path('primeros-pasos/ocultar/', views.DismissChecklistView.as_view(), name='onboarding_dismiss'),
]
