from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    # Antes los grupos se llamaban «materias»: los enlaces y favoritos viejos siguen llegando al mismo lugar.
    re_path(r'^materia/(?P<rest>.*)$', RedirectView.as_view(url='/grupo/%(rest)s', permanent=True, query_string=True)),
    path('', include('apps.onboarding.urls')),
    path('', include('apps.accounts.urls')),
    path('', include('apps.organizations.urls')),
    path('', include('apps.courses.urls')),
    path('', include('apps.grades.urls')),
    path('', include('apps.syllabus.urls')),
    path('', include('apps.batches.urls')),
    path('', include('apps.quizzes.urls')),
    path('', include('apps.ai.urls')),
    path('', include('apps.reports.urls')),
    path('', include('apps.messaging.urls')),
    path('', include('apps.messaging.notification_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
