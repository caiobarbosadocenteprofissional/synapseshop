"""Worker consumidor do evento ``PedidoCriado`` (Aula 9).

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
``services.messaging.ConsumidorPedidoCriado``, que aplica a política de
reentrega (recuo exponencial) e, ao esgotrar as tentativas, deixa a mensagem
morrer para a DLQ.

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

from events.contracts import ContratoInvalido, EventoPedidoCriado  # noqa: E402
from repositories.models import Pedido  # noqa: E402
from services import idempotencia  # noqa: E402
from services.messaging import ConsumidorPedidoCriado  # noqa: E402

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


def main() -> None:
    consumidor = ConsumidorPedidoCriado(processar_pedido_criado)
    # As chaves de deduplicação têm prazo de validade: as expiradas são
    # descartadas na subida do worker para a tabela não crescer sem limite.
    expiradas = idempotencia.limpar_expirados()
    _log(
        "worker.iniciado",
        fila=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
        dlq=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
        max_retries=settings.MENSAGERIA_MAX_RETRIES,
        idempotencia_ttl=settings.IDEMPOTENCIA_TTL_SEGUNDOS,
        chaves_expiradas_removidas=expiradas,
        falha_forcada=bool(settings.PEDIDO_WORKER_FALHA_IDEM_KEYS),
    )
    try:
        consumidor.executar()
    finally:
        _log("worker.encerrado")


if __name__ == "__main__":
    main()