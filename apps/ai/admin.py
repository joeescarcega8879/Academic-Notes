from django.contrib import admin

from .models import AIRequest


@admin.register(AIRequest)
class AIRequestAdmin(admin.ModelAdmin):
    """Bitácora de solo lectura: sirve para auditar y para ver el costo, no para editar."""

    list_display = ('created_at', 'organization', 'kind', 'status', 'provider', 'model', 'tokens_in', 'tokens_out', 'cost_usd')
    list_filter = ('status', 'kind', 'provider', 'contains_student_data', 'organization')
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in AIRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
