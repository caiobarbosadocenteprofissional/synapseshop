"""Consumidor AMQP com *ack* manual, reentrega controlada e DLQ."""

import logging
import time
from typing import Any, Callable, Dict

import pika
from django.conf import settings

from events.topology import TopologiaEvento
from services.log_estruturado import LoggerEstruturado
from services.messaging_base import (
    ler_tentativa,
    processar_evento,
)
from services.messaging_rabbit.topologia import conexao, declarar_topologia, fechar_recursos

logger = logging.getLogger("synapseshop.mensageria")
log = LoggerEstruturado(logger)


class ConsumidorEvento:
    """Consome um evento com *ack* manual, reentrega e DLQ.

    O handler recebe o dicionário do evento e o número da tentativa. Ele deve
    ser **idempotente**: a garantia aqui é de entrega pelo menos uma vez, não de
    processamento exatamente uma vez. Fila e DLQ vêm da topologia do evento.
    """

    def __init__(
        self,
        handler: Callable[[Dict[str, Any], int], None],
        topologia: TopologiaEvento,
        client_id: str = "",
    ) -> None:
        self._handler = handler
        self._topologia = topologia
        self._client_id = client_id
        self._conexao = None
        self._canal = None
        self._parado = False

    def parar(self) -> None:
        self._parado = True

    @property
    def topologia(self) -> TopologiaEvento:
        return self._topologia

    def executar(self) -> None:
        """Consome em laço até ``parar()`` ou o broker cair.

        A conexão só é refeita quando ela realmente cai: o laço interno apenas
        bombeia os eventos do socket com *timeout*, para que uma mensagem em
        processamento não seja interrompida por um tique do laço externo.
        """
        while not self._parado:
            try:
                self._conexao = conexao(self._client_id)
                self._canal = self._conexao.channel()
                declarar_topologia(self._canal)
                self._canal.basic_consume(
                    queue=self._topologia.fila,
                    on_message_callback=self._ao_receber,
                    auto_ack=False,
                )
                log(
                    "mensageria.consumidor.iniciado",
                    fila=self._topologia.fila,
                    prefetch=settings.RABBITMQ_PREFETCH,
                    max_retries=settings.MENSAGERIA_MAX_RETRIES,
                    dlq=self._topologia.fila_dlq,
                    cliente=self._client_id or None,
                )
                while not self._parado and self._conexao.is_open:
                    self._conexao.process_data_events(time_limit=1)
            except KeyboardInterrupt:
                # Ctrl+C tem de encerrar o worker: sem marcar a parada, o laço
                # voltaria a consumir e o processo nunca sairia.
                self._parado = True
                log("mensageria.consumidor.interrompido")
            except Exception as exc:  # noqa: BLE001 - reconecta com backoff
                log("mensageria.consumidor.falha", erro=str(exc))
                time.sleep(2)
            finally:
                self._fechar_recursos()

    def _fechar_recursos(self) -> None:
        fechar_recursos(self._canal, self._conexao)
        self._canal = None
        self._conexao = None

    def _ao_receber(self, canal, metodo, propriedades, corpo: bytes) -> None:
        headers = dict(getattr(propriedades, "headers", None) or {})
        tentativa = ler_tentativa(headers)
        correlation_id = getattr(propriedades, "correlation_id", None)

        def republicar(corpo_republicado, _evento, cabecalhos_novos):
            publicado = canal.basic_publish(
                exchange=self._topologia.exchange,
                routing_key=self._topologia.routing_key,
                body=corpo_republicado,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    correlation_id=correlation_id,
                    message_id=getattr(propriedades, "message_id", None),
                    timestamp=int(time.time()),
                    headers={**headers, **cabecalhos_novos},
                ),
                mandatory=True,
            )
            if publicado is False:
                # Sem confirmar a republicação, a original precisa ficar na fila:
                # requeue=True devolve a entrega para o broker em vez de perdê-la.
                canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=True)
                return "broker nao confirmou a republicacao; mensagem reenfileirada"
            return None

        def confirmar() -> None:
            canal.basic_ack(delivery_tag=metodo.delivery_tag)

        def matar(_corpo, _evento, _cabecalhos, _erro) -> bool:
            # nack sem requeue encaminha a mensagem para a DLQ; o broker leva o
            # corpo original, sem republicação.
            canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)
            return True

        processar_evento(
            corpo=corpo,
            tentativa=tentativa,
            handler=self._handler,
            republicar=republicar,
            confirmar=confirmar,
            matar=matar,
            campos=lambda: {"correlation_id": correlation_id},
            destino_dlq=self._topologia.fila_dlq,
        )
