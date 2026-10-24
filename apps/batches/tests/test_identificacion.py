"""Identificar al alumno buscando las matrículas exactas del grupo en el texto de la portada."""

from types import SimpleNamespace

import pytest

from apps.batches.services.identify import match_students, name_matches


def alumno(pk, numero, apellido='Pérez'):
    return SimpleNamespace(pk=pk, student_number=numero, last_name=apellido, first_name='Ana')


def encontrados(texto, *alumnos):
    return [a.pk for a in match_students(texto, alumnos)]


class TestMatricula:
    def test_la_encuentra_en_la_portada(self):
        assert encontrados('Nombre: Ana Pérez\nMatrícula: 20240001\nGrupo 3B', alumno(1, '20240001')) == [1]

    def test_sin_coincidencia_no_asigna_a_nadie(self):
        assert encontrados('Matrícula: 99999999', alumno(1, '20240001')) == []

    @pytest.mark.parametrize('escrita', ['2024 0001', '2024-0001', '2024_0001', '2024.0001', '2 0 2 4 0 0 0 1', 'MATRICULA 20240001.'])
    def test_ignora_espacios_guiones_y_puntos_entre_los_caracteres(self, escrita):
        assert encontrados(f'Matrícula: {escrita}', alumno(1, '20240001')) == [1]

    def test_ignora_mayusculas_en_matriculas_con_letras(self):
        assert encontrados('mat. a01234567', alumno(1, 'A01234567')) == [1]

    @pytest.mark.parametrize(('guardada', 'escrita'), [
        ('0012345', '12345'), ('12345', '0012345'), ('012345', '00012345'), ('0012345', '012345'),
    ])
    def test_los_ceros_a_la_izquierda_no_importan(self, guardada, escrita):
        assert encontrados(f'Matrícula {escrita}', alumno(1, guardada)) == [1]

    def test_no_coincide_dentro_de_una_matricula_mas_larga(self):
        assert encontrados('Matrícula: 123456', alumno(1, '12345')) == []

    def test_no_coincide_pegada_a_letras(self):
        assert encontrados('Folio A12345', alumno(1, '12345')) == []
        assert encontrados('Clave 12345B', alumno(1, '12345')) == []

    def test_la_matricula_larga_gana_a_la_que_es_su_parte_inicial(self):
        # «12345 6» contiene la matrícula 12345 (con un espacio de separación) y también la 123456.
        assert encontrados('Matrícula: 12345 6', alumno(1, '12345'), alumno(2, '123456')) == [2]

    def test_dos_matriculas_distintas_en_la_portada_son_ambiguas(self):
        texto = 'Matrícula: 20240001. Trabajo en equipo con 20240002'
        assert sorted(encontrados(texto, alumno(1, '20240001'), alumno(2, '20240002'))) == [1, 2]

    def test_la_matricula_de_un_companero_se_ve_como_ambigua_si_escribe_las_dos(self):
        assert len(encontrados('Mi matrícula 20240001 (copié la de 20240002)', alumno(1, '20240001'), alumno(2, '20240002'))) == 2

    def test_alumnos_sin_matricula_se_omiten(self):
        assert encontrados('Matrícula: 20240001', alumno(1, ''), alumno(2, None), alumno(3, '20240001')) == [3]

    @pytest.mark.parametrize('corta', ['7', '12', '123', '0012'])
    def test_una_matricula_demasiado_corta_no_se_busca(self, corta):
        assert encontrados('Grupo 12, hoja 7, ejercicio 123', alumno(1, corta)) == []

    def test_la_misma_matricula_dos_veces_es_un_solo_alumno(self):
        assert encontrados('Matrícula 20240001 ... 20240001', alumno(1, '20240001')) == [1]

    def test_dos_alumnos_con_la_misma_matricula_salvo_ceros_son_ambiguos(self):
        assert sorted(encontrados('Matrícula 12345', alumno(1, '012345'), alumno(2, '12345'))) == [1, 2]

    @pytest.mark.parametrize('texto', ['1 ' * 2000, '0' * 4000, '1-' * 2000 + '0', 'a1' * 2000])
    def test_un_texto_enorme_no_se_cuelga(self, texto):
        assert encontrados(texto, alumno(1, '11111112')) == []

    def test_digitos_sueltos_separados_por_espacios_si_forman_la_matricula(self):
        assert encontrados('1 1 1 1 1 1 1 1', alumno(1, '11111111')) == [1]


class TestNombre:
    def test_el_apellido_aparece(self):
        assert name_matches('Nombre: Ana PÉREZ López', alumno(1, '1', 'Pérez'))

    def test_el_apellido_no_aparece(self):
        assert not name_matches('Nombre: Juan Gómez', alumno(1, '1', 'Pérez'))

    def test_basta_con_uno_de_los_apellidos(self):
        assert name_matches('Ana López', alumno(1, '1', 'Pérez López'))

    def test_particulas_cortas_no_cuentan(self):
        assert not name_matches('Ana de la Torre', alumno(1, '1', 'de la Cruz'))

    def test_sin_apellido_que_comparar_se_da_por_bueno(self):
        assert name_matches('lo que sea', alumno(1, '1', ''))
