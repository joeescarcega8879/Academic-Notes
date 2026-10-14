from django.urls import path

from . import views

# Sin espacio de nombres: la campana del topbar está en todas las pantallas y usa ``notifications_read``.
urlpatterns = [
    path('notificaciones/marcar-leidas/', views.NotificationsReadView.as_view(), name='notifications_read'),
]
