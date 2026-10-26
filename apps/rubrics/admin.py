from django.contrib import admin

from .models import Rubric, RubricCriterion, RubricVersion


class VersionInline(admin.TabularInline):
    model = RubricVersion
    extra = 0
    readonly_fields = ('number', 'max_points')
    can_delete = False


@admin.register(Rubric)
class RubricAdmin(admin.ModelAdmin):
    list_display = ('name', 'author', 'organization', 'is_archived', 'updated_at')
    list_filter = ('is_archived', 'organization')
    search_fields = ('name', 'description')
    inlines = [VersionInline]


class CriterionInline(admin.TabularInline):
    model = RubricCriterion
    extra = 0


@admin.register(RubricVersion)
class RubricVersionAdmin(admin.ModelAdmin):
    list_display = ('rubric', 'number', 'max_points', 'created_at')
    inlines = [CriterionInline]
