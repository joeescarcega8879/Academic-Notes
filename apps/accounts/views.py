from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.urls import NoReverseMatch, reverse
from django.views import View

from .forms import LoginForm, ProfileForm, StudentProfileForm, ProfessorProfileForm
from .models import User

class LoginView(View):
    template_name = 'login.html'
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect(self._dashboard_url(request.user))
        return render(request, self.template_name, {'form': LoginForm()})
    
    def post(self, request):
        form = LoginForm(request, data=request.POST)
        role = request.POST.get('role')
        
        if form.is_valid():
            user = form.get_user()
            if role and user.role != role:
                return render(request, self.template_name, {
                    'form': form,
                    'error': 'El rol seleccionado no coincide con esta cuenta.',
                })
            
            login(request, user)
            return redirect(self._dashboard_url(user))
        return render(request, self.template_name, {'form': form})
    
    def _dashboard_url(self, user):
        name = 'professor_dashboard' if user.role == User.Role.PROFESSOR else 'student_dashboard'
        try:
            return reverse(name)
        except NoReverseMatch:
            # Los dashboards llegan en la Fase 3; hasta entonces, al perfil.
            return reverse('profile')
    
class LogoutView(View):
    
    def get(self, request):
        logout(request)
        return redirect('login')
    
class ProfileView(LoginRequiredMixin, View):
    template_name = 'perfil.html'
    login_url = '/login/'
    
    def get(self, request):
        profile_form = ProfileForm(instance=request.user)
        if request.user.role == User.Role.STUDENT:
            eform = StudentProfileForm(instance=getattr(request.user, 'student_profile', None))
        else:
            eform = ProfessorProfileForm(instance=getattr(request.user, 'professor_profile', None))
        return render(request, self.template_name, {'profile_form': profile_form, 'extra_form': eform})
    
    def post(self, request):
        pform = ProfileForm(request.POST, request.FILES, instance=request.user)
        if request.user.role == User.Role.STUDENT:
            eform = StudentProfileForm(request.POST, instance=getattr(request.user, 'student_profile', None))
        else:
            eform = ProfessorProfileForm(request.POST, instance=getattr(request.user, 'professor_profile', None))
        if pform.is_valid() and eform.is_valid():
            pform.save()
            extra = eform.save(commit=False)
            extra.user = request.user
            extra.save()
            return redirect('profile')
        return render(request, self.template_name, {'profile_form': pform, 'extra_form': eform})