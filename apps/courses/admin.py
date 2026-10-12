from django.contrib import admin
from .models import Course, Enrollment, Student

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'organization', 'professor', 'schedule')
    search_fields = ('name', 'code')
    list_filter = ('organization', 'professor')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'student_number', 'email', 'organization', 'user')
    search_fields = ('first_name', 'last_name', 'student_number', 'email')
    list_filter = ('organization',)
    autocomplete_fields = ('user',)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'enrolled_at')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_number', 'course__name')
    autocomplete_fields = ('student', 'course')
  