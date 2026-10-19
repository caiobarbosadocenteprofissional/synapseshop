"""Bootstrap e helpers compartilhados pelos workers de eventos.

Os dois workers têm o mesmo ciclo de vida: configuram o Django, criam o
``ConsumidorEvento`` da topologia do evento, limpam chaves de idempotência
expiradas, registram o destino no log e executam até receber sinal. O que muda
entre eles é apenas o evento consumido e o handler — e é isso que cada módulo
``workers/*_worker.py`` declara.
"""

import logging
import os
import sys
from fnmatch import fnmatchcase
from typing import Any, Iterable, Mapping

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402  (após o ajuste de sys.path e DJANGO_SETTINGS_MODULE)

django.setup()

from django.conf import settings  # noqa: E402

from events.topology import topologia_de  # noqa: E402
from services import idempotencia  # noqa: E402
from services.log_estruturado import log_evento  # noqa: E402
from services.messaging import ConsumidorEvento  # noqa: E402

logger = logging.getLogger("synapseshop.worker")


def _log(nome_evento: str, **campos: Any) -> None:
    log_evento(logger, nome_evento, **campos)


class ErroForcadoDeTeste(RuntimeError):
    """Falha proposital para exercitar a reentrega e a DLQ (DoD das Aulas 9/11)."""


def falha_forcada(
    candidatos: Iterable[str], variavel_ambiente: str, padroes: Iterable[str]
) -> bool:
    """Informa se a mensagem deve falhar de propósito (validação da DLQ)."""
    if os.environ.get(variavel_ambiente, "").lower() in ("1", "true", "yes"):
        return True
    return any(
        fnmatchcase(candidato, padrao)
        for candidato in candidatos
        for padrao in padroes
        if candidato
    )


def destino_log(evento: str) -> Mapping[str, Any]:
    """Nome da fila/tópico de trabalho e da DLQ, conforme o broker ativo."""
    topologia = topologia_de(evento)
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


def executar_worker(*, nome, evento, handler, client_id, falha_ativa) -> None:
    """Ciclo de vida comum: consumir até o encerramento, com log de subida/saída."""
    consumidor = ConsumidorEvento(
        handler,
        topologia_de(evento),
        client_id=client_id,
    )
    # As chaves de deduplicação têm prazo de validade: as expiradas são
    # descartadas na subida do worker para a tabela não crescer sem limite.
    expiradas = idempotencia.limpar_expirados()
    _log(
        "worker.iniciado",
        worker=nome,
        max_retries=settings.MENSAGERIA_MAX_RETRIES,
        idempotencia_ttl=settings.IDEMPOTENCIA_TTL_SEGUNDOS,
        chaves_expiradas_removidas=expiradas,
        falha_forcada=bool(falha_ativa),
        **destino_log(evento),
    )
    try:
        consumidor.executar()
    finally:
        _log("worker.encerrado", worker=nome)
