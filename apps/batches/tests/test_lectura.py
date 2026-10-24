"""Lectura del contenido de los PDF del lote: texto digital, OCR, «Legible a medias» y el paso por Celery."""

import io
import json

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from apps.accounts.tests.factories import ProfessorFactory
from apps.batches import tasks
from apps.batches.models import BatchFile
from apps.batches.services import batch, ocr, reading
from apps.batches.tests.factories import (
    blank_pdf, make_pdf, mixed_pdf, pdf_de, scan_pdf, subir, upload,
)
from apps.grades.models import Submission

pytestmark = pytest.mark.django_db

Status = BatchFile.Status
ReadStatus = Submission.ReadStatus

CUERPO = 'La revolución industrial transformó la producción de bienes en toda Europa durante el siglo XIX.'
PORTADA = ['Nombre: Ana Pérez', 'Matrícula: 20240001']


def url(nombre, pk):
    return reverse(f'batches:{nombre}', args=[pk])


class OcrFalso:
    """Un Tesseract de mentira: cada página devuelve lo que la prueba dejó en ``paginas`` (o lanza si es un error)."""

    def __init__(self, paginas):
        self.paginas = paginas

    def __call__(self, data):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, index):
        pagina = self.paginas.get(index, ocr.OcrPage('', None, 0))
        if isinstance(pagina, Exception):
            raise pagina
        return pagina


def pagina(texto, confianza=90.0):
    return ocr.OcrPage(texto, confianza, len(texto.split()))


@pytest.fixture
def ocr_falso(monkeypatch):
    paginas = {}
    monkeypatch.setattr(ocr, 'available', lambda: True)
    monkeypatch.setattr(ocr, 'Scan', OcrFalso(paginas))
    return paginas


@pytest.fixture
def sin_encolar(monkeypatch):
    """Celery todavía no leyó nada: los archivos se quedan «Leyendo» hasta que la prueba llame a ``process_file``."""
    monkeypatch.setattr(batch, '_enqueue', lambda pk: None)


# ── El cuerpo ─────────────────────────────────────────────────────────

class TestLecturaDelCuerpo:
    def test_el_texto_digital_se_lee_tal_cual(self):
        cuerpo = reading.read_body(make_pdf(['Portada'], pages=3, body=CUERPO), 1)
        assert cuerpo.status == ReadStatus.TEXT and cuerpo.confidence is None and cuerpo.note == ''
        assert 'revolución industrial' in cuerpo.text

    def test_la_portada_no_es_parte_del_cuerpo(self):
        cuerpo = reading.read_body(make_pdf(['Matrícula: 20240001'], pages=2, body=CUERPO), 1)
        assert '20240001' not in cuerpo.text

    def test_sin_portada_el_cuerpo_empieza_en_la_primera_pagina(self):
        cuerpo = reading.read_body(make_pdf([CUERPO + ' Otra vez.'], pages=1), 0)
        assert cuerpo.status == ReadStatus.TEXT and 'revolución' in cuerpo.text

    def test_un_pdf_de_solo_portada_no_tiene_cuerpo(self):
        cuerpo = reading.read_body(make_pdf(['Portada']), 1)
        assert cuerpo.status == ReadStatus.EMPTY and cuerpo.text == ''

    def test_paginas_escaneadas_se_leen_con_ocr(self, ocr_falso):
        ocr_falso[1], ocr_falso[2] = pagina(CUERPO, 91), pagina(CUERPO, 85)
        cuerpo = reading.read_body(blank_pdf(3), 1)
        assert cuerpo.status == ReadStatus.OCR and 'revolución' in cuerpo.text and cuerpo.note == ''
        assert cuerpo.confidence == pytest.approx(88, abs=0.5)

    def test_la_confianza_pesa_por_palabras_leidas(self, ocr_falso):
        ocr_falso[1] = ocr.OcrPage('palabra ' * 100, 90.0, 100)
        ocr_falso[2] = ocr.OcrPage('palabra ' * 10, 30.0, 10)
        assert reading.read_body(blank_pdf(3), 1).confidence == pytest.approx(84.5, abs=0.1)

    def test_poca_confianza_es_legible_a_medias(self, ocr_falso):
        ocr_falso[1] = pagina(CUERPO, 41)
        cuerpo = reading.read_body(blank_pdf(2), 1)
        assert cuerpo.status == ReadStatus.PARTIAL and 'poca confianza' in cuerpo.note and cuerpo.confidence == 41

    def test_casi_sin_texto_es_legible_a_medias(self, ocr_falso):
        ocr_falso[1] = pagina('a b', 80)
        cuerpo = reading.read_body(blank_pdf(2), 1)
        assert cuerpo.status == ReadStatus.PARTIAL and 'Casi no salió texto' in cuerpo.note

    def test_una_pagina_que_falla_no_tumba_las_demas(self, ocr_falso):
        ocr_falso[1], ocr_falso[2] = ocr.OcrError('se colgó'), pagina(CUERPO, 90)
        cuerpo = reading.read_body(blank_pdf(3), 1)
        assert cuerpo.status == ReadStatus.OCR and '1 página sin leer' in cuerpo.note

    def test_sin_ocr_las_imagenes_quedan_a_medias_y_se_dice_por_que(self):
        cuerpo = reading.read_body(blank_pdf(3), 1)
        assert cuerpo.status == ReadStatus.PARTIAL
        assert '2 páginas sin leer' in cuerpo.note and 'no tiene OCR' in cuerpo.note

    def test_la_portada_escaneada_se_lee_con_ocr(self, ocr_falso):
        ocr_falso[0] = pagina('Matrícula: 20240001')
        assert reading.ocr_cover(blank_pdf(1), 1) == 'Matrícula: 20240001'

    def test_sin_ocr_o_sin_portada_no_hay_texto_de_portada(self, ocr_falso):
        ocr_falso[0] = pagina('Matrícula: 20240001')
        assert reading.ocr_cover(blank_pdf(1), 0) == ''

    def test_sin_ocr_la_portada_sale_vacia(self):
        assert reading.ocr_cover(blank_pdf(1), 1) == ''

    def test_una_pagina_de_la_portada_que_falla_no_rompe(self, ocr_falso):
        ocr_falso[0], ocr_falso[1] = ocr.OcrError('x'), pagina('20240001')
        assert reading.ocr_cover(blank_pdf(2), 2) == '20240001'


