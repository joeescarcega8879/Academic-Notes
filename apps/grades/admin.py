from django.contrib import admin
from .models import Evaluation, Grade

@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'type', 'max_score', 'weight', 'date')
    list_filter = ('type', 'subject')
    search_fields = ('title', 'subject__name')
    autocomplete_fields = ('subject',)

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'evaluation', 'score', 'graded_at')
    list_filter = ('evaluation__subject',)
    search_fields = ('student__username', 'student__email', 'evaluation__title')
    autocomplete_fields = ('student', 'evaluation')