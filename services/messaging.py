"""Escolha do transporte de mensageria (Camada 5).

A Aula 9 entregou o par produtor/consumidor sobre RabbitMQ e a Aula 10 o
entregou sobre Apache Kafka. Os dois transportes implementam a mesma surface —
``ProdutorEvento``, ``ConsumidorEvento`` e ``MensageriaIndisponivel`` — e este
módulo é o único ponto que decide qual deles está ativo, a partir de
``MENSAGERIA_BROKER``.

Por que uma fachada em vez de duplicar a escolha nos chamadores: o contrato do
evento, a regra de deduplicação e o worker são **independentes do broker**. Se o
produtor e o consumidor escolhessem o transporte por conta própria, bastaria um
``MENSAGERIA_BROKER`` divergente entre a API e o ``pedido-worker`` para que um
pedido fosse publicado no Kafka e procurado no RabbitMQ — falha silenciosa, do
tipo que só aparece como mensagem presa numa fila vazia. Uma decisão só, tomada
no import, elimina essa classe de erro.

A Aula 11 aplica a mesma ideia ao **evento**: o par produtor/consumidor deixou de
ser ``...PedidoCriado`` e passou a receber a topologia do evento
(``events/topology.py``), então publicar um pagamento ou notificar uma
notificação é o mesmo código com outra topologia. ``pedido-worker`` e
``notificacao-worker`` são a mesma classe com handlers diferentes.

A topologia não é exportada de propósito: ``declarar_topologia`` tem assinatura
diferente em cada transporte (o AMQP recebe o canal, o Kafka usa o
``AdminClient``), e quem a chama é o próprio produtor/consumidor do transporte
escolhido.

O contrato em ``events/contracts.py`` e a regra de deduplicação em
``services/idempotencia.py`` também são agnósticos: a troca de broker não muda o
formato da mensagem nem a chave de idempotência.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if settings.MENSAGERIA_BROKER == "kafka":
    from services.messaging_kafka import (
        ConsumidorEvento,
        MensageriaIndisponivel,
        ProdutorEvento,
    )
elif settings.MENSAGERIA_BROKER == "rabbitmq":
    from services.messaging_rabbit import (
        ConsumidorEvento,
        MensageriaIndisponivel,
        ProdutorEvento,
    )
else:
    raise ImproperlyConfigured(
        f"MENSAGERIA_BROKER invalido: {settings.MENSAGERIA_BROKER!r} "
        "(use 'kafka' ou 'rabbitmq')"
    )

__all__ = [
    "ConsumidorEvento",
    "MensageriaIndisponivel",
    "ProdutorEvento",
]