# ── Del archivo subido al estado ──────────────────────────────────────

class TestProcesoDelArchivo:
    def test_sube_leyendo_y_celery_le_da_su_estado(self, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        assert archivo.status == Status.READING and archivo.student is None
        batch.process_file(archivo.pk)
        archivo.refresh_from_db()
        assert archivo.status == Status.READY and archivo.student == ana

    def test_leer_dos_veces_no_cambia_nada(self, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        batch.process_file(archivo.pk)
        antes = BatchFile.objects.values().get(pk=archivo.pk)
        batch.process_file(archivo.pk)
        assert BatchFile.objects.values().get(pk=archivo.pk) == antes

    def test_la_portada_escaneada_se_identifica_con_ocr(self, tarea, ana, ocr_falso):
        ocr_falso[0] = pagina('Nombre: Ana Pérez\nMatrícula: 20240001')
        archivo = subir(tarea, upload('escaneo.pdf', blank_pdf(2))).created[0]
        assert archivo.status == Status.READY and archivo.student == ana
        assert archivo.identified_by == BatchFile.IdentifiedBy.COVER and '20240001' in archivo.cover_text

    def test_portada_escaneada_sin_ocr_se_asigna_a_mano(self, tarea, ana):
        archivo = subir(tarea, upload('escaneo.pdf', blank_pdf(1))).created[0]
        assert archivo.status == Status.UNIDENTIFIED and 'no tiene OCR' in archivo.problem

    def test_ocr_que_no_encuentra_texto_en_la_portada(self, tarea, ana, ocr_falso):
        archivo = subir(tarea, upload('escaneo.pdf', blank_pdf(1))).created[0]
        assert archivo.status == Status.UNIDENTIFIED and 'ni con OCR' in archivo.problem

    def test_si_falla_la_lectura_queda_sin_leer_en_lugar_de_leyendo(self, tarea, ana, monkeypatch):
        def falla(*args):
            raise RuntimeError('se rompió')

        monkeypatch.setattr(reading, 'read_body', falla)
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        assert archivo.status == Status.UNREADABLE and 'No se pudo leer' in archivo.problem

    def test_el_cuerpo_queda_en_el_archivo(self, tarea, ana):
        archivo = subir(tarea, upload('a.pdf', make_pdf(PORTADA, pages=3, body=CUERPO))).created[0]
        assert archivo.body_status == ReadStatus.TEXT and 'revolución' in archivo.body_text and archivo.ocr_confidence is None

    def test_si_lo_descartan_justo_mientras_se_lee_no_se_revive(self, tarea, ana, sin_encolar, monkeypatch):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        leer = reading.read_body

        def descartan_a_media_lectura(*args):
            BatchFile.objects.filter(pk=archivo.pk).delete()
            return leer(*args)

        monkeypatch.setattr(reading, 'read_body', descartan_a_media_lectura)
        batch.process_file(archivo.pk)
        assert not BatchFile.objects.exists()

    def test_descartar_mientras_se_lee_no_deja_nada(self, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        batch.discard(archivo)
        batch.process_file(archivo.pk)
        assert not BatchFile.objects.exists()

    def test_no_se_asigna_mientras_se_lee(self, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        with pytest.raises(ValidationError, match='se está leyendo'):
            batch.assign(archivo, ana)

    def test_guardar_no_toma_lo_que_aun_se_lee(self, tarea, ana, sin_encolar):
        subir(tarea, pdf_de('20240001'))
        assert batch.apply(tarea).saved == 0 and not Submission.objects.exists()

    def test_sin_broker_se_lee_en_la_peticion(self, tarea, ana, monkeypatch):
        def sin_broker(*args, **kwargs):
            raise ConnectionError('no hay redis')

        monkeypatch.setattr(tasks.read_batch_file, 'delay', sin_broker)
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        assert archivo.status == Status.READY and archivo.student == ana

    def test_dos_archivos_del_mismo_alumno_son_duplicados_aunque_se_lean_por_separado(self, tarea, ana, sin_encolar):
        uno, dos = (a for a in subir(tarea, pdf_de('20240001', nombre='1.pdf'), pdf_de('20240001', nombre='2.pdf')).created)
        batch.process_file(uno.pk)
        assert BatchFile.objects.get(pk=uno.pk).status == Status.READY
        batch.process_file(dos.pk)
        assert set(BatchFile.objects.values_list('status', flat=True)) == {Status.DUPLICATE}

    def test_guardar_pasa_la_lectura_a_la_entrega(self, tarea, ana):
        subir(tarea, upload('a.pdf', make_pdf(PORTADA, pages=3, body=CUERPO)))
        assert batch.apply(tarea).saved == 1
        entrega = Submission.objects.get(activity=tarea, student=ana)
        assert entrega.read_status == ReadStatus.TEXT and 'revolución' in entrega.body_text
        assert 'Matrícula' not in entrega.body_text

    def test_guardar_pasa_la_confianza_del_ocr(self, tarea, ana, ocr_falso):
        ocr_falso[1] = pagina(CUERPO, 77)
        subir(tarea, upload('a.pdf', mixed_pdf(PORTADA, ['x'])))
        batch.apply(tarea)
        entrega = Submission.objects.get(activity=tarea, student=ana)
        assert entrega.read_status == ReadStatus.OCR and entrega.ocr_confidence == 77

    def test_reemplazar_una_entrega_actualiza_lo_leido(self, tarea, ana):
        Submission.objects.create(activity=tarea, student=ana, text='hola', submitted_at=timezone.now())
        archivo = subir(tarea, upload('a.pdf', make_pdf(PORTADA, pages=3, body=CUERPO))).created[0]
        assert archivo.status == Status.CONFLICT
        batch.assign(archivo, ana, replace=True)
        batch.apply(tarea)
        entrega = Submission.objects.get(activity=tarea, student=ana)
        assert entrega.read_status == ReadStatus.TEXT and 'revolución' in entrega.body_text


class TestOcrUnidades:
    TSV = (
        'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        '4\t1\t1\t1\t1\t0\t0\t0\t5\t5\t50\tno es una palabra\n'
        '5\t1\t1\t1\t1\t1\t0\t0\t5\t5\t96.5\tHola\n'
        '5\t1\t1\t1\t1\t2\t0\t0\t5\t5\t-1\tsin_confianza\n'
        '5\t1\t1\t1\t1\t3\t0\t0\t5\t5\t80\tmundo\n'
        '5\t1\t1\t1\t2\t1\t0\t0\t5\t5\t70\tsegunda\n'
        '5\t1\t1\t1\t2\t2\t0\t0\t5\t5\t90\t   \n'
    )

    def test_el_tsv_se_agrupa_por_lineas_y_solo_cuentan_palabras_leidas(self):
        pagina = ocr._parse_tsv(self.TSV)
        assert pagina.text == 'Hola mundo\nsegunda' and pagina.words == 3
        assert pagina.confidence == pytest.approx((96.5 + 80 + 70) / 3)

    def test_sin_palabras_no_hay_confianza(self):
        assert ocr._parse_tsv('level\tx\n') == ocr.OcrPage('', None, 0)

    def test_una_pagina_enorme_se_reduce_antes_del_ocr(self, monkeypatch):
        vistas = []
        monkeypatch.setattr(ocr, 'recognize', lambda imagen: vistas.append(imagen.size) or ocr.OcrPage('', None, 0))
        writer = PdfWriter()
        writer.add_blank_page(width=5000, height=3000)
        buffer = io.BytesIO()
        writer.write(buffer)
        with ocr.Scan(buffer.getvalue()) as scan:
            scan.read(0)
        assert max(vistas[0]) <= ocr.MAX_SIDE_PX


# ── Con Tesseract de verdad (se omiten donde no está instalado) ───────

@pytest.fixture
def ocr_real(settings):
    settings.OCR_ENABLED = True
    ocr._has_language.cache_clear()
    if not ocr.available():
        pytest.skip('Tesseract con el idioma español no está instalado')
    yield
    ocr._has_language.cache_clear()


class TestOcrReal:
    def test_la_portada_escaneada_identifica_al_alumno(self, ocr_real, tarea, ana):
        archivo = subir(tarea, upload('escaneo.pdf', scan_pdf(['Nombre: Ana Perez', 'Matricula: 20240001']))).created[0]
        assert archivo.status == Status.READY and archivo.student == ana

    def test_el_cuerpo_escaneado_se_lee(self, ocr_real, tarea, ana):
        pdf = mixed_pdf(PORTADA, [
            'La revolucion industrial cambio la forma de producir en Europa',
            'y las fabricas crecieron muy rapido en las ciudades del norte.',
        ])
        archivo = subir(tarea, upload('a.pdf', pdf)).created[0]
        assert archivo.body_status == ReadStatus.OCR and 'revolucion' in archivo.body_text.lower()
        assert archivo.ocr_confidence >= reading.MIN_CONFIDENCE

    def test_paginas_en_blanco_son_legibles_a_medias(self, ocr_real, tarea, ana):
        archivo = subir(tarea, upload('a.pdf', mixed_pdf(PORTADA, [], []))).created[0]
        assert archivo.status == Status.READY and archivo.body_status == ReadStatus.PARTIAL

    def test_un_pdf_roto_no_cuelga_el_ocr(self, ocr_real):
        with pytest.raises(ocr.OcrError):
            with ocr.Scan(make_pdf(['x'])) as scan:
                scan.read(7)


# ── La pantalla ───────────────────────────────────────────────────────

class TestPantallaDeLectura:
    def test_el_estado_dice_si_siguen_leyendo(self, professor_client, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        assert json.loads(professor_client.get(url('status', tarea.pk)).content) == {'busy': True}
        batch.process_file(archivo.pk)
        assert json.loads(professor_client.get(url('status', tarea.pk)).content) == {'busy': False}

    def test_la_pagina_se_actualiza_sola_solo_mientras_lee(self, professor_client, tarea, ana, sin_encolar):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert 'data-batch-poll' in html and 'Leyendo…' in html and url('status', tarea.pk) in html
        assert 'Guardar 1 entrega' not in html
        batch.process_file(archivo.pk)
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert 'data-batch-poll' not in html and 'Guardar 1 entrega' in html

    def test_al_subir_avisa_que_se_esta_leyendo(self, professor_client, tarea, ana, sin_encolar):
        response = professor_client.post(
            url('index', tarea.pk), {'files': [pdf_de('20240001'), pdf_de('20240002')], 'cover_pages': '1'}, follow=True,
        )
        assert any('Se subieron 2 archivos y se están leyendo' in str(m) for m in response.context['messages'])

    def test_muestra_como_se_leyo_el_cuerpo(self, professor_client, tarea, ana):
        subir(tarea, upload('a.pdf', make_pdf(PORTADA, pages=3, body=CUERPO)))
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert 'Texto digital' in html and 'Ver el texto leído' in html and 'revolución industrial' in html

    def test_muestra_la_confianza_y_el_aviso_de_legible_a_medias(self, professor_client, tarea, ana, ocr_falso):
        ocr_falso[1] = pagina(CUERPO, 41)
        subir(tarea, upload('a.pdf', mixed_pdf(PORTADA, ['x'])))
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert 'Legible a medias' in html and '41 % de confianza' in html and 'poca confianza' in html

    def test_el_texto_leido_se_muestra_escapado(self, professor_client, tarea, ana):
        subir(tarea, upload('a.pdf', make_pdf(PORTADA, pages=2, body='<script>alert(1)</script> ' * 4)))
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert '<script>alert(1)</script>' not in html and '&lt;script&gt;alert(1)' in html

    def test_la_pantalla_dice_si_este_servidor_tiene_ocr(self, professor_client, tarea, ocr_falso):
        assert 'ninguna imagen sale a un tercero' in professor_client.get(url('index', tarea.pk)).content.decode()

    def test_sin_ocr_la_pantalla_lo_avisa(self, professor_client, tarea):
        assert 'no tiene OCR' in professor_client.get(url('index', tarea.pk)).content.decode()

    def test_el_estado_es_solo_del_docente_del_grupo(self, student_client, client, tarea, enrollment):
        assert student_client.get(url('status', tarea.pk)).status_code in (302, 403, 404)
        assert client.get(url('status', tarea.pk)).url.startswith('/login/')
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert otro.get(url('status', tarea.pk)).status_code == 404
