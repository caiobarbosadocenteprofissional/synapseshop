"""Consumidor Kafka com offset manual, reentrega controlada e DLQ."""

import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from confluent_kafka import Consumer, KafkaError, KafkaException, Message
from django.conf import settings

from events.topology import TopologiaEvento
from services.messaging_base import (
    HEADER_ERRO,
    HEADER_TENTATIVA,
    _log,
    esperar_reentrega,
    ler_tentativa,
)
from services.messaging_kafka.observabilidade import (
    registrar_ociosidade,
    tempo_de_fila,
)
from services.messaging_kafka.publicacao import publicar_retencao
from services.messaging_kafka.topicos import _erro_do_broker, declarar_topologia


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
                _log("mensageria.consumidor.interrompido")
            except Exception as exc:  # noqa: BLE001 - reconecta com backoff
                _log(
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
        _log(
            "kafka.consumidor.particoes",
            grupo=self._topologia.grupo,
            topico=self._topologia.topico,
            cliente=consumidor.memberid() if hasattr(consumidor, "memberid") else None,
            particoes=self._particoes,
            total_particoes=settings.KAFKA_PARTICOES,
        )

    def _ao_revogar(self, _consumidor, particoes) -> None:
        _log(
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
            _log("kafka.commit.falhou", erro=_erro_do_broker(exc), contexto=contexto)

    def _ao_receber(self, msg: Message) -> None:
        cabecalhos = list(msg.headers() or [])
        tentativa = ler_tentativa(cabecalhos)
        inicio = time.perf_counter()
        tempo_fila_ms = tempo_de_fila(msg)
        try:
            evento = json.loads(msg.value().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            # Corpo ilegível não tem como ser reprocessado: vai direto para a DLQ.
            self._matar(
                msg, cabecalhos, None, None, tentativa,
                f"corpo invalido: {exc}", inicio, tempo_fila_ms,
            )
            return

        chave = evento.get("idempotency_key") if isinstance(evento, dict) else None
        try:
            self._handler(evento, tentativa)
        except Exception as exc:  # noqa: BLE001 - política de falha do consumidor
            self._reentregar(
                msg, cabecalhos, evento, chave, exc, tentativa, inicio, tempo_fila_ms
            )
            return

        self._confirma(msg, "ok")
        _log(
            "mensageria.consumido",
            correlation_id=evento.get("correlation_id") if isinstance(evento, dict) else None,
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            tentativa=tentativa,
            resultado="ok",
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    def _reentregar(
        self, msg, cabecalhos, evento, chave, exc, tentativa, inicio, tempo_fila_ms
    ) -> None:
        """Republica com tentativa+1 e recuo exponencial, ou mata para a DLQ."""
        if tentativa >= settings.MENSAGERIA_MAX_RETRIES:
            self._matar(
                msg, cabecalhos, evento, chave, tentativa, str(exc), inicio, tempo_fila_ms
            )
            return

        proxima = tentativa + 1
        espera = esperar_reentrega(proxima)
        republished = publicar_retencao(
            evento=evento,
            chave=chave,
            cabecalhos={HEADER_TENTATIVA: proxima, HEADER_ERRO: str(exc)[:500]},
            client_id=self._client_id,
            destino=self._topologia.topico,
        )
        if republished is None:
            # Sem confirmar a republicação, o offset não é commitado: a
            # mensagem volta a ser entregue em vez de ser perdida.
            _log(
                "mensageria.reentrega.falhou",
                idempotency_key=chave,
                tentativa=tentativa,
                topico=msg.topic(),
                particao=msg.partition(),
                offset=msg.offset(),
                erro="broker nao confirmou a republicacao; offset nao commitado",
            )
            time.sleep(espera)
            return

        time.sleep(espera)
        self._confirma(msg, f"reentrega:{proxima}")
        _log(
            "mensageria.reentrega",
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            tentativa=tentativa,
            proxima_tentativa=proxima,
            espera_ms=round(espera * 1000, 3),
            erro=str(exc)[:500],
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    def _matar(self, msg, cabecalhos, evento, chave, tentativa, erro, inicio, tempo_fila_ms) -> None:
        """Esgotou as tentativas: publica na DLQ e então confirma o offset."""
        cabecalhos_dlq = {
            HEADER_TENTATIVA: tentativa,
            HEADER_ERRO: str(erro)[:500],
            "x-tópico-origem": msg.topic(),
            "x-particao-origem": str(msg.partition()),
            "x-offset-origem": str(msg.offset()),
            "x-morto-em": str(int(time.time() * 1000)),
        }
        publicada = publicar_retencao(
            evento=evento,
            chave=chave,
            cabecalhos=cabecalhos_dlq,
            client_id=self._client_id,
            destino=self._topologia.dlq,
        )
        if publicada is None:
            _log(
                "mensageria.dlq.falhou",
                idempotency_key=chave,
                tentativa=tentativa,
                erro="broker nao confirmou a publicacao na DLQ; offset nao commitado",
            )
            return
        self._confirma(msg, "dlq")
        _log(
            "mensageria.dlq",
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            dlq=self._topologia.dlq,
            tentativa=tentativa,
            erro=str(erro)[:500],
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )
