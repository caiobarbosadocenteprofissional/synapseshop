"""Camada de mensageria assíncrona sobre RabbitMQ (Aula 9).

Entrega o par produtor/consumidor do evento ``PedidoCriado`` com três
responsabilidades:

1. **Topologia** — exchange de eventos, fila principal, dead-letter exchange
   (DLX) e dead-letter queue (DLQ), todas duráveis e declaradas de forma
   idempotente, para que API e worker subam em qualquer ordem.
2. **Publicação** — publicação persistente (``delivery_mode=2``) em exchange
   *topic*, com ``correlation_id`` para rastreio ponta a ponta e confirmação do
   broker (``confirm_delivery``) para que o produtor saiba se a mensagem entrou.
3. **Consumo com reentrega controlada** — *ack* manual (pelo menos uma vez),
   contador de tentativas no header ``x-retry-count``, recuo exponencial
   limitado por ``MENSAGERIA_BACKOFF_*`` e, ao esgotrar as tentativas,
   ``nack`` sem *requeue* para que o broker encaminhe a mensagem à DLQ.

O módulo não conhece o domínio: ele transporta dicionários JSON e devolve as
mensagens consumidas ao handler registrado. O contrato está em
``events/contracts.py`` e a regra de deduplicação em ``services/idempotencia.py``.

**Por que o *backoff* é feito no consumidor:** para esperar entre tentativas sem
perder a ordem nem acumular mensagens, o consumidor segura a entrega
(prefetch=1), republica a mesma mensagem com o contador incrementado e só então
confirma a original. A alternativa usual (filas de delay com TTL) foi
considerada e fica registrada em ``docs/DECISOES_TECNICAS_AULA9.md`` como
evolução natural: ela libera o consumidor durante a espera, ao custo de mais uma
fila por patamar de atraso.
"""

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

import pika
from django.conf import settings

logger = logging.getLogger("synapseshop.mensageria")

HEADER_TENTATIVA = "x-retry-count"


class MensageriaIndisponivel(RuntimeError):
    """O broker não pôde ser alcançado ou recusou a publicação."""


def _conexao() -> pika.BlockingConnection:
    """Abre uma conexão AMQP com heartbeat e timeout de bloqueio definidos."""
    parametros = pika.ConnectionParameters(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        virtual_host=settings.RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(
            settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
        ),
        heartbeat=30,
        blocked_connection_timeout=30,
        connection_attempts=3,
        retry_delay=2,
        socket_timeout=10,
    )
    return pika.BlockingConnection(parametros)


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `event_type`/`evento` e a colisão seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


class ProdutorPedidoCriado:
    """Publica eventos de domínio na exchange da Camada 5.

    A topologia é declarada na construção para que a API também funcione como
    *publisher* mesmo antes de o worker existir (fila criada e vazia).
    """

    def __init__(self) -> None:
        self._conexao: Optional[pika.BlockingConnection] = None
        self._canal = None

    def __enter__(self) -> "ProdutorPedidoCriado":
        self.conectar()
        return self

    def __exit__(self, *_excecao) -> None:
        self.fechar()

    def conectar(self) -> None:
        try:
            self._conexao = _conexao()
            self._canal = self._conexao.channel()
            self._canal.confirm_delivery()
            declarar_topologia(self._canal)
        except Exception as exc:  # noqa: BLE001 - erro de broker vira erro de domínio
            self.fechar()
            raise MensageriaIndisponivel(str(exc)) from exc

    def fechar(self) -> None:
        for recurso in (self._canal, self._conexao):
            try:
                if recurso is not None and recurso.is_open:
                    recurso.close()
            except Exception:  # noqa: BLE001 - encerramento é best effort
                pass
        self._canal = None
        self._conexao = None

    def publicar(self, evento: Dict[str, Any], idempotency_key: str) -> str:
        """Publica o evento e devolve o ``correlation_id`` da entrega."""
        corpo = json.dumps(evento, ensure_ascii=False).encode("utf-8")
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
                exchange=settings.RABBITMQ_EXCHANGE,
                routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
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
            routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
            bytes=len(corpo),
            duracao_ms=round((time.perf_counter() - iniciado) * 1000, 3),
        )
        return correlation_id


def declarar_topologia(canal) -> None:
    """Declara exchange, fila, DLX e DLQ. Idempotente por natureza do AMQP."""
    canal.exchange_declare(
        exchange=settings.RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
    )
    canal.exchange_declare(exchange=settings.RABBITMQ_DLX, exchange_type="direct", durable=True)

    canal.queue_declare(queue=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ, durable=True)
    canal.queue_bind(
        exchange=settings.RABBITMQ_DLX,
        queue=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
        routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
    )

    # A fila principal morre para a DLQ: basta um nack sem requeue para que o
    # broker rota a mensagem, sem que o consumidor precise republicar nada.
    canal.queue_declare(
        queue=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.RABBITMQ_DLX,
            "x-dead-letter-routing-key": settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
        },
    )
    canal.queue_bind(
        exchange=settings.RABBITMQ_EXCHANGE,
        queue=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
        routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
    )
    canal.basic_qos(prefetch_count=settings.RABBITMQ_PREFETCH)


def _esperar_reentrega(tentativa: int) -> float:
    """Recuo exponencial limitado por ``MENSAGERIA_BACKOFF_MAX_MS``."""
    atraso_ms = min(
        settings.MENSAGERIA_BACKOFF_BASE_MS * (2 ** (tentativa - 1)),
        settings.MENSAGERIA_BACKOFF_MAX_MS,
    )
    return atraso_ms / 1000.0


