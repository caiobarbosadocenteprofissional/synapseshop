"""Testes dos utilitários críticos: chaves de cache e chave de idempotência.

São funções puras (sem banco, sem rede) — o alvo é o formato das chaves, que é
um contrato entre produtor e invalidador.
"""

from decimal import Decimal

import pytest

from django.http import QueryDict

from events.contracts import _texto
from events.topology import chave_de
from services import cache

pytestmark = pytest.mark.unit


def _query(params):
    """Converte um dict em ``QueryDict`` — a forma real usada pelas views."""
    query = QueryDict("", mutable=True)
    for chave, valor in params.items():
        query[chave] = valor
    return query


def test_chaves_cache_tem_prefixo():
    assert cache._chave_item(7) == "item:7"
    assert cache._chave_pedido(1) == "pedido:1"
    assert cache._chave_item(5).startswith("item:")
    assert cache._chave_pedido(9).startswith("pedido:")


def test_chave_lista_itens_assinatura_estavel_independente_da_ordem():
    a = cache._chave_lista_itens(_query({"page": "1", "search": "fone"}))
    b = cache._chave_lista_itens(_query({"search": "fone", "page": "1"}))
    assert a == b
    assert a.startswith("itens:list:")


def test_chave_lista_itens_ignora_parametros_irrelevantes():
    assert cache._chave_lista_itens(_query({"foo": "bar"})) == cache._chave_lista_itens(_query({}))


def test_chave_lista_itens_aceita_querydict():
    query = QueryDict("page=1&category=2")
    assert cache._chave_lista_itens(query).startswith("itens:list:")


def test_texto_decodifica_bytes_e_mantem_str():
    assert cache._texto(b"abc") == "abc"
    assert cache._texto("abc") == "abc"


def test_ttls_reflete_settings(settings):
    ttls = cache.ttls()
    assert ttls[cache.ENDPOINT_LISTA_ITENS] == settings.CACHE_TTL_LISTA
    assert ttls[cache.ENDPOINT_DETALHE_ITEM] == settings.CACHE_TTL_DETALHE
    assert ttls[cache.ENDPOINT_DETALHE_PEDIDO] == settings.CACHE_TTL_PEDIDO


def test_cache_ativo_respeita_kill_switch(settings):
    settings.CACHE_ENABLED = True
    assert cache.cache_ativo() is True
    settings.CACHE_ENABLED = False
    assert cache.cache_ativo() is False


@pytest.mark.parametrize(
    ("id_registro", "prefixo", "esperado"),
    [
        (10, "pagamento", "pagamento:10"),
        (123, "notificacao", "notificacao:123"),
        (1, "pedido", "pedido:1"),
    ],
)
def test_chave_de_idempotencia(id_registro, prefixo, esperado):
    assert chave_de(id_registro, prefixo) == esperado


def test_texto_de_decimal_e_int_usa_representacao_estavel():
    assert _texto(Decimal("10.50")) == "10.50"
    assert _texto(Decimal("0")) == "0"
    assert _texto(5) == "5"
