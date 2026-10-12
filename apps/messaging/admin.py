from django.contrib import admin
from .models import Conversation, Message

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ('sender', 'body', 'created_at', 'read_at')
    readonly_fields = ('created_at',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('course', 'student', 'created_at')
    list_filter = ('course',)
    search_fields = ('course__name', 'student__username', 'student__email')
    autocomplete_fields = ('course', 'student')
    inlines = [MessageInline]

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender', 'created_at', 'read_at')
    list_filter = ('read_at',)
    search_fields = ('body', 'sender__username', 'sender__email')
    autocomplete_fields = ('conversation', 'sender')
    readonly_fields = ('created_at',)