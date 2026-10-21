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
   diferentes são consumidos em paralelo. A confirmação é feita com
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

O pacote tem a mesma forma do ``services/messaging_rabbit/``: ``publicacao.py``
com o produtor, ``consumidor.py`` com o consumidor, ``topicos.py`` com a
topologia e ``observabilidade.py`` com as métricas. A política de reentrega é
compartilhada pelos dois transportes e mora em ``services/messaging_base.py``.
"""

from services.messaging_base import (
    MensageriaIndisponivel,
    ResultadoPublicacao,
    esperar_reentrega,
    ler_tentativa,
    serializar_evento,
)
from services.messaging_kafka.consumidor import ConsumidorEvento
from services.messaging_kafka.observabilidade import registrar_ociosidade, tempo_de_fila
from services.messaging_kafka.publicacao import HEADER_EVENTO, ProdutorEvento, publicar_retencao
from services.messaging_kafka.topicos import _erro_do_broker, declarar_topologia

__all__ = [
    "HEADER_EVENTO",
    "ConsumidorEvento",
    "MensageriaIndisponivel",
    "ProdutorEvento",
    "ResultadoPublicacao",
    "_erro_do_broker",
    "declarar_topologia",
    "esperar_reentrega",
    "ler_tentativa",
    "publicar_retencao",
    "registrar_ociosidade",
    "serializar_evento",
    "tempo_de_fila",
]
