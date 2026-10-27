from django.urls import path

from . import school_views, views

app_name = 'organizations'

urlpatterns = [
    path('organizacion/cambiar/', views.SwitchOrganizationView.as_view(), name='switch'),
    path('ajustes/', views.SettingsView.as_view(), name='settings'),
    path('ajustes/plan/', views.PlanView.as_view(), name='plan'),
    path('escuela/', school_views.SchoolView.as_view(), name='school'),
    path('escuela/invitar/', school_views.InviteView.as_view(), name='school_invite'),
    path('escuela/invitaciones/<int:pk>/reenviar/', school_views.ResendView.as_view(), name='school_resend'),
    path('escuela/invitaciones/<int:pk>/retirar/', school_views.RevokeView.as_view(), name='school_revoke'),
    path('escuela/invitacion/<str:token>/', school_views.AcceptView.as_view(), name='school_accept'),
]
