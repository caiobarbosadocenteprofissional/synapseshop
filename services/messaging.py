"""Escolha do transporte de mensageria (Camada 5).

A Aula 9 entregou o par produtor/consumidor sobre RabbitMQ e a Aula 10 o
entregou sobre Apache Kafka. Os dois transportes implementam a mesma surface —
publicar um evento, consumir com pelo menos uma vez, reentregar e matar para a
DLQ — e este módulo é o único ponto que decide qual deles está ativo, a partir
de ``MENSAGERIA_BROKER``.

Por que uma fachada em vez de duplicar a escolha nos chamadores: o contrato do
evento, a regra de deduplicação e o worker são **independentes do broker**. Se o
produtor e o consumidor escolhessem o transporte por conta própria, bastaria um
``MENSAGERIA_BROKER`` divergente entre a API e o ``pedido-worker`` para que um
pedido fosse publicado no Kafka e procurado no RabbitMQ — falha silenciosa, do
tipo que só aparece como mensagem presa numa fila vazia. Uma decisão só elimina
essa classe de erro.

A escolha é **preguiçosa**: ela acontece na chamada, não no import. Escolher no
import congelava o transporte no momento em que o módulo era carregado, e um
teste (ou um ``override_settings``) que trocasse ``MENSAGERIA_BROKER`` depois
continuaria falando com o broker antigo — sem nenhum aviso. Resolvendo na
chamada, a decisão segue a configuração do momento.

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

from typing import Any, Callable, Dict, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from services.messaging_base import (
    ConsumidorEventoProtocol,
    MensageriaIndisponivel,
    ProdutorEventoProtocol,
)

BROKERS = ("kafka", "rabbitmq")


def _broker() -> str:
    """Broker ativo, validado. Erro claro para valor desconhecido."""
    broker = settings.MENSAGERIA_BROKER
    if broker not in BROKERS:
        raise ImproperlyConfigured(
            f"MENSAGERIA_BROKER invalido: {broker!r} "
            f"(use {' ou '.join(repr(b) for b in BROKERS)})"
        )
    return broker


def produtor_evento(
    topologia,
    client_id: str = "synapseshop-api",
) -> ProdutorEventoProtocol:
    """Produtor do broker ativo, resolvido na chamada."""
    if _broker() == "kafka":
        from services.messaging_kafka import ProdutorEvento
    else:
        from services.messaging_rabbit import ProdutorEvento
    return ProdutorEvento(topologia, client_id=client_id)


def consumidor_evento(
    handler: Callable[[Dict[str, Any], int], None],
    topologia,
    client_id: str = "synapseshop-worker",
) -> ConsumidorEventoProtocol:
    """Consumidor do broker ativo, resolvido na chamada."""
    if _broker() == "kafka":
        from services.messaging_kafka import ConsumidorEvento
    else:
        from services.messaging_rabbit import ConsumidorEvento
    return ConsumidorEvento(handler, topologia, client_id=client_id)


__all__ = [
    "BROKERS",
    "ConsumidorEventoProtocol",
    "MensageriaIndisponivel",
    "ProdutorEventoProtocol",
    "consumidor_evento",
    "produtor_evento",
]
