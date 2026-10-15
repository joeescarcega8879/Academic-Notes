"""Perfil editable para alumno y docente, foto de perfil privada y nombre del producto unificado."""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.accounts import avatars
from apps.accounts.avatars import process_avatar
from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.accounts.models import ProfessorProfile, StudentProfile
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership

pytestmark = pytest.mark.django_db


def imagen(formato='PNG', size=(800, 600), color=(200, 30, 30), mode='RGB', nombre=None, **kwargs):
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, format=formato, **kwargs)
    return SimpleUploadedFile(nombre or f'foto.{formato.lower()}', buffer.getvalue(), content_type=f'image/{formato.lower()}')


def datos(user, **extra):
    return {'first_name': user.first_name or 'Ana', 'last_name': user.last_name or 'Pérez', 'email': user.email, **extra}


def abrir(user):
    user.refresh_from_db()
    with user.avatar.open('rb') as archivo:
        return Image.open(BytesIO(archivo.read()))


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


class TestProcesarFoto:
    def test_queda_cuadrada_jpeg_y_de_512_como_maximo(self):
        resultado = process_avatar(imagen(size=(1600, 900)))
        foto = Image.open(BytesIO(resultado.read()))
        assert foto.format == 'JPEG'
        assert foto.size == (512, 512)

    def test_una_foto_pequena_no_se_amplia(self):
        foto = Image.open(BytesIO(process_avatar(imagen(size=(200, 120))).read()))
        assert foto.size == (120, 120)

    def test_png_con_transparencia_se_pone_sobre_blanco(self):
        foto = Image.open(BytesIO(process_avatar(imagen(mode='RGBA', color=(0, 0, 0, 0), size=(64, 64))).read()))
        assert foto.getpixel((10, 10)) == (255, 255, 255)

    def test_webp_y_jpeg_se_aceptan(self):
        for formato in ('WEBP', 'JPEG'):
            assert Image.open(BytesIO(process_avatar(imagen(formato=formato)).read())).format == 'JPEG'

    def test_se_descartan_los_metadatos_gps(self):
        origen = Image.new('RGB', (100, 100), (10, 120, 10))
        exif = Image.Exif()
        exif[0x8825] = {1: 'N', 2: (19.0, 25.0, 0.0)}  # GPSInfo
        buffer = BytesIO()
        origen.save(buffer, format='JPEG', exif=exif)
        assert Image.open(BytesIO(buffer.getvalue())).getexif().get(0x8825)  # el original sí lo traía
        foto = Image.open(BytesIO(process_avatar(SimpleUploadedFile('f.jpg', buffer.getvalue())).read()))
        assert not foto.getexif().get(0x8825)

    def test_respeta_la_orientacion_del_celular(self):
        origen = Image.new('RGB', (200, 100), (255, 255, 255))
        origen.paste((255, 0, 0), (0, 0, 100, 100))  # mitad izquierda roja
        exif = Image.Exif()
        exif[0x0112] = 6  # «gira 90° a la derecha»: la izquierda pasa arriba
        buffer = BytesIO()
        origen.save(buffer, format='JPEG', exif=exif, quality=95)
        foto = Image.open(BytesIO(process_avatar(SimpleUploadedFile('f.jpg', buffer.getvalue())).read()))
        arriba, abajo = foto.getpixel((50, 10)), foto.getpixel((50, foto.height - 10))
        assert arriba[0] > 200 and arriba[1] < 80  # rojo arriba
        assert abajo[1] > 200  # blanco abajo

    @pytest.mark.parametrize('nombre,contenido', [
        ('foto.jpg', b'esto no es una imagen'),
        ('foto.png', b''),
        ('foto.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        ('foto.jpg', b'\x89PNG\r\n\x1a\n' + b'truncado'),
    ])
    def test_rechaza_lo_que_no_es_una_imagen(self, nombre, contenido):
        with pytest.raises(Exception) as error:
            process_avatar(SimpleUploadedFile(nombre, contenido))
        assert error.type.__name__ == 'ValidationError'

    def test_rechaza_gif_aunque_sea_imagen_valida(self):
        with pytest.raises(Exception, match='JPG, PNG o WebP'):
            process_avatar(imagen(formato='GIF'))

    def test_rechaza_mas_de_5_mb(self):
        grande = SimpleUploadedFile('f.jpg', b'0' * (avatars.MAX_AVATAR_BYTES + 1))
        with pytest.raises(Exception, match='5 MB'):
            process_avatar(grande)

    def test_rechaza_una_imagen_con_demasiados_pixeles(self, monkeypatch):
        monkeypatch.setattr(avatars, 'MAX_AVATAR_PIXELS', 1000)
        with pytest.raises(Exception, match='demasiado grande'):
            process_avatar(imagen(size=(100, 100)))


class TestSubirFoto:
    @pytest.mark.parametrize('fabrica', [StudentFactory, ProfessorFactory], ids=['alumno', 'docente'])
    def test_sube_la_foto_y_se_guarda_procesada(self, fabrica):
        user = fabrica()
        respuesta = cliente(user).post(reverse('profile'), datos(user, avatar=imagen(size=(1200, 800))))
        assert respuesta.status_code == 302
        user.refresh_from_db()
        assert user.avatar and user.avatar.name.startswith(f'{user.pk}/') and user.avatar.name.endswith('.jpg')
        foto = abrir(user)
        assert foto.format == 'JPEG' and foto.size == (512, 512)
        assert user.avatar_url.startswith(reverse('avatar', args=[user.pk]))

    def test_no_se_guarda_con_el_nombre_que_trae_el_archivo(self):
        user = StudentFactory()
        cliente(user).post(reverse('profile'), datos(user, avatar=imagen(nombre='../../etc/passwd.png')))
        user.refresh_from_db()
        assert '..' not in user.avatar.name and 'passwd' not in user.avatar.name

    def test_reemplazar_borra_la_foto_anterior(self):
        user = StudentFactory()
        client = cliente(user)
        client.post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        anterior = user.avatar.name
        client.post(reverse('profile'), datos(user, avatar=imagen(color=(0, 0, 255))))
        user.refresh_from_db()
        assert user.avatar.name != anterior
        assert not user.avatar.storage.exists(anterior)
        assert user.avatar.storage.exists(user.avatar.name)

    def test_quitar_la_foto_borra_el_archivo(self):
        user = StudentFactory()
        client = cliente(user)
        client.post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        archivo = user.avatar.name
        client.post(reverse('profile'), datos(user, remove_avatar='on'))
        user.refresh_from_db()
        assert not user.avatar and user.avatar_url == ''
        assert not user.avatar.storage.exists(archivo)

    def test_guardar_sin_tocar_la_foto_la_conserva(self):
        user = StudentFactory()
        client = cliente(user)
        client.post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        archivo = user.avatar.name
        client.post(reverse('profile'), datos(user, first_name='Otra'))
        user.refresh_from_db()
        assert user.first_name == 'Otra' and user.avatar.name == archivo

    def test_subir_y_quitar_a_la_vez_gana_la_foto_nueva(self):
        user = StudentFactory()
        cliente(user).post(reverse('profile'), datos(user, avatar=imagen(), remove_avatar='on'))
        user.refresh_from_db()
        assert user.avatar

    def test_un_archivo_invalido_no_cambia_nada_y_explica_por_que(self):
        user = StudentFactory()
        client = cliente(user)
        client.post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        archivo = user.avatar.name
        respuesta = client.post(
            reverse('profile'), datos(user, first_name='Cambio', avatar=SimpleUploadedFile('virus.png', b'MZ no soy una foto')),
        )
        assert respuesta.status_code == 200
        assert 'No se pudo leer la imagen' in respuesta.content.decode()
        user.refresh_from_db()
        assert user.avatar.name == archivo and user.first_name != 'Cambio'

    def test_la_foto_aparece_en_la_barra_y_en_el_perfil(self):
        user = ProfessorFactory()
        client = cliente(user)
        client.post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        html = client.get(reverse('profile')).content.decode()
        assert html.count(f'src="{user.avatar_url}"') >= 3  # barra lateral, encabezado y formulario


class TestVerLaFoto:
    @pytest.fixture
    def con_foto(self):
        user = StudentFactory()
        cliente(user).post(reverse('profile'), datos(user, avatar=imagen()))
        user.refresh_from_db()
        return user

    def test_el_dueno_la_ve_con_cabeceras_seguras(self, con_foto):
        respuesta = cliente(con_foto).get(reverse('avatar', args=[con_foto.pk]))
        assert respuesta.status_code == 200
        assert respuesta['Content-Type'] == 'image/jpeg'
        assert respuesta['X-Content-Type-Options'] == 'nosniff'
        assert 'private' in respuesta['Cache-Control']
        assert Image.open(BytesIO(b''.join(respuesta.streaming_content))).format == 'JPEG'

    def test_quien_comparte_organizacion_la_ve(self, con_foto):
        docente = ProfessorFactory()
        organizacion = Membership.objects.get(user=docente).organization
        MembershipFactory(user=con_foto, organization=organizacion)
        assert cliente(docente).get(reverse('avatar', args=[con_foto.pk])).status_code == 200

    def test_alguien_de_otra_organizacion_recibe_404(self, con_foto):
        MembershipFactory(user=con_foto)
        extrano = ProfessorFactory()
        assert cliente(extrano).get(reverse('avatar', args=[con_foto.pk])).status_code == 404

    def test_sin_sesion_va_al_login(self, con_foto):
        respuesta = Client().get(reverse('avatar', args=[con_foto.pk]))
        assert respuesta.status_code == 302 and '/login/' in respuesta.url

    def test_quien_no_tiene_foto_da_404(self):
        user = StudentFactory()
        assert cliente(user).get(reverse('avatar', args=[user.pk])).status_code == 404

    def test_la_foto_no_cuelga_de_media(self, con_foto, settings):
        assert not (settings.MEDIA_ROOT / con_foto.avatar.name).exists()


class TestPerfilSinDatosAcademicos:
    """Las cuentas del registro nuevo no traen perfil de alumno/docente: guardar el perfil no debe fallar por eso."""

    def test_alumno_nuevo_guarda_su_nombre_sin_crear_perfil_vacio(self):
        user = StudentFactory()
        respuesta = cliente(user).post(reverse('profile'), datos(user, first_name='Sofía'))
        assert respuesta.status_code == 302
        user.refresh_from_db()
        assert user.first_name == 'Sofía'
        assert not StudentProfile.objects.filter(user=user).exists()

    def test_alumno_con_solo_el_programa_recibe_un_aviso(self):
        user = StudentFactory()
        respuesta = cliente(user).post(reverse('profile'), datos(user, program='ISC'))
        assert respuesta.status_code == 200
        assert 'Semestre: Completa este dato.' in respuesta.content.decode()
        assert not StudentProfile.objects.filter(user=user).exists()

    def test_alumno_con_programa_y_semestre_lo_crea(self):
        user = StudentFactory()
        cliente(user).post(reverse('profile'), datos(user, program='ISC', semester=4))
        assert StudentProfile.objects.get(user=user).semester == 4

    def test_docente_nuevo_guarda_sin_departamento(self):
        user = ProfessorFactory()
        assert cliente(user).post(reverse('profile'), datos(user)).status_code == 302
        assert not ProfessorProfile.objects.filter(user=user).exists()

    def test_los_errores_se_muestran(self):
        otro = StudentFactory()
        user = StudentFactory()
        respuesta = cliente(user).post(reverse('profile'), datos(user, email=otro.email))
        assert respuesta.status_code == 200
        assert 'No pudimos guardar tus cambios' in respuesta.content.decode()

    def test_confirma_al_guardar(self):
        user = StudentFactory()
        respuesta = cliente(user).post(reverse('profile'), datos(user), follow=True)
        assert 'Guardamos tu perfil.' in respuesta.content.decode()


class TestAccesoAlPerfil:
    @pytest.mark.parametrize('fabrica', [StudentFactory, ProfessorFactory], ids=['alumno', 'docente'])
    def test_la_barra_lateral_lleva_al_perfil(self, fabrica):
        html = cliente(fabrica()).get(reverse('profile')).content.decode()
        assert html.count(f'href="{reverse("profile")}"') >= 2  # tarjeta de la persona y opción «Perfil»

    def test_el_boton_editar_perfil_lleva_al_formulario(self):
        html = cliente(StudentFactory()).get(reverse('profile')).content.decode()
        assert 'href="#editar-perfil"' in html and 'id="editar-perfil"' in html


class TestNombreDelProducto:
    NOMBRE_ANTERIOR = 'Grade' + 'Link'

    @pytest.mark.parametrize('url', ['/', '/login/', '/registro/', '/terminos/', '/privacidad/'])
    def test_las_paginas_publicas_dicen_academic_notes(self, url):
        html = Client().get(url).content.decode()
        assert 'Academic Notes' in html and self.NOMBRE_ANTERIOR not in html

    @pytest.mark.parametrize('fabrica', [StudentFactory, ProfessorFactory], ids=['alumno', 'docente'])
    def test_el_menu_y_los_titulos_dicen_academic_notes(self, fabrica):
        html = cliente(fabrica()).get(reverse('profile')).content.decode()
        assert 'Perfil — Academic Notes' in html or 'Perfil · Academic Notes' in html
        assert '<div class="brand-name">Academic Notes</div>' in html
        assert self.NOMBRE_ANTERIOR not in html
