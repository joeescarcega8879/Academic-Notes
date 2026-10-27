"""Proyectos por equipos: el docente arma los equipos y los califica con la rúbrica; el alumno ve el suyo en la actividad."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.grades.activity_views import OwnActiveCourseMixin
from apps.grades.models import Grade
from apps.rubrics.services.grading import COMMENT_MAX, panel_rows
from core.utils import parse_id

from .services import grading, teams
from .services.grading import adjusted_members


class TeamsMixin(OwnActiveCourseMixin):
    """El docente del grupo (activo) y solo para proyectos que se entregan por equipos."""

    def get_activity(self, pk):
        return get_object_or_404(self.activities().filter(by_teams=True).select_related('rubric_version__rubric'), pk=pk)

    @staticmethod
    def get_team(activity, team_pk):
        return get_object_or_404(activity.teams.select_related('activity__course'), pk=team_pk)


# ── Armar los equipos ─────────────────────────────────────────────────

class TeamsView(TeamsMixin, View):
    def get(self, request, pk):
        activity = self.get_activity(pk)
        rows, unassigned = teams.overview(activity)
        others = [
            other for other in self.activities().filter(course=activity.course, by_teams=True).exclude(pk=activity.pk)
            if other.teams.exists()
        ]
        # Equipos de unos 4: la mitad de los alumnos sin equipo como máximo, y al menos 2.
        default_count = max(2, min(len(unassigned), round(len(unassigned) / 4)))
        return render(request, 'teams.html', {
            'activity': activity, 'course': activity.course, 'rows': rows, 'unassigned': unassigned,
            'default_count': default_count,
            'others': others, 'student_count': activity.course.enrollments.count(), 'team_count': len(rows),
        })


class TeamActionView(TeamsMixin, View):
    """Una acción sobre los equipos: se hace por POST y se vuelve a la pantalla de equipos con el resultado."""

    def run(self, request, activity, **kwargs):
        raise NotImplementedError

    def post(self, request, pk, **kwargs):
        activity = self.get_activity(pk)
        try:
            message = self.run(request, activity, **kwargs)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, message)
        return redirect('teams:index', pk)


class TeamCreateView(TeamActionView):
    def run(self, request, activity):
        team = teams.create_team(activity, request.POST.get('name', ''))
        return f'Se creó «{team}».'


class TeamRandomView(TeamActionView):
    def run(self, request, activity):
        count = parse_id(request.POST.get('count', ''))
        if count is None:
            raise ValidationError('Escribe cuántos equipos quieres.')
        created = teams.split_randomly(activity, count)
        return f'Se repartieron los alumnos sin equipo en {len(created)} equipos nuevos.'


class TeamCopyView(TeamActionView):
    def run(self, request, activity):
        source_id = parse_id(request.POST.get('source', ''))
        source = get_object_or_404(
            self.activities().filter(course=activity.course, by_teams=True), pk=source_id if source_id is not None else 0,
        )
        copied = teams.copy_teams(source, activity)
        return f'Se copiaron {copied} equipos de «{source.title}».'


class TeamAssignView(TeamActionView):
    """Pone a un alumno en un equipo, o lo deja sin equipo si no se elige ninguno."""

    def run(self, request, activity):
        student_id = parse_id(request.POST.get('student', ''))
        enrollment = get_object_or_404(
            activity.course.enrollments.select_related('student'), student_id=student_id if student_id is not None else 0,
        )
        team_id = parse_id(request.POST.get('team', ''))
        team = self.get_team(activity, team_id) if team_id is not None else None
        teams.assign(activity, enrollment.student, team)
        return f'{enrollment.student} está en «{team}».' if team else f'{enrollment.student} quedó sin equipo.'


class TeamRenameView(TeamActionView):
    def run(self, request, activity, team_pk):
        team = teams.rename_team(self.get_team(activity, team_pk), request.POST.get('name', ''))
        return f'El equipo ahora se llama «{team}».'


class TeamDeleteView(TeamActionView):
    def run(self, request, activity, team_pk):
        team = self.get_team(activity, team_pk)
        teams.delete_team(team)
        return f'Se borró «{team}»; sus integrantes quedaron sin equipo.'


# ── Calificar por equipo ──────────────────────────────────────────────

class TeamGradeMixin(TeamsMixin):
    def rows(self, activity):
        """Un renglón por equipo (con integrantes) y quiénes de sus integrantes ya tienen nota."""
        grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
        rows = []
        for row in teams.overview(activity)[0]:
            members = row['members']
            member_grades = [grades[s.pk] for s in members if s.pk in grades]
            rows.append({
                'team': row['team'], 'members': members, 'submission': row['submission'], 'grades': member_grades,
                # La nota del equipo es la que salió de la rúbrica; los ajustes a mano son de cada alumno.
                'team_grade': next((g for g in member_grades if g.source == Grade.Source.RUBRIC), None),
                'adjusted': adjusted_members(activity, row['team']),
                'graded': all(s.pk in grades for s in members) and bool(members),
            })
        return rows


class TeamGradeListView(TeamGradeMixin, View):
    """Los equipos del proyecto con su entrega y su calificación; cada uno se califica en su pantalla."""

    def get(self, request, pk):
        activity = self.get_activity(pk)
        grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
        unassigned = [{'student': e.student, 'grade': grades.get(e.student_id)} for e in teams.unassigned_enrollments(activity)]
        return render(request, 'teams_grade_list.html', {
            'activity': activity, 'course': activity.course, 'rows': self.rows(activity), 'unassigned': unassigned,
            'version': activity.rubric_version,
        })


class TeamGradeView(TeamGradeMixin, View):
    template_name = 'rubric_grade.html'

    def context(self, activity, team, rows, *, chosen=None, comments=None, feedback=None, waive=None, replace=None, error=None):
        row = next(r for r in rows if r['team'].pk == team.pk)
        # Lo que ya se calificó con la rúbrica se muestra como punto de partida (los ajustes a mano no son de la rúbrica).
        grade = row['team_grade']
        panel = panel_rows(activity.rubric_version, grade)
        for item in panel:
            criterion_id = item['criterion'].pk
            if comments is not None:
                item['comment'] = comments.get(criterion_id, '')
            if chosen is not None:
                for cell in item['levels']:
                    cell['selected'] = chosen.get(criterion_id) == cell['level'].pk
        submission = row['submission']
        penalizable = bool(submission and submission.is_late and activity.allow_late and activity.late_penalty)
        return {
            'activity': activity, 'course': activity.course, 'team': team, 'members': row['members'], 'grade': grade,
            'submission': submission, 'version': activity.rubric_version, 'rows': panel, 'penalizable': penalizable,
            'feedback': grade.feedback if feedback is None and grade else (feedback or ''),
            'waive': (grade is not None and not grade.late_penalty) if waive is None else waive,
            'adjusted_members': row['adjusted'], 'replace': bool(replace), 'error': error, 'comment_max': COMMENT_MAX,
            'next_team': self.next_team(rows, team),
        }

    @staticmethod
    def next_team(rows, team):
        """El siguiente equipo sin calificar después de ``team`` (None si no queda ninguno)."""
        order = [row['team'].pk for row in rows]
        after = order[order.index(team.pk) + 1:] if team.pk in order else []
        pending = {row['team'].pk for row in rows if row['members'] and not row['grades']}
        return next((pk for pk in after if pk in pending), None)

    def get(self, request, pk, team_pk):
        activity = self.get_activity(pk)
        team = self.get_team(activity, team_pk)
        return render(request, self.template_name, self.context(activity, team, self.rows(activity)))

    def post(self, request, pk, team_pk):
        activity = self.get_activity(pk)
        team = self.get_team(activity, team_pk)
        rows = self.rows(activity)
        criteria = [item['criterion'] for item in panel_rows(activity.rubric_version)]
        chosen = {c.pk: parse_id(request.POST.get(f'c_{c.pk}', '')) for c in criteria}
        comments = {c.pk: request.POST.get(f'n_{c.pk}', '') for c in criteria}
        feedback = request.POST.get('feedback', '')
        waive = request.POST.get('waive') == 'on'
        replace = request.POST.get('replace') == 'on'
        try:
            result = grading.grade_team(
                activity, team, choices=chosen, comments=comments, feedback=feedback, by=request.user,
                waive_penalty=waive, replace_adjusted=replace,
            )
        except ValidationError as error:
            context = self.context(
                activity, team, rows, chosen=chosen, comments=comments, feedback=feedback, waive=waive, replace=replace,
                error=' '.join(error.messages),
            )
            return render(request, self.template_name, context)
        message = f'Se guardó la calificación de «{team}» para {len(result.graded)} integrantes.'
        if result.kept:
            message += ' Se conservó el ajuste a mano de ' + ', '.join(str(s) for s in result.kept) + '.'
        messages.success(request, message)
        following = self.next_team(rows, team) if 'siguiente' in request.POST else None
        if following is not None:
            return redirect('teams:grade', pk=activity.pk, team_pk=following)
        return redirect('teams:grade_list', pk=activity.pk)
