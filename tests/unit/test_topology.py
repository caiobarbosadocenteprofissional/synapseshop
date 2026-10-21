"""Testes da topologia de transporte por evento.

O núcleo (``events/topology.py``) é neutro: não conhece Django e só sabe o
*formato* de um transporte. O adaptador (``config/topologias.py``) é quem resolve
os *nomes* desta implantação a partir do ``settings``. Os dois são testados
separadamente porque é justamente a separação que permite importar o catálogo
de eventos sem configurar o Django.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config import topologias as topologias_app
from events import topology
from events.contracts import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
)

pytestmark = pytest.mark.unit


NOMES = topology.NomesEvento(
    topico="pedidos.pedidocriado",
    dlq="pedidos.pedidocriado.dlq",
    grupo="pedido-worker",
    exchange="pedidos.events",
    dlx="pedidos.dlx",
    routing_key="pedido.criado",
    fila="pedidos.pedidocriado",
    fila_dlq="pedidos.pedidocriado.dlq",
)


# --------------------------------------------------------------------------- #
# Núcleo neutro
# --------------------------------------------------------------------------- #
def test_construir_topologia_junta_evento_e_nomes():
    topologia_ev = topology.construir_topologia(EVENTO_PEDIDO_CRIADO, NOMES)
    assert topologia_ev.evento == EVENTO_PEDIDO_CRIADO
    assert topologia_ev.topico == "pedidos.pedidocriado"
    assert topologia_ev.dlq == "pedidos.pedidocriado.dlq"
    assert topologia_ev.grupo == "pedido-worker"


def test_construir_topologia_de_evento_desconhecido_levanta_erro():
    with pytest.raises(ValueError):
        topology.construir_topologia("EventoInexistente", NOMES)


def test_construir_topologias_exige_nome_de_todos_os_eventos():
    with pytest.raises(ValueError):
        topology.construir_topologias({EVENTO_PEDIDO_CRIADO: NOMES})


def test_construir_topologias_respeita_a_ordem_do_fluxo():
    nomes = {evento: NOMES for evento in topology.EVENTOS}
    assert [t.evento for t in topology.construir_topologias(nomes)] == list(topology.EVENTOS)


def test_nucleo_nao_importa_django():
    """O catálogo de eventos precisa ser importável sem o Django configurado."""
    import events.topology as modulo

    fonte = open(modulo.__file__, encoding="utf-8").read()
    assert "django" not in fonte


# --------------------------------------------------------------------------- #
# Adaptador da aplicação
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("evento", "topico_esperado"),
    [
        (EVENTO_PEDIDO_CRIADO, "pedidos.pedidocriado"),
        (EVENTO_PAGAMENTO_PROCESSADO, "pagamentos.pagamentoprocessado"),
        (EVENTO_NOTIFICACAO_ENVIADA, "notificacoes.notificacaoenviada"),
    ],
)
def test_topologia_de_retorna_evento_e_topico(evento, topico_esperado):
    topologia_ev = topologias_app.topologia_de(evento)
    assert topologia_ev.evento == evento
    assert topologia_ev.topico == topico_esperado
    assert topologia_ev.dlq == f"{topico_esperado}.dlq"


def test_topologia_as_dict_tem_todas_as_chaves():
    dados = topologias_app.topologia_de(EVENTO_PEDIDO_CRIADO).as_dict()
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
    pagamento = topologias_app.topologia_de(EVENTO_PAGAMENTO_PROCESSADO)
    notificacao = topologias_app.topologia_de(EVENTO_NOTIFICACAO_ENVIADA)
    assert pagamento.grupo == settings.KAFKA_GRUPO_NOTIFICACAO
    assert notificacao.grupo == settings.KAFKA_GRUPO_NOTIFICACAO


def test_topologias_na_ordem_do_fluxo():
    nomes = [t.evento for t in topologias_app.topologias()]
    assert nomes == [EVENTO_PEDIDO_CRIADO, EVENTO_PAGAMENTO_PROCESSADO, EVENTO_NOTIFICACAO_ENVIADA]


def test_topologia_de_evento_desconhecido_levanta_erro():
    with pytest.raises(ImproperlyConfigured):
        topologias_app.topologia_de("EventoInexistente")


def test_topologia_segue_a_mudanca_do_setting(settings):
    """O memo é por valor: renomear o tópico muda a topologia resolvida."""
    settings.KAFKA_TOPICO_PEDIDO_CRIADO = "outro.topico"
    assert topologias_app.topologia_de(EVENTO_PEDIDO_CRIADO).topico == "outro.topico"


@pytest.mark.parametrize(
    ("id_registro", "prefixo", "esperado"),
    [
        (15, "pagamento", "pagamento:15"),
        (42, "notificacao", "notificacao:42"),
        (1, "pedido", "pedido:1"),
    ],
)
def test_chave_de(id_registro, prefixo, esperado):
    assert topology.chave_de(id_registro, prefixo) == esperado
