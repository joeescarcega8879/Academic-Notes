from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, View
from django.db.models import Count, Max, Q
from django.utils import timezone

from .forms import MessageForm
from .models import Conversation, Message

class MessagingAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ('professor', 'student')

    def handle_no_permission(self):
        user = self.request.user

        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'student':
            return redirect('student_dashboard')
        if user.role == 'professor':
            return redirect('professor_dashboard')
        return redirect('profile')

class ConversationQuerysetMixin:

    def base_queryset(self, user):
        qs = Conversation.objects.select_related('subject', 'student', 'subject__professor')
        if user.role == 'student':
            return qs.filter(student=user)
        return qs.filter(subject__professor=user)

    def conversations_for(self, user):
        return self.base_queryset(user).annotate(
            last_message_at=Max('messages__created_at'),
            unread=Count(
                'messages',
                filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=user),
            ),
        ).order_by('-last_message_at', 'subject__name')

    def group_by_day(self, conversation, user):
        groups = []
        messages = conversation.messages.select_related('sender') if conversation else []
        for message in messages:
            day = timezone.localtime(message.created_at).date()
            if not groups or groups[-1]['day'] != day:
                groups.append({'day': day, 'messages': []})
            groups[-1]['messages'].append(message)
        return groups

    def with_other(self, conversations, user):
        for conversation in conversations:
            conversation.other = conversation.counterpart(user)
        return conversations

    def build_context(self, conversations, conversation, user):
        return {
            'conversations': conversations,
            'active_conversation': conversation,
            'message_groups': self.group_by_day(conversation, user),
            'form': MessageForm(),
        }


class ConversationListView(MessagingAccessMixin, ConversationQuerysetMixin, ListView):
    template_name = 'mensajes.html'
    context_object_name = 'conversations'

    def get_queryset(self):
        return self.conversations_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversations = self.with_other(list(context['conversations']), self.request.user)
        context['conversations'] = conversations
        context.update(self.build_context(conversations, self.pick_active(conversations), self.request.user))
        return context

    def pick_active(self, conversations):
        pk = self.request.GET.get('c')
        if pk:
            for conversation in conversations:
                if str(conversation.pk) == pk:
                    return conversation
        return conversations[0] if conversations else None


class ConversationDetailView(MessagingAccessMixin, ConversationQuerysetMixin, DetailView):
    template_name = 'mensajes.html'
    context_object_name = 'active_conversation'

    def get_queryset(self):
        return self.conversations_for(self.request.user)

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.mark_read(self.object, request.user)
        conversations = self.with_other(list(self.conversations_for(request.user)), request.user)
        context = self.build_context(conversations, self.object, request.user)
        return self.render_to_response(context)

    def mark_read(self, conversation, user):
        conversation.messages.filter(
            read_at__isnull=True,
        ).exclude(sender=user).update(read_at=timezone.now())


class MessageCreateView(MessagingAccessMixin, ConversationQuerysetMixin, View):

    def post(self, request, pk):
        conversation = get_object_or_404(self.base_queryset(request.user), pk=pk)
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.conversation = conversation
            message.sender = request.user
            message.save()
        return redirect('messaging:detail', pk=pk)
        