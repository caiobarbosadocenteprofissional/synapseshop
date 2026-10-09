"""Testes das regras de invalidação por evento de domínio."""

import pytest

from services import cache, cache_invalidation, events

pytestmark = pytest.mark.unit


def test_evento_de_item_invalida_item_e_lista(monkeypatch):
    chamadas = []

    monkeypatch.setattr(cache, "invalidar_item", lambda i: chamadas.append(("item", i)))
    monkeypatch.setattr(cache, "invalidar_lista_itens", lambda: chamadas.append(("lista", None)))

    cache_invalidation._invalida_item(item_id=5)
    assert ("item", 5) in chamadas
    assert ("lista", None) in chamadas


def test_evento_de_categoria_invalida_lista_e_detalhes(monkeypatch):
    chamadas = []

    monkeypatch.setattr(cache, "invalidar_lista_itens", lambda: chamadas.append("lista"))
    monkeypatch.setattr(
        cache, "invalidar_detalhes_itens", lambda: chamadas.append("detalhes")
    )

    cache_invalidation._invalida_categoria(categoria_id=1)
    assert chamadas == ["lista", "detalhes"]


def test_evento_de_pedido_invalida_pedido(monkeypatch):
    chamadas = []
    monkeypatch.setattr(cache, "invalidar_pedido", lambda i: chamadas.append(i))

    cache_invalidation._invalida_pedido(pedido_id=42)
    assert chamadas == [42]


@pytest.mark.parametrize(
    "nome_evento",
    ["ItemCriado", "ItemAtualizado", "ItemRemovido"],
)
def test_eventos_de_item_passam_pelo_dispatcher(nome_evento, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cache, "invalidar_item", lambda i: chamadas.append(i))
    monkeypatch.setattr(cache, "invalidar_lista_itens", lambda: None)

    events.emitir(nome_evento, item_id=7)
    assert chamadas == [7]


@pytest.mark.parametrize(
    "nome_evento",
    ["CategoriaCriada", "CategoriaAtualizada", "CategoriaRemovida"],
)
def test_eventos_de_categoria_passam_pelo_dispatcher(nome_evento, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cache, "invalidar_lista_itens", lambda: chamadas.append("lista"))
    monkeypatch.setattr(cache, "invalidar_detalhes_itens", lambda: chamadas.append("detalhes"))

    events.emitir(nome_evento, categoria_id=3)
    assert chamadas == ["lista", "detalhes"]


@pytest.mark.parametrize(
    "nome_evento",
    ["PedidoEmProcessamento", "PagamentoAprovado", "PagamentoRecusado", "NotificacaoRegistrada"],
)
def test_eventos_de_pedido_passam_pelo_dispatcher(nome_evento, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cache, "invalidar_pedido", lambda i: chamadas.append(i))

    events.emitir(nome_evento, pedido_id=10)
    assert chamadas == [10]
