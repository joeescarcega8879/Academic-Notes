import pytest

from core.utils import MAX_ID_DIGITS, parse_id


@pytest.mark.parametrize("valor, esperado", [
    ("0", 0), ("7", 7), ("007", 7), ("123456789012345678", 123456789012345678),
])
def test_ids_validos(valor, esperado):
    assert parse_id(valor) == esperado


@pytest.mark.parametrize("valor", [
    "", " ", "abc", "-1", "+1", "1.5", "1e3", " 7", "7 ", "²", "٣", "①", "１２",  # dígitos que no son ASCII
    "9" * (MAX_ID_DIGITS + 1), "9" * 5000,
    None, 7, b"7", ["7"],
])
def test_ids_invalidos_nunca_lanzan(valor):
    assert parse_id(valor) is None


def test_el_limite_es_el_de_un_entero_de_64_bits():
    assert int("9" * MAX_ID_DIGITS) < 2**63
