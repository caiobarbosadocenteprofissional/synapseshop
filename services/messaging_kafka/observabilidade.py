"""Métricas de consumo: tempo de fila e batimento do consumidor ocioso."""

import time
from typing import List, Optional

from confluent_kafka import Message
from django.conf import settings

from events.topology import TopologiaEvento
from services.messaging_base import _log


def tempo_de_fila(msg: Message) -> Optional[float]:
    """Tempo entre a gravação no log e o consumo, em ms.

    O timestamp do broker e o instante da leitura caem no mesmo host (o
    contêiner do worker), então a subtração mede a espera na particao — que na
    Aula 9 ficou misturada no total, por nao haver equivalente no AMQP.
    """
    try:
        # A API devolve (tipo, instante_em_ms); o instante é o segundo elemento.
        marca = msg.timestamp()[1]
    except Exception:  # noqa: BLE001 - alguns formatos de log nao tem timestamp
        return None
    if marca is None or marca < 0:
        return None
    return round((time.time() * 1000.0 - marca), 3)


def registrar_ociosidade(
    *,
    topologia: TopologiaEvento,
    client_id: str,
    particoes: List[int],
    ultimo_evento: float,
) -> float:
    """Batimento do consumidor ocioso; devolve o instante do último evento.

    "O worker está vivo" não aparece em log nenhum quando não há tráfego, e
    essa é exatamente a situação em que se duvida do worker. O registro sai
    no nível ``info`` — é evidência de operação, não alarme — e só quando o
    silêncio já dura mais que ``MENSAGERIA_HEARTBEAT_S``.
    """
    if settings.MENSAGERIA_HEARTBEAT_S <= 0:
        return ultimo_evento
    silencio = time.monotonic() - ultimo_evento
    if silencio < settings.MENSAGERIA_HEARTBEAT_S:
        return ultimo_evento
    agora = time.monotonic()
    _log(
        "mensageria.consumidor.ocioso",
        topico=topologia.topico,
        grupo=topologia.grupo,
        cliente=client_id,
        particoes=particoes,
        silencio_s=round(silencio, 1),
    )
    return agora
