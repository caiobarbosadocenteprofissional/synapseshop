"""Testes da publicação de eventos (``services.publicacao``)."""

import pytest

from events.contracts import EVENTO_PEDIDO_CRIADO
from events.topology import topologia_de
from services import publicacao

pytestmark = pytest.mark.unit


def _argumentos():
    return {
        "evento": {"event_type": "PedidoCriado", "dados": {}},
        "idempotency_key": "pedido:1",
        "topologia": topologia_de(EVENTO_PEDIDO_CRIADO),
        "prefixo_log": "teste",
    }


def test_mensageria_desligada_retorna_false(settings):
    settings.MESSAGERIA_ENABLED = False
    assert publicacao.publicar_evento(**_argumentos()) is False


def test_publicacao_bem_sucedida(broker_disponivel):
    assert publicacao.publicar_evento(**_argumentos()) is True
    assert broker_disponivel[0]["idempotency_key"] == "pedido:1"


def test_broker_indisponivel_retorna_false(broker_indisponivel):
    assert publicacao.publicar_evento(**_argumentos()) is False
