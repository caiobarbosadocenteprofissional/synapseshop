"""Testes do dispatcher de eventos de domínio (``services.events``)."""

import pytest

from services import events

pytestmark = pytest.mark.unit


def test_on_registra_e_emitir_chama_handler():
    recebidos = []

    @events.on("EventoDeTeste")
    def handler(**campos):
        recebidos.append(campos)

    events.emitir("EventoDeTeste", x=1)
    assert recebidos == [{"x": 1}]


def test_emitir_evento_sem_handler_nao_falha():
    events.emitir("EventoNuncaRegistrado", y=2)


def test_handler_que_falha_nao_propaga():
    @events.on("EventoQueFalha")
    def handler(**campos):
        raise RuntimeError("boom")

    events.emitir("EventoQueFalha")  # não deve levantar


def test_varios_handlers_para_o_mesmo_evento():
    ordem = []

    @events.on("EventoMultiplo")
    def primeiro(**campos):
        ordem.append("primeiro")

    @events.on("EventoMultiplo")
    def segundo(**campos):
        ordem.append("segundo")

    events.emitir("EventoMultiplo")
    assert ordem == ["primeiro", "segundo"]


def test_emitir_apos_commit_dispara_no_commit(db, django_capture_on_commit_callbacks):
    recebidos = []

    @events.on("EventoAposCommit")
    def handler(**campos):
        recebidos.append(campos)

    with django_capture_on_commit_callbacks(execute=True):
        events.emitir_apos_commit("EventoAposCommit", pedido_id=1)

    assert recebidos == [{"pedido_id": 1}]
