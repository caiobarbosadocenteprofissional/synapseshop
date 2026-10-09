"""Testes da tabela de topologias por evento."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from events import topology
from events.contracts import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("evento", "topico_esperado"),
    [
        (EVENTO_PEDIDO_CRIADO, "pedidos.pedidocriado"),
        (EVENTO_PAGAMENTO_PROCESSADO, "pagamentos.pagamentoprocessado"),
        (EVENTO_NOTIFICACAO_ENVIADA, "notificacoes.notificacaoenviada"),
    ],
)
def test_topologia_de_retorna_evento_e_topico(evento, topico_esperado):
    topologia_ev = topology.topologia_de(evento)
    assert topologia_ev.evento == evento
    assert topologia_ev.topico == topico_esperado
    assert topologia_ev.dlq == f"{topico_esperado}.dlq"


def test_topologia_as_dict_tem_todas_as_chaves():
    dados = topology.topologia_de(EVENTO_PEDIDO_CRIADO).as_dict()
    assert set(dados) == {
        "evento",
        "topico",
        "dlq",
        "grupo",
        "exchange",
        "routing_key",
        "fila",
        "fila_dlq",
    }


def test_pagamento_e_notificacao_compartilham_grupo_da_notificacao(settings):
    pagamento = topology.topologia_de(EVENTO_PAGAMENTO_PROCESSADO)
    notificacao = topology.topologia_de(EVENTO_NOTIFICACAO_ENVIADA)
    assert pagamento.grupo == settings.KAFKA_GRUPO_NOTIFICACAO
    assert notificacao.grupo == settings.KAFKA_GRUPO_NOTIFICACAO


def test_topologias_na_ordem_do_fluxo():
    nomes = [t.evento for t in topology.topologias()]
    assert nomes == [EVENTO_PEDIDO_CRIADO, EVENTO_PAGAMENTO_PROCESSADO, EVENTO_NOTIFICACAO_ENVIADA]


def test_topologia_de_evento_desconhecido_levanta_erro():
    with pytest.raises(ImproperlyConfigured):
        topology.topologia_de("EventoInexistente")


@pytest.mark.parametrize(
    ("id_registro", "prefixo", "esperado"),
    [(15, "pagamento", "pagamento:15"), (42, "notificacao", "notificacao:42")],
)
def test_chave_de(id_registro, prefixo, esperado):
    assert topology.chave_de(id_registro, prefixo) == esperado
