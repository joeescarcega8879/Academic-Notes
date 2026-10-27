from django.contrib import admin

from .models import Team, TeamMember


class MemberInline(admin.TabularInline):
    model = TeamMember
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'activity', 'organization', 'created_at')
    list_filter = ('organization',)
    search_fields = ('name', 'activity__title')
    inlines = [MemberInline]
