"""Testes dos workers consumidores (``workers.pedido_worker`` e
``workers.notificacao_worker``).

Até a Aula 15 os dois workers (~15 KB de lógica de consumidor) não tinham
nenhum teste automatizado — a validação era só via smoke test manual no Compose,
e o ``--cov`` do pytest.ini nem sequer os media. O que está aqui cobre a
lógica de domínio dos handlers: transição de estado, idempotência, contrato,
falha forçada (DoD de DLQ) e o destino de log por broker. A política de
reentrega/commit de offset em si pertence ao transporte
(``services.messaging``) e continua sendo validada pelos smoke tests.
"""

import pytest

from django.utils import timezone

from events.contracts import (
    ContratoInvalido,
    EventoPedidoCriado,
    ItemPedidoCriado,
)
from repositories.models import Pedido
from services import idempotencia
from workers import notificacao_worker, pedido_worker

pytestmark = pytest.mark.unit


def _evento_pedido(pedido, **overrides):
    bruto = EventoPedidoCriado(
        idempotency_key=pedido.idempotency_key,
        pedido_id=pedido.pk,
        usuario_id=pedido.usuario_id,
        total=pedido.total,
        status="PENDENTE",
        itens=[
            ItemPedidoCriado(
                item_id=item.item_id,
                quantidade=item.quantidade,
                preco_unitario=item.preco_unitario,
            )
            for item in pedido.itens.all()
        ],
        correlation_id=pedido.correlation_id,
    ).to_dict()
    bruto.update(overrides)
    return bruto


# --------------------------------------------------------------------------- #
# pedido_worker
# --------------------------------------------------------------------------- #
def test_falha_forcada_sem_padrao_retorna_false(settings):
    settings.PEDIDO_WORKER_FALHA_IDEM_KEYS = []
    assert pedido_worker._falha_forcada("pedido:1") is False


def test_falha_forcada_casa_com_padrao_fnmatch(settings):
    settings.PEDIDO_WORKER_FALHA_IDEM_KEYS = ["pedido-dlq-*"]
    assert pedido_worker._falha_forcada("pedido-dlq-999") is True
    assert pedido_worker._falha_forcada("pedido-smoke-1") is False


def test_falha_forcada_sempre_via_env(monkeypatch):
    monkeypatch.setenv("PEDIDO_WORKER_FALHAR_SEMPRE", "1")
    assert pedido_worker._falha_forcada("qualquer-chave") is True


def test_processar_caminho_feliz_move_para_processando(db, pedido):
    bruto = _evento_pedido(pedido)

    pedido_worker.processar_pedido_criado(bruto, tentativa=1)

    pedido.refresh_from_db()
    assert pedido.status == Pedido.Status.PROCESSANDO
    assert pedido.processado_em is not None
    assert idempotencia.ja_processado("PedidoCriado", pedido.idempotency_key)


def test_processar_reentrega_nao_reprocessa(db, pedido):
    bruto = _evento_pedido(pedido)

    pedido_worker.processar_pedido_criado(bruto, tentativa=1)
    pedido.refresh_from_db()
    primeiro_status = pedido.status
    primeiro_processado_em = pedido.processado_em

    pedido_worker.processar_pedido_criado(bruto, tentativa=2)

    pedido.refresh_from_db()
    assert pedido.status == primeiro_status
    assert pedido.processado_em == primeiro_processado_em


def test_processar_falha_forcada_levanta(db, pedido, settings):
    settings.PEDIDO_WORKER_FALHA_IDEM_KEYS = ["pedido-fixture-*"]

    with pytest.raises(pedido_worker.ErroForcadoDeTeste):
        pedido_worker.processar_pedido_criado(_evento_pedido(pedido), tentativa=1)


def test_processar_pedido_inexistente_levanta(db, pedido):
    bruto = _evento_pedido(pedido)
    bruto["dados"] = dict(bruto["dados"], pedido_id=999999)

    with pytest.raises(pedido_worker.PedidoInexistente):
        pedido_worker.processar_pedido_criado(bruto, tentativa=1)


def test_processar_chave_divergente_do_pedido_levanta(db, pedido):
    bruto = _evento_pedido(pedido)
    bruto["idempotency_key"] = "outra-chave"
    bruto["dados"] = dict(bruto["dados"], idempotency_key="outra-chave")

    with pytest.raises(ContratoInvalido):
        pedido_worker.processar_pedido_criado(bruto, tentativa=1)


