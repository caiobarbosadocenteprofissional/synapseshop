"""Publicação AMQP na exchange de eventos."""

import time
import uuid
from typing import Any, Dict, Optional

import pika

from events.topology import TopologiaEvento
from services.messaging_base import (
    HEADER_TENTATIVA,
    MensageriaIndisponivel,
    ResultadoPublicacao,
    _log,
    serializar_evento,
)
from services.messaging_rabbit.topologia import conexao, declarar_topologia, fechar_recursos


class ProdutorEvento:
    """Publica eventos de domínio na exchange de eventos.

    A topologia é declarada na construção para que a API também funcione como
    *publisher* mesmo antes do worker existir (fila criada e vazia).
    """

    def __init__(self, topologia: TopologiaEvento, client_id: str = "synapseshop-api") -> None:
        self._topologia = topologia
        self._client_id = client_id
        self._conexao: Optional[pika.BlockingConnection] = None
        self._canal = None

    def __enter__(self) -> "ProdutorEvento":
        self.conectar()
        return self

    def __exit__(self, *_excecao) -> None:
        self.fechar()

    @property
    def topologia(self) -> TopologiaEvento:
        return self._topologia

    def conectar(self) -> None:
        try:
            self._conexao = conexao(self._client_id)
            self._canal = self._conexao.channel()
            self._canal.confirm_delivery()
            declarar_topologia(self._canal)
        except Exception as exc:  # noqa: BLE001 - erro de broker vira erro de domínio
            self.fechar()
            raise MensageriaIndisponivel(str(exc)) from exc

    def fechar(self) -> None:
        fechar_recursos(self._canal, self._conexao)
        self._canal, self._conexao = None, None

    def publicar(self, evento: Dict[str, Any], idempotency_key: str) -> ResultadoPublicacao:
        """Publica o evento e devolve o ``correlation_id`` da entrega."""
        corpo = serializar_evento(evento)
        correlation_id = str(evento.get("correlation_id") or uuid.uuid4())
        propriedades = pika.BasicProperties(
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=2,  # persistente: sobrevive a restart do broker
            correlation_id=correlation_id,
            message_id=evento.get("event_id"),
            timestamp=int(time.time()),
            headers={HEADER_TENTATIVA: 0},
        )
        iniciado = time.perf_counter()
        try:
            confirmado = self._canal.basic_publish(
                exchange=self._topologia.exchange,
                routing_key=self._topologia.routing_key,
                body=corpo,
                properties=propriedades,
                mandatory=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise MensageriaIndisponivel(str(exc)) from exc

        if confirmado is False:
            raise MensageriaIndisponivel("broker nao confirmou a publicacao")

        _log(
            "mensageria.publicado",
            event_type=evento.get("event_type"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            routing_key=self._topologia.routing_key,
            bytes=len(corpo),
            cliente=self._client_id or None,
            duracao_ms=round((time.perf_counter() - iniciado) * 1000, 3),
        )
        return ResultadoPublicacao(confirmado=True, identificador=correlation_id)
