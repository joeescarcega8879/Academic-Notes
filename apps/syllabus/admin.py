from django.contrib import admin

from .models import Syllabus, SyllabusWeek


class SyllabusWeekInline(admin.TabularInline):
    model = SyllabusWeek
    extra = 0


@admin.register(Syllabus)
class SyllabusAdmin(admin.ModelAdmin):
    list_display = ('course', 'organization', 'status', 'original_name', 'updated_at')
    list_filter = ('status', 'organization')
    search_fields = ('course__name', 'original_name')
    autocomplete_fields = ('course',)
    inlines = [SyllabusWeekInline]
