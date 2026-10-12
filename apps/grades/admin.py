from django.contrib import admin
from .models import Evaluation, Grade

@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'type', 'max_score', 'weight', 'date')
    list_filter = ('type', 'course')
    search_fields = ('title', 'course__name')
    autocomplete_fields = ('course',)

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'evaluation', 'score', 'graded_at')
    list_filter = ('evaluation__course',)
    search_fields = ('student__first_name', 'student__last_name', 'student__email', 'evaluation__title')
    autocomplete_fields = ('student', 'evaluation')