"""Testes dos contratos de mensagem — caminho felizes e de erro.

O contrato é o que impede o consumidor de aplicar um evento corrompido. Cada
regra de validação de ``_validar_envelope`` tem um caso aqui.
"""

import uuid
from decimal import Decimal

import pytest

from events import contracts as c

pytestmark = pytest.mark.unit


def _envelope(tipo, chave, dados, **overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "event_type": tipo,
        "version": c.VERSAO_CONTRATO,
        "occurred_at": "2026-01-01T00:00:00Z",
        "correlation_id": str(uuid.uuid4()),
        "idempotency_key": chave,
        "dados": dados,
    }
    base.update(overrides)
    return base


def _dados_pedido(**overrides):
    dados = {
        "pedido_id": 1,
        "usuario_id": 2,
        "total": "10.00",
        "status": "PENDENTE",
        "itens": [{"item_id": 5, "quantidade": 2, "preco_unitario": "5.00"}],
    }
    dados.update(overrides)
    return dados


def _dados_pagamento(**overrides):
    dados = {
        "pagamento_id": 3,
        "pedido_id": 1,
        "usuario_id": 2,
        "valor": "10.00",
        "status": "APROVADO",
        "forma_pagamento": "pix",
        "referencia": "E123",
    }
    dados.update(overrides)
    return dados


def _dados_notificacao(**overrides):
    dados = {
        "notificacao_id": 9,
        "pedido_id": 1,
        "pagamento_id": 3,
        "canal": "EMAIL",
        "destinatario": "x@y.com",
        "assunto": "ok",
    }
    dados.update(overrides)
    return dados


# --------------------------------------------------------------------------- #
# PedidoCriado
# --------------------------------------------------------------------------- #
def test_pedido_criado_round_trip():
    evento = c.EventoPedidoCriado(
        idempotency_key="pedido:1",
        pedido_id=1,
        usuario_id=2,
        total=Decimal("10.00"),
        status="PENDENTE",
        itens=[c.ItemPedidoCriado(item_id=5, quantidade=2, preco_unitario=Decimal("5.00"))],
        correlation_id="corr-1",
    )
    bruto = evento.to_dict()
    assert bruto["version"] == c.VERSAO_CONTRATO
    assert bruto["dados"]["total"] == "10.00"

    reconstruido = c.EventoPedidoCriado.from_dict(bruto)
    assert reconstruido.pedido_id == 1
    assert reconstruido.total == Decimal("10.00")
    assert reconstruido.itens[0].item_id == 5
    assert reconstruido.correlation_id == "corr-1"


def test_correlation_id_ausente_cai_no_event_id():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido())
    bruto.pop("correlation_id")
    evento = c.EventoPedidoCriado.from_dict(bruto)
    assert evento.correlation_id == bruto["event_id"]


def test_serializar_envelope_correlation_vazia_usa_event_id():
    envelope = c._serializar_envelope(
        tipo="X", chave="k", dados={}, event_id="eid", occurred_at="agora", correlation_id=""
    )
    assert envelope["correlation_id"] == "eid"


@pytest.mark.parametrize("bruto", [None, "texto", 1, [], {}])
def test_envelope_invalido_nao_e_dict(bruto):
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


@pytest.mark.parametrize("campo", c.CAMPOS_OBRIGATORIOS)
def test_envelope_com_campo_obrigatorio_faltando(campo):
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido())
    bruto.pop(campo)
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_envelope_event_type_errado():
    bruto = _envelope("OutroEvento", "k", _dados_pedido())
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_envelope_versao_incompativel():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido(), version="2.0")
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_idempotency_key_vazio():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "   ", _dados_pedido())
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_idempotency_key_muito_longa():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "x" * 65, _dados_pedido())
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_dados_nao_e_objeto_json():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", ["nao", "e", "dict"])
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


@pytest.mark.parametrize("campo", c.CAMPOS_OBRIGATORIOS_DADOS[c.EVENTO_PEDIDO_CRIADO])
def test_pedido_dados_com_campo_faltando(campo):
    dados = _dados_pedido()
    dados.pop(campo)
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", dados)
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_pedido_sem_itens():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido(itens=[]))
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_pedido_inteiro_invalido():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido(pedido_id="abc"))
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


