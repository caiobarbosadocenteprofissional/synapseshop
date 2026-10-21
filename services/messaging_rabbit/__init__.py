"""Camada de mensageria assíncrona sobre RabbitMQ (Aulas 9 a 11).

Entrega o par produtor/consumidor de evento com três responsabilidades:

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

O pacote não conhece o domínio: ele transporta dicionários JSON e devolve as
mensagens consumidas ao handler registrado. O contrato está em
``events/contracts.py`` e a regra de deduplicação em ``services/idempotencia.py``.

**Por que o *backoff* é feito no consumidor:** para esperar entre tentativas sem
perder a ordem nem acumular mensagens, o consumidor segura a entrega
(prefetch=1), republica a mesma mensagem com o contador incrementado e só então
confirma a original. A alternativa usual (filas de delay com TTL) foi
considerada e fica registrada em ``docs/DECISOES_TECNICAS_AULA9.md`` como
evolução natural: ela libera o consumidor durante a espera, ao custo de mais uma
fila por patamar de atraso.

O transporte Kafka vive em ``services/messaging_kafka/``, com a mesma
simetria: este pacote escolhe o RabbitMQ pelo ``MENSAGERIA_BROKER=rabbitmq`` e
a fachada ``services/messaging.py`` expõe o mesmo par produtor/consumidor dos
dois, então nenhum chamador mudou. Na Aula 11 o par deixou de ser do
``PedidoCriado`` e passou a ser de **qualquer evento**: a exchange é única e cada
evento tem o seu *routing key*, a sua fila e a sua DLQ, declarados a partir de
``events/topology.py``.
"""

from services.messaging_base import MensageriaIndisponivel
from services.messaging_rabbit.consumidor import ConsumidorEvento
from services.messaging_rabbit.publicacao import ProdutorEvento
from services.messaging_rabbit.topologia import (
    conexao,
    declarar_topologia,
    fechar_recursos,
)

__all__ = [
    "ConsumidorEvento",
    "MensageriaIndisponivel",
    "ProdutorEvento",
    "conexao",
    "declarar_topologia",
    "fechar_recursos",
]
