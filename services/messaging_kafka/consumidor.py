"""Consumidor Kafka com offset manual, reentrega controlada e DLQ."""

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from confluent_kafka import Consumer, KafkaError, KafkaException, Message
from django.conf import settings

from events.topology import TopologiaEvento
from services.log_estruturado import LoggerEstruturado
from services.messaging_base import (
    ler_tentativa,
    processar_evento,
)
from services.messaging_kafka.observabilidade import (
    registrar_ociosidade,
    tempo_de_fila,
)
from services.messaging_kafka.publicacao import publicar_retencao
from services.messaging_kafka.topicos import _erro_do_broker, declarar_topologia

logger = logging.getLogger("synapseshop.mensageria")
log = LoggerEstruturado(logger)


def _chave_de(evento) -> Optional[str]:
    """Chave de idempotência do evento, que é também a chave da mensagem."""
    return evento.get("idempotency_key") if isinstance(evento, dict) else None


class ConsumidorEvento:
    """Consome um evento com offset manual, reentrega e DLQ.

    O handler recebe o dicionário do evento e o número da tentativa. Ele deve
    ser **idempotente**: a garantia aqui é de entrega pelo menos uma vez, não de
    processamento exatamente uma vez.

    Grupo, tópico e DLQ vêm da topologia do evento, não de settings soltas: é o
    que permite que ``pedido-worker`` e ``notificacao-worker`` usem a mesma
    classe sem que um possa ler o evento do outro.
    """

    def __init__(
        self,
        handler: Callable[[Dict[str, Any], int], None],
        topologia: TopologiaEvento,
        client_id: str = "synapseshop-worker",
    ) -> None:
        self._handler = handler
        self._topologia = topologia
        self._client_id = client_id
        self._consumidor: Optional[Consumer] = None
        self._parado = False
        self._particoes: List[int] = []
        self._ultimo_evento = time.monotonic()

    def parar(self) -> None:
        self._parado = True

    @property
    def particoes(self) -> List[int]:
        """Partições atribuídas a este consumidor dentro do grupo."""
        return list(self._particoes)

    @property
    def topologia(self) -> TopologiaEvento:
        return self._topologia

    def executar(self) -> None:
        """Consome em laço até ``parar()`` ou o broker cair.

        O consumidor é reconstruído só quando a conexão realmente cai; o laço
        interno apenas bombeia eventos, para que uma mensagem em processamento
        não seja interrompida por um tique do laço externo.
        """
        while not self._parado:
            consumidor = None
            try:
                # O broker roda com auto-criação desligada: quem garante a
                # topologia é a aplicação. Declarar aqui permite subir o worker
                # antes da API (e vice-versa) sem estado inicial compartilhado.
                declarar_topologia()
                consumidor = Consumer(
                    {
                        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                        "group.id": self._topologia.grupo,
                        "enable.auto.commit": False,
                        "auto.offset.reset": settings.KAFKA_AUTO_OFFSET_RESET,
                        "session.timeout.ms": settings.KAFKA_SESSION_TIMEOUT_MS,
                        "max.poll.interval.ms": settings.KAFKA_MAX_POLL_INTERVAL_MS,
                        "client.id": f"{self._client_id}-{uuid.uuid4().hex[:6]}",
                    }
                )
                consumidor.subscribe(
                    [self._topologia.topico],
                    on_assign=self._ao_atribuir,
                    on_revoke=self._ao_revogar,
                )
                self._consumidor = consumidor
                self._ultimo_evento = time.monotonic()
                while not self._parado:
                    msg = consumidor.poll(settings.KAFKA_POLL_TIMEOUT_S)
                    if msg is None:
                        self._registrar_ociosidade()
                        continue
                    if msg.error():
                        # _PARTITION_EOF é notificação de fim de log, não falha:
                        # tratá-la como erro derrubaria o consumidor no idle.
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        raise KafkaException(msg.error())
                    self._ultimo_evento = time.monotonic()
                    self._ao_receber(msg)
            except KeyboardInterrupt:
                # Ctrl+C tem de encerrar o worker: sem marcar a parada, o laço
                # voltaria a consumir e o processo nunca sairia.
                self._parado = True
                log("mensageria.consumidor.interrompido")
            except Exception as exc:  # noqa: BLE001 - reconecta com backoff
                log(
                    "mensageria.consumidor.falha",
                    erro=_erro_do_broker(exc),
                    broker="kafka",
                    topico=self._topologia.topico,
                    grupo=self._topologia.grupo,
                )
                time.sleep(2)
            finally:
                self._fechar(consumidor)

    def _registrar_ociosidade(self) -> None:
        self._ultimo_evento = registrar_ociosidade(
            topologia=self._topologia,
            client_id=self._client_id,
            particoes=self._particoes,
            ultimo_evento=self._ultimo_evento,
        )

    def _fechar(self, consumidor) -> None:
        if consumidor is not None:
            try:
                consumidor.close()
            except Exception:  # noqa: BLE001
                pass
        if consumidor is self._consumidor:
            self._consumidor = None
        self._particoes = []

    def _ao_atribuir(self, consumidor, particoes) -> None:
        self._particoes = [p.partition for p in particoes]
        log(
            "kafka.consumidor.particoes",
            grupo=self._topologia.grupo,
            topico=self._topologia.topico,
            cliente=consumidor.memberid() if hasattr(consumidor, "memberid") else None,
            particoes=self._particoes,
            total_particoes=settings.KAFKA_PARTICOES,
        )

    def _ao_revogar(self, _consumidor, particoes) -> None:
        log(
            "kafka.consumidor.rebalanceamento",
            grupo=self._topologia.grupo,
            topico=self._topologia.topico,
            particoes_revogadas=[p.partition for p in particoes],
        )
        self._particoes = []

    def _confirma(self, msg: Message, contexto: str) -> None:
        """Faz commit do offset somente depois do efeito."""
        try:
            self._consumidor.commit(message=msg, asynchronous=False)
        except Exception as exc:  # noqa: BLE001
            log("kafka.commit.falhou", erro=_erro_do_broker(exc), contexto=contexto)

    def _ao_receber(self, msg: Message) -> None:
        cabecalhos = list(msg.headers() or [])
        tentativa = ler_tentativa(cabecalhos)
        tempo_fila_ms = tempo_de_fila(msg)

        def republicar(corpo, evento, cabecalhos_novos):
            republicada = publicar_retencao(
                corpo=corpo,
                chave=_chave_de(evento),
                cabecalhos=cabecalhos_novos,
                client_id=self._client_id,
                destino=self._topologia.topico,
            )
            if republicada is None:
                # Sem confirmar a republicação, o offset não é commitado: a
                # mensagem volta a ser entregue em vez de ser perdida.
                return "broker nao confirmou a republicacao; offset nao commitado"
            return None

        def confirmar() -> None:
            self._confirma(msg, "ok")

        def matar(corpo, evento, cabecalhos_dlq, _erro) -> bool:
            publicada = publicar_retencao(
                corpo=corpo,
                chave=_chave_de(evento),
                cabecalhos={
                    **cabecalhos_dlq,
                    "x-tópico-origem": msg.topic(),
                    "x-particao-origem": str(msg.partition()),
                    "x-offset-origem": str(msg.offset()),
                    "x-morto-em": str(int(time.time() * 1000)),
                },
                client_id=self._client_id,
                destino=self._topologia.dlq,
            )
            if publicada is None:
                return False
            self._confirma(msg, "dlq")
            return True

        processar_evento(
            corpo=msg.value(),
            tentativa=tentativa,
            handler=self._handler,
            republicar=republicar,
            confirmar=confirmar,
            matar=matar,
            campos=lambda: {
                "topico": msg.topic(),
                "particao": msg.partition(),
                "offset": msg.offset(),
                "tempo_fila_ms": tempo_fila_ms,
            },
            destino_dlq=self._topologia.dlq,
        )
