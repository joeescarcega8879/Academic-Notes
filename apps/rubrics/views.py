"""Rúbricas: la biblioteca del docente, su editor y la calificación de entregas con una rúbrica."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.services.text import sort_enrollments
from apps.grades.activity_views import OwnActiveCourseMixin
from apps.grades.models import Grade, Submission
from core.utils import parse_id

from .models import Rubric, RubricVersion
from .services import editor, library
from .services.grading import COMMENT_MAX, adjusted_by_hand, grade_with_rubric, panel_rows


class OwnRubricMixin(TeacherRequiredMixin):
    """Las rúbricas son del docente que las crea, en la organización activa."""

    def rubrics(self):
        return Rubric.objects.for_organization(self.request.organization).filter(author=self.request.user).prefetch_related(
            Prefetch('versions', queryset=RubricVersion.objects.prefetch_related('criteria__levels')),
        )

    def get_rubric(self, pk):
        return get_object_or_404(self.rubrics(), pk=pk)


class RubricListView(OwnRubricMixin, View):
    def get(self, request):
        archived = request.GET.get('archivadas') == '1'
        query = request.GET.get('q', '').strip()
        return render(request, 'rubric_list.html', {
            'rows': library.library_rows(request.user, request.organization, archived=archived, query=query),
            'archived': archived, 'query': query, 'templates': editor.TEMPLATES,
            'archived_count': library.rubrics_of(request.user, request.organization, archived=True).count(),
        })


class RubricDetailView(OwnRubricMixin, View):
    def get(self, request, pk):
        rubric = self.get_rubric(pk)
        version = rubric.current_version
        activities = library.activities_using(rubric)
        return render(request, 'rubric_detail.html', {
            'rubric': rubric, 'version': version, 'rows': panel_rows(version), 'activities': activities,
            'locked': library.is_graded(version), 'versions': sorted(rubric.versions.all(), key=lambda v: -v.number),
        })


class RubricEditorView(OwnRubricMixin, View):
    """Crear o editar: un mismo formulario con la cuadrícula de criterios por niveles."""

    def get_draft(self, request, rubric):
        if rubric is not None:
            return editor.draft_from_version(rubric.current_version)
        return editor.template_draft(request.GET.get('plantilla', '')) or editor.blank_draft()

    def page(self, request, rubric, draft, errors=()):
        version = rubric.current_version if rubric else None
        for criterion in draft['criteria']:  # cada celda lleva el nombre de su nivel (se ve en el celular)
            for level, cell in zip(draft['levels'], criterion['cells'], strict=True):
                cell['level'] = level
        return render(request, 'rubric_form.html', {
            'rubric': rubric, 'draft': draft, 'errors': errors, 'locked': bool(version and library.is_graded(version)),
            'limits': {
                'min_levels': editor.MIN_LEVELS, 'max_levels': editor.MAX_LEVELS, 'max_criteria': editor.MAX_CRITERIA,
            },
            'next_version': version.number + 1 if version else 1,
        })

    def get(self, request, pk=None):
        rubric = self.get_rubric(pk) if pk else None
        return self.page(request, rubric, self.get_draft(request, rubric))

    def post(self, request, pk=None):
        rubric = self.get_rubric(pk) if pk else None
        draft = editor.parse_post(request.POST)
        errors, clean = editor.validate(draft)
        if errors:
            return self.page(request, rubric, draft, errors)
        if rubric is None:
            rubric = library.create_rubric(organization=request.organization, author=request.user, draft=clean)
            messages.success(request, f'Se creó la rúbrica «{rubric.name}».')
        else:
            version, new = library.save_rubric(rubric, clean)
            if new:
                messages.success(
                    request, f'Se guardó como versión {version.number}. Lo que ya calificaste con la anterior no cambia.',
                )
            else:
                messages.success(request, 'Se guardaron los cambios de la rúbrica.')
        return redirect(rubric)


class RubricDuplicateView(OwnRubricMixin, View):
    def post(self, request, pk):
        copy = library.duplicate(self.get_rubric(pk), author=request.user)
        messages.success(request, f'Se creó «{copy.name}». Ya puedes editarla.')
        return redirect('rubrics:update', pk=copy.pk)


class RubricArchiveView(OwnRubricMixin, View):
    """Archiva (deja de ofrecerse al armar actividades) o restaura. Lo ya calificado con ella no cambia."""

    def post(self, request, pk):
        rubric = self.get_rubric(pk)
        library.set_archived(rubric, not rubric.is_archived)
        if rubric.is_archived:
            messages.success(request, f'«{rubric.name}» quedó archivada: ya no se ofrece al crear actividades.')
            return redirect('rubrics:list')
        messages.success(request, f'«{rubric.name}» volvió a la biblioteca.')
        return redirect(rubric)


class RubricDeleteView(OwnRubricMixin, View):
    def post(self, request, pk):
        rubric = self.get_rubric(pk)
        try:
            library.delete_rubric(rubric)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return redirect(rubric)
        messages.success(request, f'Se eliminó «{rubric.name}».')
        return redirect('rubrics:list')


# ── Calificar con rúbrica ─────────────────────────────────────────────

class RubricActivityMixin(OwnActiveCourseMixin):
    def get_activity(self, pk):
        return get_object_or_404(self.activities().filter(rubric_version__isnull=False).select_related('rubric_version__rubric'), pk=pk)

    def student_rows(self, activity):
        grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
        submissions = {s.student_id: s for s in Submission.objects.filter(activity=activity)}
        enrollments = sort_enrollments(activity.course.enrollments.select_related('student__user'))
        return [
            {'student': e.student, 'grade': grades.get(e.student_id), 'submission': submissions.get(e.student_id)}
            for e in enrollments
        ]


class RubricGradeListView(RubricActivityMixin, View):
    """Los alumnos del grupo con el estado de su calificación; cada uno se califica en su propia pantalla."""

    def get(self, request, pk):
        activity = self.get_activity(pk)
        return render(request, 'rubric_grade_list.html', {
            'activity': activity, 'course': activity.course, 'rows': self.student_rows(activity),
            'version': activity.rubric_version,
        })


class RubricGradeStudentView(RubricActivityMixin, View):
    def context(self, activity, student, rows, *, chosen=None, comments=None, feedback=None, waive=None, error=None):
        grade = next((row['grade'] for row in rows if row['student'].pk == student.pk), None)
        submission = next((row['submission'] for row in rows if row['student'].pk == student.pk), None)
        panel = panel_rows(activity.rubric_version, grade)
        for row in panel:
            criterion_id = row['criterion'].pk
            if comments is not None:
                row['comment'] = comments.get(criterion_id, '')
            if chosen is not None:
                for cell in row['levels']:
                    cell['selected'] = chosen.get(criterion_id) == cell['level'].pk
        penalizable = bool(submission and submission.is_late and activity.allow_late and activity.late_penalty)
        return {
            'activity': activity, 'course': activity.course, 'student': student, 'grade': grade, 'submission': submission,
            'version': activity.rubric_version, 'rows': panel, 'penalizable': penalizable,
            'feedback': grade.feedback if feedback is None and grade else (feedback or ''),
            'waive': (grade is not None and not grade.late_penalty) if waive is None else waive,
            'adjusted': bool(grade and adjusted_by_hand(grade)), 'error': error, 'comment_max': COMMENT_MAX,
            'next_student': self.next_student(rows, student),
        }

    @staticmethod
    def next_student(rows, student):
        """El siguiente alumno sin calificar después de ``student`` en el orden de la lista (None si no queda ninguno)."""
        order = [row['student'].pk for row in rows]
        after = order[order.index(student.pk) + 1:] if student.pk in order else []
        pending = {row['student'].pk for row in rows if row['grade'] is None}
        return next((pk for pk in after if pk in pending), None)

    def student(self, activity, student_pk):
        enrollment = get_object_or_404(activity.course.enrollments.select_related('student__user'), student_id=student_pk)
        return enrollment.student

    def get(self, request, pk, student_pk):
        activity = self.get_activity(pk)
        student = self.student(activity, student_pk)
        return render(request, 'rubric_grade.html', self.context(activity, student, self.student_rows(activity)))

    def post(self, request, pk, student_pk):
        activity = self.get_activity(pk)
        student = self.student(activity, student_pk)
        rows = self.student_rows(activity)
        criteria = [row['criterion'] for row in panel_rows(activity.rubric_version)]
        chosen = {c.pk: parse_id(request.POST.get(f'c_{c.pk}', '')) for c in criteria}
        comments = {c.pk: request.POST.get(f'n_{c.pk}', '') for c in criteria}
        feedback = request.POST.get('feedback', '')
        waive = request.POST.get('waive') == 'on'
        try:
            grade_with_rubric(
                activity, student, choices=chosen, comments=comments, feedback=feedback, by=request.user, waive_penalty=waive,
            )
        except ValidationError as error:
            context = self.context(
                activity, student, rows, chosen=chosen, comments=comments, feedback=feedback, waive=waive,
                error=' '.join(error.messages),
            )
            return render(request, 'rubric_grade.html', context)
        messages.success(request, f'Se guardó la calificación de {student}.')
        following = self.next_student(rows, student) if 'siguiente' in request.POST else None
        if following is not None:
            return redirect('rubrics:grade_student', pk=activity.pk, student_pk=following)
        return redirect(activity)
