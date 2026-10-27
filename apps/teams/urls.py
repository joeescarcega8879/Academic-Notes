from django.urls import path

from . import views

app_name = 'teams'

urlpatterns = [
    path('actividades/<int:pk>/equipos/', views.TeamsView.as_view(), name='index'),
    path('actividades/<int:pk>/equipos/nuevo/', views.TeamCreateView.as_view(), name='create'),
    path('actividades/<int:pk>/equipos/azar/', views.TeamRandomView.as_view(), name='random'),
    path('actividades/<int:pk>/equipos/copiar/', views.TeamCopyView.as_view(), name='copy'),
    path('actividades/<int:pk>/equipos/asignar/', views.TeamAssignView.as_view(), name='assign'),
    path('actividades/<int:pk>/equipos/<int:team_pk>/renombrar/', views.TeamRenameView.as_view(), name='rename'),
    path('actividades/<int:pk>/equipos/<int:team_pk>/borrar/', views.TeamDeleteView.as_view(), name='delete'),
    path('actividades/<int:pk>/calificar/equipos/', views.TeamGradeListView.as_view(), name='grade_list'),
    path('actividades/<int:pk>/calificar/equipos/<int:team_pk>/', views.TeamGradeView.as_view(), name='grade'),
]