def test_pedido_decimal_invalido():
    bruto = _envelope(c.EVENTO_PEDIDO_CRIADO, "k", _dados_pedido(total="abc"))
    with pytest.raises(c.ContratoInvalido):
        c.EventoPedidoCriado.from_dict(bruto)


# --------------------------------------------------------------------------- #
# ItemPedidoCriado
# --------------------------------------------------------------------------- #
def test_item_pedido_criado_round_trip():
    item = c.ItemPedidoCriado(item_id=1, quantidade=3, preco_unitario=Decimal("2.50"))
    assert item.to_dict()["preco_unitario"] == "2.50"
    assert c.ItemPedidoCriado.from_dict(item.to_dict()).quantidade == 3


@pytest.mark.parametrize(
    "bruto",
    [
        {"quantidade": 1, "preco_unitario": "1.00"},
        {"item_id": 1, "preco_unitario": "1.00"},
        {"item_id": 1, "quantidade": 1},
    ],
)
def test_item_pedido_criado_campo_faltando(bruto):
    with pytest.raises(c.ContratoInvalido):
        c.ItemPedidoCriado.from_dict(bruto)


def test_item_pedido_criado_quantidade_menor_que_um():
    with pytest.raises(c.ContratoInvalido):
        c.ItemPedidoCriado.from_dict(
            {"item_id": 1, "quantidade": 0, "preco_unitario": "1.00"}
        )


def test_item_pedido_criado_invalido():
    with pytest.raises(c.ContratoInvalido):
        c.ItemPedidoCriado.from_dict(
            {"item_id": "x", "quantidade": 1, "preco_unitario": "1.00"}
        )


# --------------------------------------------------------------------------- #
# PagamentoProcessado
# --------------------------------------------------------------------------- #
def test_pagamento_processado_round_trip_aprovado():
    bruto = _envelope(c.EVENTO_PAGAMENTO_PROCESSADO, "pagamento:3", _dados_pagamento())
    evento = c.EventoPagamentoProcessado.from_dict(bruto)
    assert evento.aprovado is True
    assert evento.to_dict()["dados"]["valor"] == "10.00"


def test_pagamento_processado_recusado():
    bruto = _envelope(
        c.EVENTO_PAGAMENTO_PROCESSADO,
        "pagamento:3",
        _dados_pagamento(status="recusado"),
    )
    evento = c.EventoPagamentoProcessado.from_dict(bruto)
    assert evento.aprovado is False
    assert evento.status == "RECUSADO"


def test_pagamento_status_desconhecido():
    bruto = _envelope(
        c.EVENTO_PAGAMENTO_PROCESSADO, "k", _dados_pagamento(status="PENDENTE")
    )
    with pytest.raises(c.ContratoInvalido):
        c.EventoPagamentoProcessado.from_dict(bruto)


@pytest.mark.parametrize("campo", ["forma_pagamento", "referencia"])
def test_pagamento_campo_texto_vazio(campo):
    bruto = _envelope(
        c.EVENTO_PAGAMENTO_PROCESSADO, "k", _dados_pagamento(**{campo: "   "})
    )
    with pytest.raises(c.ContratoInvalido):
        c.EventoPagamentoProcessado.from_dict(bruto)


# --------------------------------------------------------------------------- #
# NotificacaoEnviada
# --------------------------------------------------------------------------- #
def test_notificacao_enviada_round_trip():
    bruto = _envelope(c.EVENTO_NOTIFICACAO_ENVIADA, "notificacao:9", _dados_notificacao())
    evento = c.EventoNotificacaoEnviada.from_dict(bruto)
    assert evento.notificacao_id == 9
    assert evento.canal == "EMAIL"
    assert evento.to_dict()["dados"]["destinatario"] == "x@y.com"


@pytest.mark.parametrize("campo", ["canal", "destinatario", "assunto"])
def test_notificacao_campo_texto_vazio(campo):
    bruto = _envelope(
        c.EVENTO_NOTIFICACAO_ENVIADA, "k", _dados_notificacao(**{campo: ""})
    )
    with pytest.raises(c.ContratoInvalido):
        c.EventoNotificacaoEnviada.from_dict(bruto)


def test_agora_termina_com_z():
    assert c._agora().endswith("Z")