def test_processar_pedido_ja_fora_de_pendente_nao_regrava(db, pedido):
    pedido.status = Pedido.Status.PROCESSANDO
    pedido.processado_em = timezone.now()
    pedido.save(update_fields=["status", "processado_em", "updated_at"])

    # Evento novo (ainda não deduplicado) chega para um pedido já processado.
    pedido_worker.processar_pedido_criado(_evento_pedido(pedido), tentativa=1)

    pedido.refresh_from_db()
    assert pedido.status == Pedido.Status.PROCESSANDO


def test_destino_log_kafka(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    destino = pedido_worker._destino_log()
    assert destino["broker"] == "kafka"
    assert destino["topico"] == "pedidos.pedidocriado"
    assert destino["dlq"] == "pedidos.pedidocriado.dlq"
    assert destino["particoes"] == settings.KAFKA_PARTICOES


def test_destino_log_rabbitmq(settings):
    settings.MENSAGERIA_BROKER = "rabbitmq"
    destino = pedido_worker._destino_log()
    assert destino["broker"] == "rabbitmq"
    assert destino["fila"] == "pedidos.pedidocriado"
    assert destino["dlq"] == "pedidos.pedidocriado.dlq"
    assert destino["prefetch"] == settings.RABBITMQ_PREFETCH


# --------------------------------------------------------------------------- #
# notificacao_worker
# --------------------------------------------------------------------------- #
def _evento_pagamento(pedido_id=7, **overrides):
    bruto = {
        "event_id": "evento-teste",
        "event_type": "PagamentoProcessado",
        "version": 1,
        "occurred_at": "2026-01-01T00:00:00Z",
        "correlation_id": "corr",
        "idempotency_key": "pagamento:3",
        "dados": {
            "pagamento_id": 3,
            "pedido_id": pedido_id,
            "usuario_id": 2,
            "valor": "10.00",
            "status": "APROVADO",
            "forma_pagamento": "pix",
            "referencia": "E123",
        },
    }
    bruto.update(overrides)
    return bruto


def test_notificacao_falha_forcada_casa_por_pedido_id(settings):
    settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS = ["pedido:7"]
    with pytest.raises(notificacao_worker.ErroForcadoDeTeste):
        notificacao_worker.processar(_evento_pagamento(pedido_id=7), tentativa=1)


def test_notificacao_falha_forcada_nao_casa_com_outro_pedido(settings):
    settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS = ["pedido:7"]
    with pytest.raises(Exception) as excinfo:
        notificacao_worker.processar(_evento_pagamento(pedido_id=8), tentativa=1)
    # Sem a falha forçada, o handler delega ao serviço, que rejeita o
    # pagamento inexistente — a falha não é a de DLQ.
    assert not isinstance(excinfo.value, notificacao_worker.ErroForcadoDeTeste)


def test_notificacao_falha_forcada_casa_por_idempotency_key(settings):
    settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS = ["pagamento:3"]
    with pytest.raises(notificacao_worker.ErroForcadoDeTeste):
        notificacao_worker.processar(_evento_pagamento(), tentativa=1)


def test_notificacao_falha_forcada_sempre_via_env(monkeypatch):
    monkeypatch.setenv("NOTIFICACAO_WORKER_FALHAR_SEMPRE", "true")
    with pytest.raises(notificacao_worker.ErroForcadoDeTeste):
        notificacao_worker.processar(_evento_pagamento(), tentativa=1)


def test_notificacao_sem_falha_delega_ao_servico(monkeypatch):
    chamado = {}

    def registrar(bruto, tentativa):
        chamado["bruto"] = bruto
        chamado["tentativa"] = tentativa

    monkeypatch.setattr(
        notificacao_worker.notificacao, "processar_pagamento_processado", registrar
    )
    bruto = _evento_pagamento()
    notificacao_worker.processar(bruto, tentativa=2)
    assert chamado == {"bruto": bruto, "tentativa": 2}


def test_notificacao_destino_log_kafka(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    destino = notificacao_worker._destino_log()
    assert destino["broker"] == "kafka"
    assert destino["topico"] == "pagamentos.pagamentoprocessado"


def test_notificacao_destino_log_rabbitmq(settings):
    settings.MENSAGERIA_BROKER = "rabbitmq"
    destino = notificacao_worker._destino_log()
    assert destino["broker"] == "rabbitmq"
    assert destino["fila"] == "pagamentos.pagamentoprocessado"
