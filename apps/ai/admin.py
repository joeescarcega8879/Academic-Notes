from django.contrib import admin

from .models import AIDraft, AIRequest, AIReview


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


@admin.register(AIDraft)
class AIDraftAdmin(admin.ModelAdmin):
    """Propuestas de la IA: de solo lectura. Lo que el docente aprueba vive en el banco y en sus quizzes, no aquí."""

    list_display = ('created_at', 'organization', 'course', 'kind', 'status', 'requested_by', 'applied_at')
    list_filter = ('kind', 'status', 'organization')
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in AIDraft._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIReview)
class AIReviewAdmin(admin.ModelAdmin):
    """Calificaciones sugeridas por la IA: de solo lectura. La nota real vive en ``Grade`` y su historial."""

    list_display = ('created_at', 'organization', 'submission', 'status', 'score', 'final_score', 'replacements', 'confirmed_in_bulk')
    list_filter = ('status', 'confirmed_in_bulk', 'organization')
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in AIReview._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
