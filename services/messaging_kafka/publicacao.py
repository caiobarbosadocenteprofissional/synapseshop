"""Republicação no mesmo tópico ou na DLQ, com um produtor dedicado."""

import json
import uuid
from typing import List, Optional, Tuple

from confluent_kafka import KafkaException, Producer
from django.conf import settings

from services.messaging_base import _log, serializar_evento
from services.messaging_kafka.topicos import _erro_do_broker


def publicar_retencao(
    *,
    evento,
    chave,
    cabecalhos,
    client_id: str,
    destino: str,
) -> Optional[Tuple[int, int]]:
    """Republica o mesmo corpo com novos headers, para reentrega ou DLQ.

    Um produtor dedicado é criado por chamada: o consumidor segura um
    ``Consumer`` de uma partição por vez, e misturar os papéis no mesmo objeto
    tornaria a reconexão do consumidor dependente da publicação.
    """
    cabecalhos = {str(nome): str(valor) for nome, valor in (cabecalhos or {}).items()}
    if not isinstance(evento, dict) or not chave:
        # Sem corpo reenviável (JSON inválido), a DLQ recebe o registro bruto
        # para que a mensagem morta continue inspecionável.
        valor = evento if isinstance(evento, (bytes, str)) else json.dumps(
            {"erro": "evento sem corpo reenviável"}, ensure_ascii=False
        )
        valor = valor.encode("utf-8") if isinstance(valor, str) else valor
        chave = chave or str(uuid.uuid4())
    else:
        valor = serializar_evento(evento)

    entrega: List[Tuple[Optional[int], Optional[int]]] = []
    erro: List[Exception] = []

    def confirmado(err, msg) -> None:
        if err is not None:
            erro.append(KafkaException(err))
            return
        entrega.append((msg.partition(), msg.offset()))

    produtor = Producer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "acks": settings.KAFKA_PRODUCER_ACKS,
            "client.id": client_id,
        }
    )
    try:
        produtor.produce(
            topic=destino,
            key=str(chave).encode("utf-8"),
            value=valor,
            headers=cabecalhos,
            on_delivery=confirmado,
        )
        restantes = produtor.flush(10)
    except Exception as exc:  # noqa: BLE001
        _log("kafka.republicacao.erro", topico=destino, erro=_erro_do_broker(exc))
        return None
    finally:
        try:
            produtor.flush(1)
        except Exception:  # noqa: BLE001
            pass
    if erro:
        _log("kafka.republicacao.erro", topico=destino, erro=_erro_do_broker(erro[0]))
        return None
    if restantes or not entrega:
        return None
    return entrega[0]
