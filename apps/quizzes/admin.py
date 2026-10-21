from django.contrib import admin

from .models import Choice, Question


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'kind', 'course', 'topic', 'points', 'author', 'organization', 'is_archived')
    list_filter = ('kind', 'is_archived', 'organization', 'course')
    search_fields = ('text', 'topic')
    inlines = [ChoiceInline]
