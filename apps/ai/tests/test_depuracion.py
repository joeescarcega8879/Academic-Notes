"""Depurar el trabajo antes de mandarlo a la IA: nombres, matrículas, correos, teléfonos y CURP salen como marcadores."""

import re
import unicodedata

import pytest

from apps.ai import redaction
from apps.ai.redaction import Redactor


def depurar(texto, **reglas):
    return Redactor(**reglas).apply(texto)


class TestNombres:
    @pytest.mark.parametrize('texto', [
        'Hola, soy Ana María Torres.', 'HOLA, SOY ANA MARÍA TORRES.', 'hola, soy ana maria torres.',
        'Torres Ana María presenta este trabajo.', 'Ana-María Torres',
    ])
    def test_el_nombre_en_cualquier_forma_se_cambia(self, texto):
        resultado = depurar(texto, names=['Ana María', 'Torres'])
        assert 'ana' not in resultado.text.lower() and 'torres' not in resultado.text.lower()
        assert resultado.replacements >= 1

    def test_con_la_tilde_suelta_tambien(self):
        texto = unicodedata.normalize('NFD', 'Escribe José Pérez')
        assert depurar(texto, names=['José', 'Pérez']).text == 'Escribe [NOMBRE]'

    def test_el_nombre_completo_cuenta_como_una_sola_mencion(self):
        resultado = depurar('Ana María Torres Ruiz entrega.', names=['Ana María', 'Torres Ruiz'])
        assert resultado.text == '[NOMBRE] entrega.' and resultado.replacements == 1

    def test_dos_menciones_separadas_son_dos(self):
        resultado = depurar('Ana dice que Torres tiene razón.', names=['Ana', 'Torres'])
        assert resultado.text == '[NOMBRE] dice que [NOMBRE] tiene razón.' and resultado.replacements == 2

    def test_no_toca_palabras_que_solo_contienen_el_nombre(self):
        resultado = depurar('Anabel y Lunares hablaron del anatema.', names=['Ana', 'Luna'])
        assert resultado.text == 'Anabel y Lunares hablaron del anatema.' and resultado.replacements == 0

    @pytest.mark.parametrize('particula', ['de', 'la', 'del', 'y', 'De La'])
    def test_las_particulas_no_identifican_a_nadie(self, particula):
        assert depurar('El centro de la ciudad y del campo', names=[particula]).replacements == 0

    def test_las_palabras_de_una_o_dos_letras_no_se_sustituyen(self):
        assert depurar('Li y Wu van al río', names=['Li', 'Wu']).replacements == 0

    def test_nombres_de_companeros_y_del_docente(self):
        resultado = depurar('Con Beto Gómez y la maestra Rocha.', names=['Beto', 'Gómez', 'Rocha'])
        assert resultado.text == 'Con [NOMBRE] y la maestra [NOMBRE].'


class TestMatriculas:
    @pytest.mark.parametrize('texto', [
        'Mi matrícula es 20240001.', 'Matrícula: 2024-0001', 'Matrícula 2024 0001', 'matricula 020240001', 'ID 2024.0001',
    ])
    def test_la_matricula_con_o_sin_separadores_o_ceros(self, texto):
        resultado = depurar(texto, numbers=['2024-0001'])
        assert '[MATRÍCULA]' in resultado.text and '0001' not in resultado.text

    def test_no_se_cambia_si_es_parte_de_otro_numero(self):
        assert depurar('Folio 120240001 y 202400012.', numbers=['20240001']).replacements == 0

    def test_con_letras(self):
        assert depurar('Soy A-2024-77', numbers=['A202477']).text == 'Soy [MATRÍCULA]'

    def test_una_matricula_corta_no_se_busca(self):
        """«40» o «7» aparecen en cualquier texto: cambiarlos destruiría el trabajo."""
        assert depurar('Son 40 alumnos y 7 grupos', numbers=['40', '007']).replacements == 0

    def test_una_matricula_con_ceros_y_pocos_digitos_solo_se_cambia_tal_cual(self):
        assert depurar('Tengo 00040 y 40', numbers=['00040']).text == 'Tengo [MATRÍCULA] y 40'


class TestOtrosDatos:
    def test_correos(self):
        resultado = depurar('Escríbeme a ana.torres+tarea@escuela.edu.mx o a otro@x.com.', emails=['ana.torres@gmail.com'])
        assert resultado.text == 'Escríbeme a [CORREO] o a [CORREO].' and resultado.replacements == 2

    def test_el_correo_conocido_se_cambia_aunque_sea_raro(self):
        assert depurar('Mi correo: ana@x', emails=['ana@x']).text == 'Mi correo: [CORREO]'

    @pytest.mark.parametrize('telefono', ['55 1234 5678', '5512345678', '(55) 1234-5678', '+52 55 1234 5678', '55-1234-5678'])
    def test_telefonos(self, telefono):
        assert depurar(f'Llámame al {telefono} por favor').text == 'Llámame al [TELÉFONO] por favor'

    def test_curp(self):
        assert depurar('Mi CURP es TORA010203MDFRZN09.').text == 'Mi CURP es [CURP].'
        assert depurar('mi curp: tora010203mdfrzn09').text == 'mi curp: [CURP]'

    @pytest.mark.parametrize('numero', ['555 123 4567', '555-123-4567'])
    def test_telefonos_con_lada_de_tres_cifras(self, numero):
        assert depurar(f'Tel. {numero}.').text == 'Tel. [TELÉFONO].'

    def test_un_texto_normal_no_se_toca(self):
        texto = 'En 2024 se sembraron 1500 árboles, el 12.5 % de ellos en 3 años; cuesta $1,250.00.'
        resultado = depurar(texto)
        assert resultado.text == texto and resultado.replacements == 0

    def test_sin_texto(self):
        assert depurar('').text == '' and depurar(None).replacements == 0


class TestPorAlumno:
    def test_un_correo_raro_conocido_tambien_se_cambia(self, course, professor):
        from apps.batches.tests.factories import inscribir

        ana = inscribir(course, '20240001', 'Ana', 'Pérez')
        beto = inscribir(course, '20240002', 'Beto', 'Gómez')
        beto.email = 'beto@localhost'
        beto.save()
        professor.email = 'maestra@aula'
        regla = redaction.redactor_for(ana, [ana, beto], professor)
        assert regla.apply('Escríbele a beto@localhost o a maestra@aula').text == 'Escríbele a [CORREO] o a [CORREO]'

    def test_reune_al_alumno_a_sus_companeros_y_al_docente(self, course, professor):
        from apps.batches.tests.factories import inscribir

        ana = inscribir(course, '20240001', 'Ana', 'Pérez')
        beto = inscribir(course, '20240002', 'Beto', 'Gómez')
        regla = redaction.redactor_for(ana, [ana, beto], professor)
        texto = f'Ana Pérez (20240001) y Beto Gómez (2024-0002) con {professor.last_name}: {ana.email}'
        resultado = regla.apply(texto)
        datos = ('Ana', 'Pérez', 'Beto', 'Gómez', '20240001', '20240002', professor.first_name, professor.last_name, ana.email)
        sin_marcadores = re.sub(r'\[[^\]]+\]', '', resultado.text).lower()  # el docente de las fábricas se llama «Nombre»
        for dato in filter(None, datos):
            assert dato.lower() not in sin_marcadores, dato
