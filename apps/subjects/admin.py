from django.contrib import admin
from .models import Subject, Enrollment

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'professor', 'schedule')
    search_fields = ('name', 'code')
    list_filter = ('professor',)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'enrolled_at')
    search_fields = ('student__username', 'subject__name')
  