class ConsumidorPedidoCriado:
    """Consome ``PedidoCriado`` com *ack* manual, reentrega e DLQ.

    O handler recebe o dicionário do evento e o número da tentativa. Ele deve
    ser **idempotente**: a garantia aqui é de entrega pelo menos uma vez, não de
    processamento exatamente uma vez.
    """

    def __init__(self, handler: Callable[[Dict[str, Any], int], None]) -> None:
        self._handler = handler
        self._conexao = None
        self._canal = None
        self._parado = False

    def parar(self) -> None:
        self._parado = True

    def executar(self) -> None:
        """Consome em laço até ``parar()`` ou o broker cair.

        A conexão só é refeita quando ela realmente cai: o laço interno apenas
        bombeia os eventos do socket com *timeout*, para que uma mensagem em
        processamento não seja interrompida por um tique do laço externo.
        """
        while not self._parado:
            try:
                self._conexao = _conexao()
                self._canal = self._conexao.channel()
                declarar_topologia(self._canal)
                self._canal.basic_consume(
                    queue=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
                    on_message_callback=self._ao_receber,
                    auto_ack=False,
                )
                _log(
                    "mensageria.consumidor.iniciado",
                    fila=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
                    prefetch=settings.RABBITMQ_PREFETCH,
                    max_retries=settings.MENSAGERIA_MAX_RETRIES,
                    dlq=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
                )
                while not self._parado and self._conexao.is_open:
                    self._conexao.process_data_events(time_limit=1)
            except KeyboardInterrupt:
                _log("mensageria.consumidor.interrompido")
            except Exception as exc:  # noqa: BLE001 - reconecta com backoff
                _log("mensageria.consumidor.falha", erro=str(exc))
                time.sleep(2)
            finally:
                self._fechar_recursos()

    def _fechar_recursos(self) -> None:
        for recurso in (self._canal, self._conexao):
            try:
                if recurso is not None and recurso.is_open:
                    recurso.close()
            except Exception:  # noqa: BLE001
                pass
        self._canal = None
        self._conexao = None

    def _tentativa(self, propriedades) -> int:
        cabecalhos = getattr(propriedades, "headers", None) or {}
        try:
            return int(cabecalhos.get(HEADER_TENTATIVA, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _ao_receber(self, canal, metodo, propriedades, corpo: bytes) -> None:
        tentativa = self._tentativa(propriedades)
        correlation_id = getattr(propriedades, "correlation_id", None)
        iniciado = time.perf_counter()
        try:
            evento = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Corpo ilegível não tem como ser reprocessado: vai direto para a DLQ.
            self._matar(canal, metodo, correlation_id, f"corpo invalido: {exc}", tentativa, iniciado)
            return

        chave = evento.get("idempotency_key") if isinstance(evento, dict) else None
        try:
            self._handler(evento, tentativa)
        except Exception as exc:  # noqa: BLE001 - política de falha do consumidor
            self._reentregar(canal, metodo, propriedades, corpo, evento, chave, exc, tentativa, correlation_id, iniciado)
            return

        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        _log(
            "mensageria.consumido",
            correlation_id=correlation_id,
            idempotency_key=chave,
            tentativa=tentativa,
            resultado="ok",
            duracao_ms=round((time.perf_counter() - iniciado) * 1000, 3),
        )

    def _reentregar(
        self, canal, metodo, propriedades, corpo, evento, chave, exc, tentativa, correlation_id, iniciado
    ) -> None:
        """Republica com tentativa+1 e recuo exponencial, ou mata para a DLQ."""
        if tentativa >= settings.MENSAGERIA_MAX_RETRIES:
            self._matar(canal, metodo, correlation_id, str(exc), tentativa, iniciado, chave)
            return

        proxima = tentativa + 1
        espera = _esperar_reentrega(proxima)
        cabecalhos = dict(getattr(propriedades, "headers", None) or {})
        cabecalhos[HEADER_TENTATIVA] = proxima
        cabecalhos["x-ultimo-erro"] = str(exc)[:500]

        republicada = canal.basic_publish(
            exchange=settings.RABBITMQ_EXCHANGE,
            routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
            body=corpo,
            properties=pika.BasicProperties(
                content_type="application/json",
                content_encoding="utf-8",
                delivery_mode=2,
                correlation_id=correlation_id,
                message_id=getattr(propriedades, "message_id", None),
                timestamp=int(time.time()),
                headers=cabecalhos,
            ),
            mandatory=True,
        )
        if republicada is False:
            # Sem confirmar a republicação, a original precisa ficar na fila:
            # requeue=True devolve a entrega para o broker em vez de perdê-la.
            canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=True)
            _log(
                "mensageria.reentrega.falhou",
                correlation_id=correlation_id,
                idempotency_key=chave,
                tentativa=tentativa,
                erro="broker nao confirmou a republicacao; mensagem reenfileirada",
            )
            return

        time.sleep(espera)
        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        _log(
            "mensageria.reentrega",
            correlation_id=correlation_id,
            idempotency_key=chave,
            tentativa=tentativa,
            proxima_tentativa=proxima,
            espera_ms=round(espera * 1000, 3),
            erro=str(exc)[:500],
            duracao_ms=round((time.perf_counter() - iniciado) * 1000, 3),
        )

    def _matar(self, canal, metodo, correlation_id, erro, tentativa, iniciado, chave=None) -> None:
        """Esgotou as tentativas: nack sem requeue encaminha para a DLQ."""
        canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)
        _log(
            "mensageria.dlq",
            correlation_id=correlation_id,
            idempotency_key=chave,
            tentativa=tentativa,
            dlq=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
            erro=erro[:500],
            duracao_ms=round((time.perf_counter() - iniciado) * 1000, 3),
        )