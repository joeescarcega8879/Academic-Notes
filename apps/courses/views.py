from django.db.models import Count
from django.views.generic import TemplateView, DetailView

from apps.accounts.mixins import OrganizationMemberMixin, StudentRequiredMixin, TeacherRequiredMixin
from apps.grades.services.grading import grade_stats, stats_by_course

from .models import Course, Enrollment

class ProfessorDashboardView(TeacherRequiredMixin, TemplateView):

    template_name = "dashboard-profesor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Evaluation, Grade

        user = self.request.user
        organization = self.request.organization
        courses = list(
            Course.objects
            .for_organization(organization)
            .filter(professor=user)
            .annotate(student_count=Count('enrollments'))
        )
        grades = list(
            Grade.objects
            .for_organization(organization)
            .filter(evaluation__course__professor=user)
            .select_related('evaluation')
        )

        per_course = stats_by_course(grades)
        for course in courses:
            stats = per_course.get(course.pk)
            course.average = stats.average if stats else None
            course.pass_rate = stats.pass_rate if stats else None

        overall = grade_stats(grades)
        context['courses'] = courses
        context['total_evaluations'] = (
            Evaluation.objects.for_organization(organization).filter(course__professor=user).count()
        )
        context['graded_count'] = overall.count
        context['group_average'] = overall.average
        context['pass_rate'] = overall.pass_rate

        context['total_students'] = (
            Enrollment.objects
            .for_organization(organization)
            .filter(course__professor=user)
            .values('student')
            .distinct()
            .count()
        )
        return context

class StudentDashboardView(StudentRequiredMixin, TemplateView):

    template_name = 'dashboard-alumno.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Grade

        user = self.request.user
        organization = self.request.organization
        enrollments = list(
            Enrollment.objects
            .for_organization(organization)
            .filter(student=user)
            .select_related('course', 'course__professor')
        )

        # Promedio ponderado del alumno (general y por materia)
        grades = list(
            Grade.objects.for_organization(organization).filter(student=user).select_related('evaluation')
        )

        per_course = stats_by_course(grades)
        for e in enrollments:
            stats = per_course.get(e.course_id)
            e.course_average = stats.average if stats else None

        context['enrollments'] = enrollments
        context['average'] = grade_stats(grades).average
        return context

class CourseDetailView(OrganizationMemberMixin, DetailView):

    model = Course
    template_name = 'materia.html'
    context_object_name = 'course'

    def get_queryset(self):
        qs = Course.objects.for_organization(self.request.organization)
        user = self.request.user
        if self.request.membership.is_teacher:
            return qs.filter(professor=user)
        return qs.filter(enrollments__student=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['enrollments'] = self.object.enrollments.select_related('student')
        context['my_enrollment'] = self.object.enrollments.filter(student=user).first()

        # Vista alumno: evaluaciones de la materia + su calificación
        if self.request.membership.is_student:
            from apps.grades.models import Grade

            my_grades = {
                g.evaluation_id: g
                for g in Grade.objects.filter(student=user, evaluation__course=self.object).select_related('evaluation')
            }
            rows = [
                {'evaluation': evaluation, 'grade': my_grades.get(evaluation.id)}
                for evaluation in self.object.evaluations.all()
            ]

            context['evaluation_rows'] = rows
            context['course_average'] = grade_stats(my_grades.values()).average
        return context
