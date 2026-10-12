from django.contrib import admin
from .models import Activity, EvaluationCriterion, EvaluationPeriod, EvaluationScheme, Grade

class PeriodInline(admin.TabularInline):
    model = EvaluationPeriod
    extra = 0


@admin.register(EvaluationScheme)
class EvaluationSchemeAdmin(admin.ModelAdmin):
    list_display = ('course', 'scale_max', 'pass_mark', 'rounding_decimals')
    search_fields = ('course__name',)
    inlines = [PeriodInline]


@admin.register(EvaluationCriterion)
class EvaluationCriterionAdmin(admin.ModelAdmin):
    list_display = ('name', 'period', 'weight', 'default_type')
    search_fields = ('name', 'period__scheme__course__name')


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'type', 'max_score', 'weight', 'date')
    list_filter = ('type', 'course')
    search_fields = ('title', 'course__name')
    autocomplete_fields = ('course',)

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'activity', 'score', 'graded_at')
    list_filter = ('activity__course',)
    search_fields = ('student__first_name', 'student__last_name', 'student__email', 'activity__title')
    autocomplete_fields = ('student', 'activity')