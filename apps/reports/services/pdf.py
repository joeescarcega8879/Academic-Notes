"""Boleta en PDF (reportlab: Python puro, sin dependencias del sistema).

Se dibuja con la fuente Helvetica incorporada: cubre el español y el latín de Europa occidental. Un carácter
que no esté en ese juego (un nombre en otro alfabeto) sale como «?» en vez de como un cuadro negro.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor('#1b2a3d')
MUTED = colors.HexColor('#6b7788')
BRAND = colors.HexColor('#1e3a5f')
SOFT = colors.HexColor('#eef1f6')
LINE = colors.HexColor('#d5dae3')
OK = colors.HexColor('#1c8a54')
BAD = colors.HexColor('#c43030')

_base = getSampleStyleSheet()['Normal']
BODY = ParagraphStyle('body', parent=_base, fontName='Helvetica', fontSize=9.5, leading=12, textColor=INK)
SMALL = ParagraphStyle('small', parent=BODY, fontSize=8, leading=10, textColor=MUTED)
BOLD = ParagraphStyle('bold', parent=BODY, fontName='Helvetica-Bold')
RIGHT = ParagraphStyle('right', parent=BODY, alignment=TA_RIGHT)
RIGHT_BOLD = ParagraphStyle('right-bold', parent=BOLD, alignment=TA_RIGHT)
HEAD = ParagraphStyle('head', parent=BODY, fontName='Helvetica-Bold', textColor=colors.white)
HEAD_RIGHT = ParagraphStyle('head-right', parent=HEAD, alignment=TA_RIGHT)
TITLE = ParagraphStyle('title', parent=BODY, fontName='Helvetica-Bold', fontSize=17, leading=21, textColor=BRAND)
ORG = ParagraphStyle('org', parent=BODY, fontName='Helvetica-Bold', fontSize=11, textColor=MUTED)
ACTIVITY = ParagraphStyle('activity', parent=BODY, leftIndent=12, fontSize=9)

PAGE_WIDTH = LETTER[0] - 4 * cm


def clean(text):
    """Texto seguro para un ``Paragraph``: sin marcado y solo con caracteres que la fuente sabe dibujar."""
    return escape(str(text).encode('cp1252', 'replace').decode('cp1252'))


def _p(text, style=BODY):
    return Paragraph(clean(text), style)


def _student_title(transcript):
    student = transcript.student
    number = f' · Matrícula {student.student_number}' if student.student_number else ''
    return f'{student}{number}'


def _scores_table(transcript):
    rows = [[_p('Concepto', HEAD), _p('Peso', HEAD_RIGHT), _p('Calificación', HEAD_RIGHT)]]
    styles = [
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 1), (-1, -1), 0.4, LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    scale = f'/ {transcript.scale_max}'
    for period in transcript.periods:
        if transcript.multiple_periods:
            rows.append([_p(period.name, BOLD), _p(f'{period.weight} %', RIGHT_BOLD), ''])
            styles.append(('BACKGROUND', (0, len(rows) - 1), (-1, len(rows) - 1), SOFT))
        for criterion in period.criteria:
            value = f'{criterion.value} {scale}' if criterion.value else '—'
            rows.append([_p(criterion.name, BOLD), _p(f'{criterion.weight} %', RIGHT), _p(value, RIGHT_BOLD)])
            for line in criterion.lines:
                title = f'{line.title} ({line.type_label})'
                if line.graded:
                    score = f'{line.score_text} / {line.max_score}'
                    detail = f'<br/><font size="7.5" color="#6b7788">{clean(line.note)}</font>' if line.note else ''
                    rows.append([Paragraph(clean(title) + detail, ACTIVITY), '', _p(score, RIGHT)])
                else:
                    rows.append([_p(title, ACTIVITY), '', _p('Sin calificar', ParagraphStyle('pending', parent=RIGHT, textColor=MUTED))])
            if not criterion.lines:
                rows.append([_p('Sin actividades publicadas', ParagraphStyle('empty', parent=ACTIVITY, textColor=MUTED)), '', ''])
    table = Table(rows, colWidths=[PAGE_WIDTH * 0.62, PAGE_WIDTH * 0.14, PAGE_WIDTH * 0.24], repeatRows=1)
    table.setStyle(TableStyle(styles))
    return table


def _final_box(transcript):
    colour = {True: OK, False: BAD}.get(transcript.passed, MUTED)
    final = f'{transcript.final} / {transcript.scale_max}' if transcript.final else '—'
    value = ParagraphStyle('final', parent=BOLD, fontSize=20, leading=24, textColor=colour)
    status = ParagraphStyle('status', parent=BOLD, fontSize=11, textColor=colour, alignment=TA_RIGHT)
    box = Table(
        [[_p('Calificación final', BOLD), _p(final, value), _p(transcript.status, status)]],
        colWidths=[PAGE_WIDTH * 0.34, PAGE_WIDTH * 0.33, PAGE_WIDTH * 0.33],
    )
    box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.8, colour), ('BACKGROUND', (0, 0), (-1, -1), SOFT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    return box


def _story_for(transcript):
    course = transcript.course
    info = Table([
        [_p('Alumno', SMALL), _p(_student_title(transcript), BOLD)],
        [_p('Grupo', SMALL), _p(f'{course.name} ({course.code})')],
        [_p('Ciclo escolar', SMALL), _p(transcript.academic_year)],
        [_p('Docente', SMALL), _p(transcript.professor)],
    ], colWidths=[PAGE_WIDTH * 0.2, PAGE_WIDTH * 0.8])
    info.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1), ('LEFTPADDING', (0, 0), (0, -1), 0)]))
    notes = (
        f'Mínimo aprobatorio: {transcript.pass_mark} de {transcript.scale_max}. La calificación final se calcula con los pesos '
        'de cada criterio; solo cuentan las actividades publicadas que ya tienen calificación.'
    )
    return [
        _p(transcript.organization_name, ORG), Spacer(1, 2), _p('Boleta de calificaciones', TITLE), Spacer(1, 10),
        info, Spacer(1, 12), _scores_table(transcript), Spacer(1, 14), _final_box(transcript), Spacer(1, 8), _p(notes, SMALL),
    ]


def render_transcripts(transcripts, *, compress=True):
    """PDF (bytes) con una boleta por alumno, cada una en su propia página. ``compress=False`` deja el texto legible (pruebas)."""
    buffer = BytesIO()
    first = transcripts[0] if transcripts else None
    generated = first.generated_on.strftime('%d/%m/%Y') if first else ''

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, clean(f'Generado el {generated} con GradeLink'))
        canvas.drawRightString(LETTER[0] - 2 * cm, 1.2 * cm, f'Página {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
        title=clean(f'Boleta · {first.course.name}') if first else 'Boleta', author='GradeLink', pageCompression=1 if compress else 0,
    )
    story = []
    for index, transcript in enumerate(transcripts):
        if index:
            story.append(PageBreak())
        story.extend(_story_for(transcript))
    if not story:
        story = [_p('Este grupo no tiene alumnos inscritos.')]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
