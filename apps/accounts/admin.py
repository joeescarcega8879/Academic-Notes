from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, StudentProfile, ProfessorProfile

class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'username', 'role', 'is_staff']
    list_filter = ['role', 'is_staff']
    ordering = ['email']
    
    fieldsets = UserAdmin.fieldsets + (
        ('Rol y Datos', {'fields': ('role', 'phone', 'birth_date', 'dni', 'avatar')}),
        ('Preferencias', {'fields': ('notify_grades', 'notify_weekly', 'notify_sms', 'show_average')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'role', 'dni', 'password1', 'password2'),
        }),
    )
admin.site.register(User, CustomUserAdmin)
admin.site.register(StudentProfile)
admin.site.register(ProfessorProfile)