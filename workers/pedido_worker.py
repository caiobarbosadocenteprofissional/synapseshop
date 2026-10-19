"""Worker consumidor do evento ``PedidoCriado`` (Aulas 9 a 11).

Roda como processo separado da API (``docker compose up pedido-worker``) e é o
lado *consumidor* do fluxo producer/consumer da Camada 5.

O que ele faz ao receber uma mensagem:

1. valida o contrato (``events.contracts``) — evento desconhecido ou corrompido
   é rejeitado antes de qualquer escrita;
2. consulta a chave de idempotência — reentrega de um evento já aplicado é
   confirmada sem efeito colateral;
3. aplica o efeito de domínio: o pedido sai de ``PENDENTE`` para
   ``PROCESSANDO`` e recebe ``processado_em``;
4. registra a chave de deduplicação com TTL, para que a próxima reentrega seja
   reconhecida.

Se qualquer passo levantar exceção, a exceção sobe para
``services.messaging.ConsumidorEvento``, que aplica a política de reentrega
(recuo exponencial) e, ao esgotar as tentativas, deixa a mensagem morrer para a
DLQ.

Este worker não sabe em qual broker está: ``services/messaging.py`` escolhe o
transporte (RabbitMQ na Aula 9, Kafka na Aula 10) e expõe o mesmo par
consumidor/produtor. É por isso que o handler, a deduplicação e a transição de
estado são idênticos nos dois casos — inclusive na garantia de idempotência, que
é o que torna a semântica de *at-least-once* do Kafka segura. Na Aula 11 o
mesmo par ``ConsumidorEvento`` é usado pelo ``notificacao-worker``: o que muda é
a topologia e o handler, não a classe.

Simulação de erro para validar reentrega e DLQ (Aula 9, DoD "erro forçado"):
``PEDIDO_WORKER_FALHA_IDEM_KEYS=pedido-dlq-*`` faz o worker rejeitar apenas os
pedidos cuja ``idempotency_key`` casa com o padrão, permitindo exercitar o
caminho feliz e o caminho de falha no mesmo ambiente. Os padrões aceitam
``fnmatch`` (``*``, ``?``), então a chave do teste pode ser única por execução.
"""

import os
import sys
import time
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from workers.comum import (  # noqa: E402  (bootstrap do Django e do sys.path)
    ErroForcadoDeTeste,
    _log,
    destino_log,
    executar_worker,
    falha_forcada,
)

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from events.contracts import ContratoInvalido, EVENTO_PEDIDO_CRIADO, EventoPedidoCriado  # noqa: E402
from repositories.models import Pedido  # noqa: E402
from services import idempotencia  # noqa: E402
from services.events import PEDIDO_EM_PROCESSAMENTO, emitir_apos_commit  # noqa: E402


class PedidoInexistente(RuntimeError):
    """O evento aponta para um pedido que não está no repositório."""


def _falha_forcada(idempotency_key: str) -> bool:
    """Informa se este pedido deve falhar de propósito (validação da DLQ)."""
    return falha_forcada(
        [idempotency_key],
        "PEDIDO_WORKER_FALHAR_SEMPRE",
        settings.PEDIDO_WORKER_FALHA_IDEM_KEYS,
    )


def processar_pedido_criado(bruto: Dict[str, Any], tentativa: int) -> None:
    """Aplica um evento ``PedidoCriado``. Idempotente por construção."""
    evento = EventoPedidoCriado.from_dict(bruto)
    inicio = time.perf_counter()

    if idempotencia.ja_processado(evento.event_type, evento.idempotency_key):
        _log(
            "worker.pedido.duplicado",
            event_type=evento.event_type,
            correlation_id=evento.correlation_id,
            idempotency_key=evento.idempotency_key,
            pedido_id=evento.pedido_id,
            tentativa=tentativa,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )
        return

    if _falha_forcada(evento.idempotency_key):
        raise ErroForcadoDeTeste(
            f"falha forcada para a idempotency_key {evento.idempotency_key}"
        )

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(pk=evento.pedido_id).first()
        if pedido is None:
            raise PedidoInexistente(
                f"pedido {evento.pedido_id} referenciado pelo evento nao existe"
            )
        if pedido.idempotency_key != evento.idempotency_key:
            raise ContratoInvalido(
                f"idempotency_key do evento ({evento.idempotency_key}) diverge do "
                f"pedido {pedido.pk} ({pedido.idempotency_key})"
            )

        ja_aplicado = pedido.status != Pedido.Status.PENDENTE
        if not ja_aplicado:
            pedido.status = Pedido.Status.PROCESSANDO
            pedido.processado_em = timezone.now()
            pedido.save(update_fields=["status", "processado_em", "updated_at"])
            # O estado do pedido mudou em outro processo: o cache do detalhe,
            # que é compartilhado no Redis, tem de ser invalidado aqui para que
            # o próximo GET /api/v1/pedidos/<id>/ não sirva o estado antigo.
            emitir_apos_commit(PEDIDO_EM_PROCESSAMENTO, pedido_id=pedido.pk)

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 3)
    idempotencia.registrar(
        evento.event_type, evento.idempotency_key, duracao_ms=duracao_ms
    )
    _log(
        "worker.pedido.processado",
        event_type=evento.event_type,
        correlation_id=evento.correlation_id,
        idempotency_key=evento.idempotency_key,
        pedido_id=pedido.pk,
        status=pedido.status,
        itens=len(evento.itens),
        total=str(evento.total),
        tentativa=tentativa,
        resultado="duplicado" if ja_aplicado else "ok",
        duracao_ms=duracao_ms,
    )


def _destino_log() -> dict:
    """Nome da fila/tópico de trabalho e da DLQ, conforme o broker ativo."""
    return dict(destino_log(EVENTO_PEDIDO_CRIADO))


def main() -> None:
    executar_worker(
        nome="pedido",
        evento=EVENTO_PEDIDO_CRIADO,
        handler=processar_pedido_criado,
        client_id="synapseshop-pedido-worker",
        falha_ativa=settings.PEDIDO_WORKER_FALHA_IDEM_KEYS,
    )


if __name__ == "__main__":
    main()