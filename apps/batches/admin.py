from django.contrib import admin

from .models import BatchFile


@admin.register(BatchFile)
class BatchFileAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'activity', 'organization', 'status', 'body_status', 'student', 'pages', 'created_at')
    list_filter = ('status', 'body_status', 'organization')
    search_fields = ('original_name', 'activity__title')
    raw_id_fields = ('activity', 'student', 'uploaded_by')
