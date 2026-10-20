"""Camada de mensageria assíncrona sobre Apache Kafka (Aulas 10 e 11).

Entrega o par produtor/consumidor do evento ``PedidoCriado`` que o transporte
AMQP da Aula 9 entregou, com as semânticas próprias do Kafka:

1. **Topologia** — tópicos ``pedidos.pedidocriado`` e ``pedidos.pedidocriado.dlq``,
   criados via ``KafkaAdminClient`` de forma idempotente (``TopicAlreadyExists``
   é ignorado), com ``KAFKA_PARTICOES`` partições e retenção configurável por
   ``KAFKA_RETENTION_MS``. A API e o worker declaram a topologia na subida, como
   no AMQP, para que subam em qualquer ordem. Na Aula 11 a topologia deixou de ser
   do evento e passou a ser **por evento** (``events/topology.py``): este módulo
   cria o par tópico/DLQ de cada evento declarado, sem conhecer os nomes.
2. **Publicação** — a **chave da mensagem é a ``idempotency_key``**. Como o
   Kafka distribui por ``hash(chave) % partições``, todos os eventos do mesmo
   pedido caem na mesma partição e portanto são consumidos em ordem; partições
   diferentes são consumidas em paralelo. A confirmação é feita com
   ``acks=all`` e ``flush`` — o produtor só devolve sucesso depois que o líder
   (e as réplicas) aceitaram o registro.
3. **Consumo com reentrega controlada** — ``enable.auto.commit=False``: o offset
   é commitado **depois** do efeito, o que dá entrega pelo menos uma vez sem
   perder evento em queda do consumidor. O contador de tentativas viaja no header
   ``x-retry-count`` e, ao esgotar ``MENSAGERIA_MAX_RETRIES``, a mensagem é
   publicada no tópico da DLQ e só então o offset é commitado.

Diferenças em relação ao AMQP que valem registro:

- **Não há *dead-letter exchange* nativa.** O roteamento da mensagem morta é
  feito pela aplicação, publicando no tópico da DLQ. O preço é não haver
  atomicidade entre "publicar na DLQ" e "commit do offset": se o processo cair
  entre as duas, a mensagem é reentregue e vai de novo para a DLQ, o que é
  inofensivo porque a leitura da DLQ é humana e a duplicata é identificável.
  Em troca, a DLQ vira um **log consultável e inspecionável**, que é o motivo de
  existir a Aula 10.
- **Não há reentrega nativa por mensagem.** Reentregar é republicar no mesmo
  tópico com o contador incrementado; é a mesma política da Aula 9, e por isso
  o backoff é feito segurando o offset (o consumidor não faz commit antes de
  republicar).
- **A retenção é o ganho real.** O tópico guarda o histórico por
  ``KAFKA_RETENTION_MS``, então um consumidor novo ou o reprocessamento por
  offset são operações ordinárias, e não uma fila que precise sobreviver a um
  broker.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from confluent_kafka import KafkaException, Producer
from django.conf import settings

from events.topology import TopologiaEvento
from services.messaging_base import (
    HEADER_ERRO,
    HEADER_TENTATIVA,
    MensageriaIndisponivel,
    _log,
    esperar_reentrega,
    ler_tentativa,
    serializar_evento,
)
from services.messaging_kafka.consumidor import ConsumidorEvento
from services.messaging_kafka.publicacao import publicar_retencao
from services.messaging_kafka.topicos import _erro_do_broker, declarar_topologia

HEADER_EVENTO = "event_type"


class ProdutorEvento:
    """Publica eventos de domínio no tópico do evento que lhe foi entregue.

    A chave da mensagem é a ``idempotency_key``, o que dá ordenação por pedido.
    A topologia é declarada na construção para que a API também publique antes de
    o worker existir. Quem usa esta classe não diz qual evento publica — diz o
    que faz com a topologia, e é o mesmo caminho para ``PedidoCriado``,
    ``PagamentoProcessado`` e ``NotificacaoEnviada``.
    """

    def __init__(self, topologia: TopologiaEvento, client_id: str = "synapseshop-api") -> None:
        self._topologia = topologia
        self._client_id = client_id
        self._produtor: Optional[Producer] = None

    @property
    def topico(self) -> str:
        return self._topologia.topico

    def __enter__(self) -> "ProdutorEvento":
        self.conectar()
        return self

    def __exit__(self, *_excecao) -> None:
        self.fechar()

    def conectar(self) -> None:
        try:
            self._produtor = Producer(
                {
                    "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                    "acks": settings.KAFKA_PRODUCER_ACKS,
                    "linger.ms": settings.KAFKA_PRODUCER_LINGER_MS,
                    "client.id": self._client_id,
                }
            )
            declarar_topologia()
        except Exception as exc:  # noqa: BLE001 - erro de broker vira erro de dominio
            self.fechar()
            raise MensageriaIndisponivel(_erro_do_broker(exc)) from exc

    def fechar(self) -> None:
        if self._produtor is not None:
            try:
                self._produtor.flush(5)
            except Exception:  # noqa: BLE001 - encerramento é best effort
                pass
        self._produtor = None

    def publicar(
        self,
        evento: Dict[str, Any],
        idempotency_key: str,
        topico: Optional[str] = None,
        cabecalhos: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Publica o evento e devolve ``(particao, offset)`` da entrega.

        ``topico`` e ``cabecalhos`` existem para a reentrega e para a DLQ, que
        escrevem no mesmo tópico com contador de tentativa e último erro.
        """
        destino = topico or self._topologia.topico
        corpo = serializar_evento(evento)
        cabecalhos = {
            HEADER_TENTATIVA: 0,
            HEADER_EVENTO: str(evento.get("event_type") or ""),
            "event_id": str(evento.get("event_id") or ""),
            **(cabecalhos or {}),
        }
        # O cliente Kafka exige header em str/bytes: o contador de tentativa é
        # inteiro na memória e vira texto na borda, num ponto só.
        cabecalhos = {str(nome): str(valor) for nome, valor in cabecalhos.items()}
        entrega: List[Tuple[Optional[int], Optional[int]]] = []
        erro: List[Exception] = []

        def confirmado(err, msg) -> None:
            if err is not None:
                erro.append(KafkaException(err))
                return
            entrega.append((msg.partition(), msg.offset()))

        iniciado = time.perf_counter()
        try:
            self._produtor.produce(
                topic=destino,
                key=idempotency_key.encode("utf-8"),
                value=corpo,
                headers=cabecalhos,
                on_delivery=confirmado,
            )
            # flush espera as confirmações pendentes: sem ele, publicar seria
            # apenas enfileirar no cliente e a API mentiria sobre o desfecho.
            restantes = self._produtor.flush(10)
        except BufferError as exc:
            raise MensageriaIndisponivel("fila de envio do produtor cheia") from exc
        except Exception as exc:  # noqa: BLE001
            raise MensageriaIndisponivel(_erro_do_broker(exc)) from exc

        duracao_ms = round((time.perf_counter() - iniciado) * 1000, 3)
        if erro:
            raise MensageriaIndisponivel(_erro_do_broker(erro[0]))
        if restantes or not entrega:
            raise MensageriaIndisponivel(
                f"broker nao confirmou a publicacao em {destino} "
                f"({restantes} pendente(s))"
            )

        particao, offset = entrega[0]
        _log(
            "mensageria.publicado",
            event_type=evento.get("event_type"),
            idempotency_key=idempotency_key,
            correlation_id=evento.get("correlation_id"),
            topico=destino,
            particao=particao,
            offset=offset,
            bytes=len(corpo),
            duracao_ms=duracao_ms,
        )
        return particao, offset


__all__ = [
    "ConsumidorEvento",
    "HEADER_EVENTO",
    "MensageriaIndisponivel",
    "ProdutorEvento",
    "declarar_topologia",
    "esperar_reentrega",
    "ler_tentativa",
    "publicar_retencao",
    "serializar_evento",
]
