"""El borrador de la rúbrica: lectura del formulario, validación y plantillas."""

from decimal import Decimal

import pytest

from apps.rubrics.services import editor


def formulario(niveles=('Excelente', 'Bueno'), criterios=(('Tesis', ('4', '2')),), nombre='Ensayo', descripcion=''):
    """POST del editor como lo arma la página (campos por posición)."""
    datos = {'name': nombre, 'description': descripcion, 'levels': str(len(niveles)), 'criteria': str(len(criterios))}
    for j, nivel in enumerate(niveles):
        datos[f'level_{j}'] = nivel
    for i, (criterio, puntos) in enumerate(criterios):
        datos[f'c{i}_name'] = criterio
        for j, valor in enumerate(puntos):
            datos[f'c{i}_l{j}_points'] = valor
            datos[f'c{i}_l{j}_text'] = f'texto {i}{j}'
    return datos


class TestLectura:
    def test_lee_el_formulario_por_posicion(self):
        borrador = editor.parse_post(formulario(criterios=(('Tesis', ('4', '2')), ('Fuentes', ('3', '0')))))
        assert borrador['name'] == 'Ensayo' and borrador['levels'] == ['Excelente', 'Bueno']
        assert [c['name'] for c in borrador['criteria']] == ['Tesis', 'Fuentes']
        assert borrador['criteria'][1]['cells'][0] == {'points': '3', 'text': 'texto 10'}

    def test_recorta_espacios(self):
        borrador = editor.parse_post(formulario(nombre='  Ensayo  ', criterios=((' Tesis ', ('4', '2')),)))
        assert borrador['name'] == 'Ensayo' and borrador['criteria'][0]['name'] == 'Tesis'

    @pytest.mark.parametrize('cuenta', ['', 'abc', '-3', '1e3'])
    def test_cuentas_invalidas_no_rompen(self, cuenta):
        borrador = editor.parse_post({'name': 'X', 'levels': cuenta, 'criteria': cuenta})
        assert borrador['levels'] == [] and borrador['criteria'] == []

    def test_un_envio_manipulado_no_genera_miles_de_filas(self):
        borrador = editor.parse_post({'name': 'X', 'levels': '99999', 'criteria': '99999'})
        assert len(borrador['levels']) == editor.READ_LIMIT and len(borrador['criteria']) == editor.READ_LIMIT


class TestPuntos:
    @pytest.mark.parametrize('texto, esperado', [
        ('4', Decimal('4.00')), ('2,5', Decimal('2.50')), (' 3.456 ', Decimal('3.46')), ('0', Decimal('0.00')), ('1000', Decimal('1000.00')),
    ])
    def test_validos(self, texto, esperado):
        assert editor.parse_points(texto) == esperado

    @pytest.mark.parametrize('texto', ['', 'x', '-1', '1000.01', 'NaN', 'Infinity', '1e5'])
    def test_invalidos(self, texto):
        assert editor.parse_points(texto) is None


class TestValidacion:
    def validar(self, **cambios):
        return editor.validate(editor.parse_post(formulario(**cambios)))

    def test_un_borrador_correcto_devuelve_decimales(self):
        errores, limpio = self.validar(criterios=(('Tesis', ('4', '2,5')),))
        assert errores == [] and limpio['criteria'][0]['cells'][1]['points'] == Decimal('2.50')

    def test_pide_nombre(self):
        errores, limpio = self.validar(nombre='')
        assert limpio is None and errores == ['Ponle un nombre a la rúbrica.']

    def test_nombre_y_descripcion_largos(self):
        errores, _ = self.validar(nombre='x' * 151, descripcion='y' * 201)
        assert len(errores) == 2

    @pytest.mark.parametrize('niveles', [('Solo',), tuple(f'N{n}' for n in range(7))])
    def test_cantidad_de_niveles(self, niveles):
        errores, limpio = self.validar(niveles=niveles, criterios=(('Tesis', ('1',) * len(niveles)),))
        assert limpio is None and any('niveles' in e for e in errores)

    def test_sin_criterios(self):
        errores, limpio = self.validar(criterios=())
        assert limpio is None and any('criterios' in e for e in errores)

    def test_demasiados_criterios(self):
        errores, _ = self.validar(criterios=tuple((f'C{n}', ('1', '0')) for n in range(13)))
        assert any('entre 1 y 12 criterios' in e for e in errores)

    def test_niveles_sin_nombre_o_repetidos(self):
        assert any('nombre' in e for e in self.validar(niveles=('Excelente', ''))[0])
        assert any('repetir' in e for e in self.validar(niveles=('Bueno', 'bueno'))[0])

    def test_criterio_sin_nombre(self):
        errores, _ = self.validar(criterios=(('', ('4', '2')),))
        assert errores == ['El criterio 1 necesita un nombre.']

    def test_puntos_invalidos_dicen_donde(self):
        errores, _ = self.validar(criterios=(('Tesis', ('4', 'x')),))
        assert errores == ['«Tesis», nivel «Bueno»: los puntos deben ser un número de 0 a 1000.']

    def test_un_criterio_sin_puntos_no_sirve(self):
        errores, _ = self.validar(criterios=(('Tesis', ('0', '0')),))
        assert errores == ['«Tesis» debe dar puntos en al menos un nivel.']

    def test_descripcion_de_celda_demasiado_larga(self):
        datos = formulario()
        datos['c0_l0_text'] = 'x' * 1001
        errores, _ = editor.validate(editor.parse_post(datos))
        assert any('descripción' in e for e in errores)

    def test_no_se_exige_que_los_puntos_vayan_en_orden(self):
        errores, limpio = self.validar(criterios=(('Tesis', ('1', '4')),))
        assert errores == [] and limpio is not None


class TestPlantillas:
    @pytest.mark.parametrize('clave', list(editor.TEMPLATES))
    def test_cada_plantilla_es_una_rubrica_valida(self, clave):
        borrador = editor.template_draft(clave)
        errores, limpio = editor.validate(borrador)
        assert errores == [], clave
        assert limpio is not None

    def test_la_copia_no_toca_la_plantilla(self):
        borrador = editor.template_draft('ensayo')
        borrador['criteria'][0]['name'] = 'otro'
        borrador['criteria'][0]['cells'][0]['points'] = '99'
        assert editor.TEMPLATES['ensayo']['draft']['criteria'][0]['name'] == 'Tesis'
        assert editor.TEMPLATES['ensayo']['draft']['criteria'][0]['cells'][0]['points'] == '4'

    def test_plantilla_inexistente(self):
        assert editor.template_draft('nada') is None

    def test_la_hoja_en_blanco_pide_completarse(self):
        errores, _ = editor.validate(editor.blank_draft())
        assert errores and all('nombre' in e for e in errores)
