"""Topologia de transporte por evento (Aula 11).

Até a Aula 10 a topologia era do evento: um tópico, uma fila, uma DLQ e um
*consumer group* para ``PedidoCriado``. O fluxo da Aula 11 tem três eventos, e
cada um precisa do seu — mas a **decisão** de como cada evento é nomeado e roteado
é uma só, e é aqui que ela fica.

A tabela é lida de ``config/settings.py`` (nomes vêm de variáveis de ambiente,
como já acontecia com o evento de pedido) e devolvida por :func:`topologia_de`.
Os transportes (``services/messaging_kafka.py`` e ``services/messaging_rabbit.py``)
consomem esta estrutura e não conhecem nomes: é por isso que o produtor e o
consumidor da notificação não puderam divergir deDefaults diferentes — o mesmo
argumento que motivou a fachada de broker, aplicado agora ao evento.

Uma decisão de nomenclatura merece registro: **a exchange AMQP é única**
(``RABBITMQ_EXCHANGE`` = ``pedidos.events``) e os três eventos usam *routing
keys* diferentes. Trocar de exchange exigiria recriar as três filas e as três
ligações; manter uma exchange com chave por evento é a forma comum e deixa o
roteamento explícito. O nome ``pedidos.events`` continua verdadeiro: pagamento e
notificação são eventos **do pedido**, não de outro agregado.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from events.contracts import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
)


@dataclass(frozen=True)
class TopologiaEvento:
    """Onde um evento é publicado e de onde é consumido, nos dois transportes.

    ``topico``/``dlq`` são usados pelo Kafka; ``exchange``/``routing_key``/
    ``fila``/``fila_dlq`` pelo RabbitMQ. Os dois conjuntos coexistem porque a
    mesma aplicação fala com os dois brokers — que é o motivo de a fachada
    existir.
    """

    evento: str
    topico: str
    dlq: str
    grupo: str
    exchange: str
    dlx: str
    routing_key: str
    fila: str
    fila_dlq: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "evento": self.evento,
            "topico": self.topico,
            "dlq": self.dlq,
            "grupo": self.grupo,
            "exchange": self.exchange,
            "routing_key": self.routing_key,
            "fila": self.fila,
            "fila_dlq": self.fila_dlq,
        }


def _pedido_criado() -> TopologiaEvento:
    return TopologiaEvento(
        evento=EVENTO_PEDIDO_CRIADO,
        topico=settings.KAFKA_TOPICO_PEDIDO_CRIADO,
        dlq=settings.KAFKA_TOPICO_PEDIDO_CRIADO_DLQ,
        grupo=settings.KAFKA_GRUPO_CONSUMIDORES,
        exchange=settings.RABBITMQ_EXCHANGE,
        dlx=settings.RABBITMQ_DLX,
        routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
        fila=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
        fila_dlq=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
    )


def _pagamento_processado() -> TopologiaEvento:
    return TopologiaEvento(
        evento=EVENTO_PAGAMENTO_PROCESSADO,
        topico=settings.KAFKA_TOPICO_PAGAMENTO_PROCESSADO,
        dlq=settings.KAFKA_TOPICO_PAGAMENTO_PROCESSADO_DLQ,
        # Grupo próprio: escalar o consumo da notificação não pode competes com o
        # do pedido, e os offsets dos dois fluxos são independentes.
        grupo=settings.KAFKA_GRUPO_NOTIFICACAO,
        exchange=settings.RABBITMQ_EXCHANGE,
        dlx=settings.RABBITMQ_DLX,
        routing_key=settings.RABBITMQ_ROUTING_KEY_PAGAMENTO_PROCESSADO,
        fila=settings.RABBITMQ_FILA_PAGAMENTO_PROCESSADO,
        fila_dlq=settings.RABBITMQ_FILA_PAGAMENTO_PROCESSADO_DLQ,
    )


def _notificacao_enviada() -> TopologiaEvento:
    return TopologiaEvento(
        evento=EVENTO_NOTIFICACAO_ENVIADA,
        topico=settings.KAFKA_TOPICO_NOTIFICACAO_ENVIADA,
        dlq=settings.KAFKA_TOPICO_NOTIFICACAO_ENVIADA_DLQ,
        grupo=settings.KAFKA_GRUPO_NOTIFICACAO,
        exchange=settings.RABBITMQ_EXCHANGE,
        dlx=settings.RABBITMQ_DLX,
        routing_key=settings.RABBITMQ_ROUTING_KEY_NOTIFICACAO_ENVIADA,
        fila=settings.RABBITMQ_FILA_NOTIFICACAO_ENVIADA,
        fila_dlq=settings.RABBITMQ_FILA_NOTIFICACAO_ENVIADA_DLQ,
    )


_CONSTRUTORES = {
    EVENTO_PEDIDO_CRIADO: _pedido_criado,
    EVENTO_PAGAMENTO_PROCESSADO: _pagamento_processado,
    EVENTO_NOTIFICACAO_ENVIADA: _notificacao_enviada,
}


@lru_cache(maxsize=None)
def topologia_de(evento: str) -> TopologiaEvento:
    """Topologia de um evento. Erro claro para evento sem topologia declarada."""
    construtor = _CONSTRUTORES.get(evento)
    if construtor is None:
        raise ImproperlyConfigured(
            f"evento sem topologia declarada: {evento!r} "
            f"(declarados: {', '.join(sorted(_CONSTRUTORES))})"
        )
    return construtor()


def topologias() -> Tuple[TopologiaEvento, ...]:
    """Todas as topologias, na ordem do fluxo. Usada por ``declarar_topologia``."""
    return tuple(topologia_de(evento) for evento in _CONSTRUTORES)


def chave_de(id_do_registro: int, prefixo: str) -> str:
    """Chave de idempotência dos eventos da Aula 11.

    ``pagamento:15``, ``notificacao:42``. O prefixo é o agregado, e não a chave
    do pedido: a deduplicação é única por ``(evento, idempotency_key)``, então
    um pedido e o seu pagamento são entradas distintas — sem prefixo, as duas
    registrarão a mesma chave em eventos diferentes e a segunda gravação seria
    lida como duplicata.
    """
    return f"{prefixo}:{id_do_registro}"