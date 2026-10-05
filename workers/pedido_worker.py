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

import json
import logging
import os
import sys
import time
from fnmatch import fnmatchcase
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402  (após o ajuste de sys.path e DJANGO_SETTINGS_MODULE)

django.setup()

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from events.contracts import ContratoInvalido, EVENTO_PEDIDO_CRIADO, EventoPedidoCriado  # noqa: E402
from events.topology import topologia_de  # noqa: E402
from repositories.models import Pedido  # noqa: E402
from services import idempotencia  # noqa: E402
from services.events import PEDIDO_EM_PROCESSAMENTO, emitir_apos_commit  # noqa: E402
from services.messaging import ConsumidorEvento  # noqa: E402

logger = logging.getLogger("synapseshop.worker")


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: o contrato do
    # evento tem um campo `event_type` e a colisão de nome seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


class ErroForcadoDeTeste(RuntimeError):
    """Falha proposital para exercitar a reentrega e a DLQ (DoD da Aula 9)."""


class PedidoInexistente(RuntimeError):
    """O evento aponta para um pedido que não está no repositório."""


def _falha_forcada(idempotency_key: str) -> bool:
    """Informa se este pedido deve falhar de propósito (validação da DLQ)."""
    if os.environ.get("PEDIDO_WORKER_FALHAR_SEMPRE", "").lower() in ("1", "true", "yes"):
        return True
    return any(
        fnmatchcase(idempotency_key, padrao)
        for padrao in settings.PEDIDO_WORKER_FALHA_IDEM_KEYS
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
    """Nome da fila/tópico de trabalho e da DLQ, conforme o broker ativo.

    O log de subida precisa dizer onde a mensagem entra e onde a morta sai, e os
    dois nomes são diferentes entre AMQP e Kafka. A política (tentativas, TTL) é
    a mesma e vem sempre das mesmas settings; os nomes vêm da topologia do evento,
    que este worker consome — o mesmo par de ``main()``.
    """
    topologia = topologia_de(EVENTO_PEDIDO_CRIADO)
    if settings.MENSAGERIA_BROKER == "kafka":
        return {
            "broker": "kafka",
            "evento": topologia.evento,
            "topico": topologia.topico,
            "dlq": topologia.dlq,
            "grupo": topologia.grupo,
            "particoes": settings.KAFKA_PARTICOES,
        }
    return {
        "broker": "rabbitmq",
        "evento": topologia.evento,
        "fila": topologia.fila,
        "dlq": topologia.fila_dlq,
        "prefetch": settings.RABBITMQ_PREFETCH,
    }


def main() -> None:
    consumidor = ConsumidorEvento(
        processar_pedido_criado,
        topologia_de(EVENTO_PEDIDO_CRIADO),
        client_id="synapseshop-pedido-worker",
    )
    # As chaves de deduplicação têm prazo de validade: as expiradas são
    # descartadas na subida do worker para a tabela não crescer sem limite.
    expiradas = idempotencia.limpar_expirados()
    _log(
        "worker.iniciado",
        worker="pedido",
        max_retries=settings.MENSAGERIA_MAX_RETRIES,
        idempotencia_ttl=settings.IDEMPOTENCIA_TTL_SEGUNDOS,
        chaves_expiradas_removidas=expiradas,
        falha_forcada=bool(settings.PEDIDO_WORKER_FALHA_IDEM_KEYS),
        **_destino_log(),
    )
    try:
        consumidor.executar()
    finally:
        _log("worker.encerrado", worker="pedido")


if __name__ == "__main__":
    main()