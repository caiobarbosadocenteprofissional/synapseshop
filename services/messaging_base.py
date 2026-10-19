"""Peças compartilhadas pelos transportes AMQP e Kafka.

Os dois transportes têm o mesmo contrato de domínio — publicar um dicionário
JSON, consumir com pelo menos uma vez, reentregar com recuo exponencial e matar
para a DLQ — mas falam protocolos diferentes. Tudo que não depende do protocolo
mora aqui: o log estruturado, os nomes dos headers de controle, o cálculo do
recuo e a leitura do contador de tentativas, que chega como ``dict`` no AMQP e
como lista de pares no Kafka.

Manter esses detalhes num só lugar garante que a política de reentrega não
divirja entre os brokers; o que é específico de cada um (conexão, topologia,
ack/commit) permanece no módulo do transporte.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any, Dict

from django.conf import settings

from services.log_estruturado import log_evento

logger = logging.getLogger("synapseshop.mensageria")

HEADER_TENTATIVA = "x-retry-count"
HEADER_ERRO = "x-ultimo-erro"


class MensageriaIndisponivel(RuntimeError):
    """O broker não pôde ser alcançado ou recusou a publicação."""


def _log(nome_evento: str, **campos: Any) -> None:
    log_evento(logger, nome_evento, **campos)


def esperar_reentrega(tentativa: int) -> float:
    """Recuo exponencial limitado por ``MENSAGERIA_BACKOFF_MAX_MS``."""
    atraso_ms = min(
        settings.MENSAGERIA_BACKOFF_BASE_MS * (2 ** (tentativa - 1)),
        settings.MENSAGERIA_BACKOFF_MAX_MS,
    )
    return atraso_ms / 1000.0


def ler_tentativa(cabecalhos) -> int:
    """Lê ``x-retry-count`` de headers AMQP (mapa) ou Kafka (lista de pares)."""
    if not cabecalhos:
        return 0
    pares = cabecalhos.items() if isinstance(cabecalhos, Mapping) else cabecalhos
    for nome, valor in pares:
        if nome != HEADER_TENTATIVA:
            continue
        if isinstance(valor, bytes):
            valor = valor.decode("utf-8", "replace")
        try:
            return int(valor or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def serializar_evento(evento: Dict[str, Any]) -> bytes:
    """Serializa o envelope em JSON UTF-8, preservando acentos."""
    return json.dumps(evento, ensure_ascii=False).encode("utf-8")
