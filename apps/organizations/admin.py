from django.contrib import admin

from .models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    # El plan se cambia aquí, directo desde la lista: así se activa el plan de pago mientras no haya cobro en línea.
    list_display = ('name', 'type', 'plan', 'is_active', 'created_at')
    list_editable = ('plan',)
    list_filter = ('type', 'plan', 'is_active')
    search_fields = ('name',)
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'created_at')
    list_filter = ('role', 'organization')
    search_fields = ('user__email', 'user__username', 'organization__name')
