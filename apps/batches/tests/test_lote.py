"""El lote de PDFs: subir, identificar por la portada, asignar a mano, descartar y guardar como entregas."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.batches.models import BatchFile
from apps.batches.services import batch
from apps.batches.tests.factories import (
    blank_pdf, cover_upload, encrypted_pdf, inscribir, make_pdf, pdf_de, subir, upload,
)
from apps.courses.services.courses import archive_course
from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.models import Activity, Grade, Submission
from apps.grades.services.gradebook import grade_activity
from apps.grades.tests.factories import ActivityFactory

pytestmark = pytest.mark.django_db

Status = BatchFile.Status


# ── Subir e identificar ───────────────────────────────────────────────

class TestIdentificacion:
    def test_la_portada_identifica_al_alumno(self, tarea, ana, beto):
        result = subir(tarea, pdf_de('20240001', nombre='ana.pdf'), pdf_de('20240002', 'Gómez', 'beto.pdf'))
        por_nombre = {f.original_name: f for f in result.created}
        assert por_nombre['ana.pdf'].student == ana and por_nombre['beto.pdf'].student == beto
        for archivo in result.created:
            assert (archivo.status, archivo.identified_by, archivo.pages) == (Status.READY, 'cover', 1)
            assert 'Matrícula' in archivo.cover_text and not archivo.name_mismatch

    def test_no_se_toca_ninguna_entrega_hasta_confirmar(self, tarea, ana):
        subir(tarea, pdf_de('20240001'))
        assert not Submission.objects.exists()

    def test_sin_coincidencia_queda_sin_identificar(self, tarea, ana):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        assert (archivo.status, archivo.student) == (Status.UNIDENTIFIED, None)
        assert 'ningún alumno' in archivo.problem

    def test_la_portada_con_dos_matriculas_queda_sin_identificar(self, tarea, ana, beto):
        archivo = subir(tarea, cover_upload('a.pdf', 'Matrícula 20240001', 'Compañero 20240002')).created[0]
        assert (archivo.status, archivo.student) == (Status.UNIDENTIFIED, None)
        assert 'varios alumnos' in archivo.problem

    def test_una_portada_que_es_imagen_queda_sin_identificar(self, tarea, ana):
        archivo = subir(tarea, upload('escaneo.pdf', blank_pdf())).created[0]
        assert archivo.status == Status.UNIDENTIFIED and 'no tiene texto' in archivo.problem

    def test_sin_paginas_de_portada_todo_se_asigna_a_mano(self, tarea, ana):
        archivo = subir(tarea, pdf_de('20240001'), cover_pages=0).created[0]
        assert archivo.status == Status.UNIDENTIFIED and 'portada' in archivo.problem

    def test_la_matricula_en_la_segunda_pagina_solo_cuenta_con_dos_paginas_de_portada(self, tarea, ana):
        contenido = make_pdf(['Portada'], pages=2, body='Matrícula 20240001')
        assert subir(tarea, upload('a.pdf', contenido), cover_pages=1).created[0].status == Status.UNIDENTIFIED
        assert subir(tarea, upload('b.pdf', contenido), cover_pages=2).created[0].student == ana

    def test_la_matricula_del_cuerpo_no_identifica(self, tarea, ana):
        contenido = make_pdf(['Portada sin datos'], pages=3, body='Matrícula 20240001')
        assert subir(tarea, upload('a.pdf', contenido), cover_pages=1).created[0].status == Status.UNIDENTIFIED

    def test_avisa_si_la_portada_no_trae_el_apellido(self, tarea, ana):
        archivo = subir(tarea, cover_upload('a.pdf', 'Nombre: Juan Rojas', 'Matrícula: 20240001')).created[0]
        assert archivo.status == Status.READY and archivo.student == ana and archivo.name_mismatch

    def test_matricula_con_ceros_y_guiones(self, tarea, course):
        luis = inscribir(course, '0012345', 'Luis', 'Ramos')
        archivo = subir(tarea, cover_upload('a.pdf', 'Ramos Luis', 'Mat. 12-345')).created[0]
        assert archivo.student == luis

    def test_una_matricula_dentro_de_otra_no_coincide(self, tarea, course):
        inscribir(course, '12345', 'Luis', 'Ramos')
        archivo = subir(tarea, cover_upload('a.pdf', 'Ramos', 'Matrícula 123456')).created[0]
        assert archivo.status == Status.UNIDENTIFIED

    def test_alumno_sin_matricula_solo_se_asigna_a_mano(self, tarea, course):
        sin = EnrollmentFactory(course=course, student__user=None, student__student_number='').student
        archivo = subir(tarea, cover_upload('a.pdf', 'Alumno sin matrícula')).created[0]
        assert archivo.status == Status.UNIDENTIFIED
        assign = batch.assign(archivo, sin)
        assert (assign.status, assign.student, assign.identified_by) == (Status.READY, sin, 'manual')

    def test_un_alumno_de_otro_grupo_no_se_identifica(self, tarea, ana):
        otro = EnrollmentFactory(student__user=None, student__student_number='55555555').student
        archivo = subir(tarea, pdf_de(otro.student_number)).created[0]
        assert archivo.status == Status.UNIDENTIFIED


# ── Archivos que no sirven ────────────────────────────────────────────

class TestArchivosInvalidos:
    def test_pdf_con_contrasena(self, tarea, ana):
        archivo = subir(tarea, upload('a.pdf', encrypted_pdf())).created[0]
        assert archivo.status == Status.UNREADABLE and 'contraseña' in archivo.problem and not archivo.file

    def test_pdf_danado(self, tarea):
        archivo = subir(tarea, upload('a.pdf', b'%PDF-1.4\nesto no es un pdf de verdad')).created[0]
        assert archivo.status == Status.UNREADABLE and not archivo.file

    def test_no_es_un_pdf_aunque_se_llame_asi(self, tarea):
        archivo = subir(tarea, upload('a.pdf', b'MZ\x90\x00 programa')).created[0]
        assert archivo.status == Status.UNREADABLE and 'No es un PDF' in archivo.problem

    def test_demasiadas_paginas(self, tarea):
        archivo = subir(tarea, upload('a.pdf', make_pdf(['x'], pages=101))).created[0]
        assert archivo.status == Status.UNREADABLE and '101 páginas' in archivo.problem

    def test_otro_tipo_de_archivo_se_rechaza_sin_entrar_a_la_lista(self, tarea):
        result = subir(tarea, upload('tarea.docx', b'PK\x03\x04'), pdf_de('1'))
        assert result.rejected == [('tarea.docx', 'Solo se aceptan archivos PDF.')]
        assert BatchFile.objects.count() == 1

    def test_un_archivo_de_mas_de_10_mb_se_rechaza(self, tarea):
        grande = SimpleUploadedFile('grande.pdf', b'%PDF-1.4' + b'0' * (10 * 1024 * 1024))
        result = subir(tarea, grande)
        assert result.rejected and '10 MB' in result.rejected[0][1] and not BatchFile.objects.exists()

    def test_un_archivo_malo_no_arruina_a_los_demas(self, tarea, ana):
        result = subir(tarea, upload('mal.pdf', b'%PDF-1.4 roto'), pdf_de('20240001'))
        assert sorted(f.status for f in result.created) == [Status.READY, Status.UNREADABLE]

    def test_un_nombre_con_ruta_se_limpia(self, tarea, ana):
        archivo = subir(tarea, upload('../../etc/pasa\nwd.pdf', make_pdf(['Matrícula 20240001']))).created[0]
        assert archivo.original_name == 'passwd.pdf' or '/' not in archivo.original_name


class TestTopes:
    def test_sin_archivos(self, tarea):
        with pytest.raises(ValidationError, match='al menos un archivo'):
            subir(tarea)

    def test_demasiados_archivos(self, tarea, monkeypatch):
        monkeypatch.setattr(batch, 'MAX_BATCH_FILES', 2)
        with pytest.raises(ValidationError, match='hasta 2 archivos'):
            subir(tarea, *[pdf_de('1', nombre=f'{n}.pdf') for n in range(3)])
        assert not BatchFile.objects.exists()

    def test_la_subida_pesa_demasiado(self, tarea, monkeypatch):
        monkeypatch.setattr(batch, 'MAX_BATCH_BYTES', 1000)
        with pytest.raises(ValidationError, match='Divídela'):
            subir(tarea, pdf_de('1'), pdf_de('2'))
        assert not BatchFile.objects.exists()

    def test_tope_de_archivos_esperando(self, tarea, monkeypatch):
        monkeypatch.setattr(batch, 'MAX_PENDING_FILES', 2)
        subir(tarea, pdf_de('1', nombre='a.pdf'), pdf_de('2', nombre='b.pdf'))
        with pytest.raises(ValidationError, match='esperando'):
            subir(tarea, pdf_de('3', nombre='c.pdf'))

    def test_solo_actividades_con_entrega(self, course):
        participacion = ActivityFactory(course=course, type=Activity.Type.PARTICIPATION)
        with pytest.raises(ValidationError, match='no recibe entregas'):
            subir(participacion, pdf_de('1'))

    def test_un_grupo_archivado_es_de_solo_lectura(self, tarea, course):
        archive_course(course)
        with pytest.raises(ValidationError):
            subir(tarea, pdf_de('1'))


# ── Duplicados y entregas previas ─────────────────────────────────────

class TestDuplicadosYConflictos:
    def test_dos_archivos_con_la_misma_matricula_son_duplicados(self, tarea, ana):
        result = subir(tarea, pdf_de('20240001', nombre='a.pdf'), pdf_de('20240001', nombre='b.pdf'))
        assert {f.status for f in result.created} == {Status.DUPLICATE}
        assert all(f.student == ana and 'más de un archivo' in f.problem for f in result.created)

    def test_el_duplicado_tambien_se_detecta_entre_subidas(self, tarea, ana):
        primero = subir(tarea, pdf_de('20240001', nombre='a.pdf')).created[0]
        subir(tarea, pdf_de('20240001', nombre='b.pdf'))
        primero.refresh_from_db()
        assert primero.status == Status.DUPLICATE

    def test_descartar_uno_deja_listo_al_otro(self, tarea, ana):
        a, b = subir(tarea, pdf_de('20240001', nombre='a.pdf'), pdf_de('20240001', nombre='b.pdf')).created
        batch.discard(a)
        b.refresh_from_db()
        assert b.status == Status.READY and BatchFile.objects.count() == 1

    def test_asignar_a_mano_a_quien_ya_tiene_un_archivo_los_marca_duplicados(self, tarea, ana):
        listo = subir(tarea, pdf_de('20240001', nombre='a.pdf')).created[0]
        suelto = subir(tarea, pdf_de('99999999', nombre='b.pdf')).created[0]
        batch.assign(suelto, ana)
        listo.refresh_from_db()
        suelto.refresh_from_db()
        assert listo.status == suelto.status == Status.DUPLICATE

    def test_reasignar_libera_al_alumno_anterior(self, tarea, ana, beto):
        a, b = subir(tarea, pdf_de('20240001', nombre='a.pdf'), pdf_de('20240001', nombre='b.pdf')).created
        batch.assign(b, beto)
        a.refresh_from_db()
        assert a.status == Status.READY and b.status == Status.READY and b.student == beto

    def test_quien_ya_entrego_en_el_portal_queda_en_conflicto(self, tarea, ana):
        Submission.objects.create(activity=tarea, student=ana, text='mi respuesta', submitted_at=timezone.now())
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        assert archivo.status == Status.CONFLICT and 'Ya entregó' in archivo.problem

    def test_el_docente_puede_pedir_que_reemplace_la_entrega(self, tarea, ana):
        Submission.objects.create(activity=tarea, student=ana, text='mi respuesta', submitted_at=timezone.now())
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        archivo = batch.assign(archivo, ana, replace=True)
        assert archivo.status == Status.READY and archivo.replace

    def test_una_entrega_calificada_no_se_puede_reemplazar(self, tarea, ana):
        Submission.objects.create(activity=tarea, student=ana, text='mi respuesta', submitted_at=timezone.now())
        grade_activity(tarea, ana, score=8)
        archivo = batch.assign(subir(tarea, pdf_de('20240001')).created[0], ana, replace=True)
        assert archivo.status == Status.CONFLICT and not archivo.replace and 'calificada' in archivo.problem

    def test_tener_calificacion_sin_entrega_no_estorba(self, tarea, ana):
        grade_activity(tarea, ana, score=8)
        assert subir(tarea, pdf_de('20240001')).created[0].status == Status.READY


# ── Asignar a mano y descartar ────────────────────────────────────────

class TestAsignarYDescartar:
    def test_asignar_un_sin_identificar(self, tarea, ana):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        archivo = batch.assign(archivo, ana)
        assert (archivo.status, archivo.student, archivo.identified_by) == (Status.READY, ana, 'manual')

    def test_el_alumno_debe_ser_del_grupo(self, tarea, ana):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        ajeno = EnrollmentFactory().student
        with pytest.raises(ValidationError, match='no está en el grupo'):
            batch.assign(archivo, ajeno)

    def test_un_archivo_ilegible_no_se_asigna(self, tarea, ana):
        archivo = subir(tarea, upload('a.pdf', b'%PDF-1.4 roto')).created[0]
        with pytest.raises(ValidationError, match='no se pudo leer'):
            batch.assign(archivo, ana)

    def test_descartar_borra_el_archivo_del_disco(self, tarea, ana):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        storage, nombre = archivo.file.storage, archivo.file.name
        assert storage.exists(nombre)
        batch.discard(archivo)
        assert not storage.exists(nombre) and not BatchFile.objects.exists()


# ── Guardar como entregas ─────────────────────────────────────────────

class TestGuardar:
    def test_crea_las_entregas_sin_penalizacion_aunque_la_fecha_limite_haya_pasado(self, tarea, ana, beto):
        contenido = make_pdf(['Matrícula 20240001'], pages=3)
        subir(tarea, upload('ana.pdf', contenido), pdf_de('20240002', 'Gómez', 'beto.pdf'))
        result = batch.apply(tarea)
        assert result.saved == 2 and not result.skipped
        entrega = Submission.objects.get(activity=tarea, student=ana)
        assert (entrega.original_name, entrega.is_late, entrega.text) == ('ana.pdf', False, '')
        assert entrega.file.read() == contenido
        assert not BatchFile.objects.exists()

    def test_la_entrega_conserva_el_archivo_en_disco(self, tarea, ana):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        nombre = archivo.file.name
        batch.apply(tarea)
        assert Submission.objects.get().file.name == nombre
        assert archivo.file.storage.exists(nombre)

    def test_solo_guarda_los_identificados(self, tarea, ana):
        subir(tarea, pdf_de('20240001', nombre='a.pdf'), pdf_de('99999999', nombre='b.pdf'))
        assert batch.apply(tarea).saved == 1
        assert list(BatchFile.objects.values_list('original_name', 'status')) == [('b.pdf', Status.UNIDENTIFIED)]

    def test_no_guarda_duplicados_ni_conflictos(self, tarea, ana, beto):
        Submission.objects.create(activity=tarea, student=beto, text='portal', submitted_at=timezone.now())
        subir(tarea, pdf_de('20240001', nombre='a.pdf'), pdf_de('20240001', nombre='b.pdf'), pdf_de('20240002', 'Gómez', 'c.pdf'))
        assert batch.apply(tarea).saved == 0
        assert BatchFile.objects.count() == 3

    def test_reemplazar_conserva_el_texto_y_borra_el_archivo_anterior(self, tarea, ana):
        previa = Submission(activity=tarea, student=ana, text='mi respuesta', submitted_at=timezone.now(), is_late=True)
        previa.file.save('viejo.pdf', SimpleUploadedFile('viejo.pdf', make_pdf(['viejo'])), save=False)
        previa.original_name = 'viejo.pdf'
        previa.save()
        viejo = previa.file.name
        archivo = subir(tarea, pdf_de('20240001', nombre='nuevo.pdf')).created[0]
        batch.assign(archivo, ana, replace=True)
        assert batch.apply(tarea).saved == 1
        previa.refresh_from_db()
        assert (previa.text, previa.original_name, previa.is_late) == ('mi respuesta', 'nuevo.pdf', True)
        assert not previa.file.storage.exists(viejo) and previa.file.storage.exists(previa.file.name)
        assert Submission.objects.count() == 1

    def test_si_el_alumno_entrego_mientras_tanto_no_se_pisa(self, tarea, ana):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        Submission.objects.create(activity=tarea, student=ana, text='llegó primero', submitted_at=timezone.now())
        result = batch.apply(tarea)
        assert result.saved == 0 and 'entregó mientras tanto' in result.skipped[0][1]
        archivo.refresh_from_db()
        assert archivo.status == Status.CONFLICT and Submission.objects.get().text == 'llegó primero'

    def test_si_la_entrega_se_califico_mientras_tanto_no_se_reemplaza(self, tarea, ana):
        Submission.objects.create(activity=tarea, student=ana, text='portal', submitted_at=timezone.now())
        archivo = batch.assign(subir(tarea, pdf_de('20240001')).created[0], ana, replace=True)
        grade_activity(tarea, ana, score=7)
        result = batch.apply(tarea)
        assert result.saved == 0 and 'calificada' in result.skipped[0][1]
        assert Submission.objects.get().text == 'portal' and BatchFile.objects.filter(pk=archivo.pk).exists()

    def test_la_entrega_guardada_se_puede_calificar_y_ver(self, professor_client, tarea, ana):
        subir(tarea, pdf_de('20240001'))
        batch.apply(tarea)
        filas = professor_client.get(reverse('grades:activity_grading', args=[tarea.pk])).context['rows']
        assert [f['submission'] is not None for f in filas if f['student'] == ana] == [True]

    def test_sin_nada_que_guardar(self, tarea):
        assert batch.apply(tarea).saved == 0

    def test_un_grupo_archivado_no_guarda(self, tarea, course, ana):
        subir(tarea, pdf_de('20240001'))
        archive_course(course)
        with pytest.raises(ValidationError):
            batch.apply(tarea)
        assert not Submission.objects.exists()

    def test_otras_calificaciones_no_se_tocan(self, tarea, ana):
        subir(tarea, pdf_de('20240001'))
        batch.apply(tarea)
        assert not Grade.objects.exists()


# ── Pantallas ─────────────────────────────────────────────────────────

def url(nombre, pk):
    return reverse(f'batches:{nombre}', args=[pk])


class TestPantalla:
    def test_el_docente_ve_la_pagina(self, professor_client, tarea, ana):
        subir(tarea, pdf_de('20240001', nombre='ana.pdf'), pdf_de('99999999', nombre='x.pdf'))
        response = professor_client.get(url('index', tarea.pk))
        html = response.content.decode()
        assert response.status_code == 200 and 'ana.pdf' in html and 'x.pdf' in html
        assert 'Guardar 1 entrega' in html and 'Ver la portada' in html and 'Sin identificar' in html

    def test_sube_varios_archivos_y_avisa(self, professor_client, tarea, ana):
        response = professor_client.post(url('index', tarea.pk), {
            'files': [pdf_de('20240001', nombre='a.pdf'), pdf_de('99999999', nombre='b.pdf')], 'cover_pages': '1',
        }, follow=True)
        assert response.redirect_chain[-1][0] == url('index', tarea.pk)
        assert any('2 archivos: 1 identificado' in str(m) for m in response.context['messages'])
        assert BatchFile.objects.count() == 2

    def test_recuerda_las_paginas_de_portada_en_la_actividad(self, professor_client, tarea, ana):
        professor_client.post(url('index', tarea.pk), {'files': [pdf_de('20240001')], 'cover_pages': '2'})
        tarea.refresh_from_db()
        assert tarea.cover_pages == 2
        professor_client.post(url('index', tarea.pk), {'files': [pdf_de('20240001', nombre='b.pdf')], 'cover_pages': '0'})
        tarea.refresh_from_db()
        assert tarea.cover_pages == 0

    @pytest.mark.parametrize('valor', ['7', 'dos', '-1', '²', ''])
    def test_un_valor_raro_de_portada_se_ignora(self, professor_client, tarea, ana, valor):
        professor_client.post(url('index', tarea.pk), {'files': [pdf_de('20240001')], 'cover_pages': valor})
        tarea.refresh_from_db()
        assert tarea.cover_pages == 1 and BatchFile.objects.count() == 1

    def test_sin_archivos_muestra_el_error(self, professor_client, tarea):
        response = professor_client.post(url('index', tarea.pk), {}, follow=True)
        assert any('al menos un archivo' in str(m) for m in response.context['messages'])

    def test_asignar_descartar_y_guardar(self, professor_client, tarea, ana):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        professor_client.post(url('assign', archivo.pk), {'student': ana.pk})
        archivo.refresh_from_db()
        assert archivo.student == ana and archivo.status == Status.READY
        response = professor_client.post(url('apply', tarea.pk), follow=True)
        assert any('Se guardó 1 entrega' in str(m) for m in response.context['messages'])
        assert Submission.objects.filter(student=ana).exists()
        otro = subir(tarea, pdf_de('99999999', nombre='otro.pdf')).created[0]
        professor_client.post(url('discard', otro.pk))
        assert not BatchFile.objects.exists()

    def test_asignar_sin_elegir_alumno(self, professor_client, tarea, ana):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        response = professor_client.post(url('assign', archivo.pk), {'student': ''}, follow=True)
        assert any('Elige a un alumno' in str(m) for m in response.context['messages'])
        archivo.refresh_from_db()
        assert archivo.student is None

    @pytest.mark.parametrize('valor', ['abc', '²', '99999999999999999999999'])
    def test_alumno_invalido_no_da_error_500(self, professor_client, tarea, valor):
        archivo = subir(tarea, pdf_de('99999999')).created[0]
        assert professor_client.post(url('assign', archivo.pk), {'student': valor}).status_code == 302

    def test_guardar_sin_nada_lo_dice(self, professor_client, tarea):
        response = professor_client.post(url('apply', tarea.pk), follow=True)
        assert any('No hay archivos identificados' in str(m) for m in response.context['messages'])

    def test_descargar_el_pdf(self, professor_client, tarea, ana):
        contenido = make_pdf(['Matrícula 20240001'])
        archivo = subir(tarea, upload('ana.pdf', contenido)).created[0]
        response = professor_client.get(url('file', archivo.pk))
        assert response.status_code == 200 and b''.join(response.streaming_content) == contenido
        assert 'attachment' in response['Content-Disposition'] and response['X-Content-Type-Options'] == 'nosniff'
        assert response['Content-Type'] == 'application/octet-stream'

    def test_un_archivo_sin_leer_no_se_descarga(self, professor_client, tarea):
        archivo = subir(tarea, upload('a.pdf', b'%PDF-1.4 roto')).created[0]
        assert professor_client.get(url('file', archivo.pk)).status_code == 404

    def test_el_nombre_del_archivo_no_se_interpreta_como_html(self, professor_client, tarea):
        subir(tarea, cover_upload('<img src=x onerror=alert(1)>.pdf', 'Nada'))
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert '<img src=x' not in html and '&lt;img src=x' in html

    def test_la_portada_se_muestra_escapada(self, professor_client, tarea):
        subir(tarea, cover_upload('a.pdf', '<script>alert(1)</script>'))
        html = professor_client.get(url('index', tarea.pk)).content.decode()
        assert '<script>alert(1)</script>' not in html

    def test_la_actividad_enlaza_al_lote(self, professor_client, tarea, ana):
        subir(tarea, pdf_de('20240001'))
        html = professor_client.get(tarea.get_absolute_url()).content.decode()
        assert url('index', tarea.pk) in html and 'Lote de PDFs (1)' in html

    def test_una_participacion_no_tiene_lote(self, professor_client, course):
        participacion = ActivityFactory(course=course, type=Activity.Type.PARTICIPATION)
        assert url('index', participacion.pk) and professor_client.get(url('index', participacion.pk)).status_code == 404
        assert url('index', participacion.pk) not in professor_client.get(participacion.get_absolute_url()).content.decode()

    def test_grupo_archivado_no_ofrece_lote(self, professor_client, tarea, course):
        archive_course(course)
        assert professor_client.get(url('index', tarea.pk)).status_code == 404
        assert url('index', tarea.pk) not in professor_client.get(tarea.get_absolute_url()).content.decode()


class TestPermisos:
    RUTAS = ('index', 'apply')

    def test_el_alumno_no_entra(self, student_client, tarea, enrollment):
        archivo = subir(tarea, pdf_de('1')).created[0]
        for nombre, pk in (('index', tarea.pk), ('apply', tarea.pk), ('assign', archivo.pk), ('discard', archivo.pk), ('file', archivo.pk)):
            assert student_client.get(url(nombre, pk)).status_code in (302, 403, 404, 405), nombre
            assert student_client.post(url(nombre, pk), {}).status_code in (302, 403, 404), nombre
        assert BatchFile.objects.filter(pk=archivo.pk).exists()

    def test_el_anonimo_va_al_login(self, client, tarea):
        assert client.get(url('index', tarea.pk)).url.startswith('/login/')

    def test_otro_docente_no_ve_ni_toca_el_lote(self, tarea, ana):
        from django.test import Client

        from apps.accounts.tests.factories import ProfessorFactory

        archivo = subir(tarea, pdf_de('20240001')).created[0]
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert otro.get(url('index', tarea.pk)).status_code == 404
        assert otro.post(url('index', tarea.pk), {'files': [pdf_de('1')]}).status_code == 404
        assert otro.post(url('apply', tarea.pk)).status_code == 404
        assert otro.post(url('assign', archivo.pk), {'student': ana.pk}).status_code == 404
        assert otro.post(url('discard', archivo.pk)).status_code == 404
        assert otro.get(url('file', archivo.pk)).status_code == 404
        assert BatchFile.objects.get(pk=archivo.pk).status == Status.READY

    def test_otro_docente_de_la_misma_organizacion_tampoco(self, tarea, ana, course):
        from django.test import Client

        from apps.accounts.tests.factories import ProfessorFactory
        from apps.organizations.models import Membership
        from apps.organizations.services import SESSION_KEY
        from apps.organizations.tests.factories import MembershipFactory

        archivo = subir(tarea, pdf_de('20240001')).created[0]
        colega = ProfessorFactory()
        MembershipFactory(user=colega, organization=course.organization, role=Membership.Role.TEACHER)
        cliente = Client()
        cliente.force_login(colega)
        sesion = cliente.session
        sesion[SESSION_KEY] = course.organization_id
        sesion.save()
        assert cliente.get(url('index', tarea.pk)).status_code == 404
        assert cliente.get(url('file', archivo.pk)).status_code == 404
        assert cliente.post(url('discard', archivo.pk)).status_code == 404
        assert cliente.post(url('assign', archivo.pk), {'student': ana.pk}).status_code == 404
        assert BatchFile.objects.filter(pk=archivo.pk).exists()

    def test_los_borrados_y_cambios_exigen_post(self, professor_client, tarea, ana):
        archivo = subir(tarea, pdf_de('20240001')).created[0]
        for nombre, pk in (('apply', tarea.pk), ('assign', archivo.pk), ('discard', archivo.pk)):
            assert professor_client.get(url(nombre, pk)).status_code == 405, nombre
