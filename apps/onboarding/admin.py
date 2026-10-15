from django.contrib import admin

from .models import WaitlistEntry


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ('email', 'plan', 'user', 'created_at')
    list_filter = ('plan', 'created_at')
    search_fields = ('email',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
