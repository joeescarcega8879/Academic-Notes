"""Control de acceso por rol en la organización activa (``request.membership``)."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect


def home_url_name(membership):
    """Nombre de la URL de inicio según el rol de ``membership`` (perfil si no tiene rol operativo)."""
    if membership is not None and membership.is_teacher:
        return 'professor_dashboard'
    if membership is not None and membership.is_student:
        return 'student_dashboard'
    return 'profile'


class OrganizationMemberMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Docentes y alumnos de la organización activa. Sin organización o con otro rol, al inicio de su rol."""

    def test_func(self):
        membership = self.request.membership
        return membership is not None and (membership.is_teacher or membership.is_student)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect(home_url_name(self.request.membership))


class TeacherRequiredMixin(OrganizationMemberMixin):
    """Solo quien da clase en la organización activa."""

    def test_func(self):
        membership = self.request.membership
        return membership is not None and membership.is_teacher


class StudentRequiredMixin(OrganizationMemberMixin):
    """Solo alumnos de la organización activa."""

    def test_func(self):
        membership = self.request.membership
        return membership is not None and membership.is_student
