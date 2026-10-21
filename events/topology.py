"""Topologia de transporte por evento (Aula 11).

Até a Aula 10 a topologia era do evento: um tópico, uma fila, uma DLQ e um
*consumer group* para ``PedidoCriado``. O fluxo da Aula 11 tem três eventos, e
cada um precisa do seu — mas a **decisão** de como cada evento é nomeado e roteado
é uma só, e é aqui que ela fica.

Este módulo é **neutro**: não importa Django nem lê ``settings``. Ele conhece a
*forma* do transporte de um evento (que nomes ele precisa) e a ordem do fluxo;
os *nomes* de cada implantação são injetados. A direção da dependência é
``config`` → ``events``: quem lê o ``settings`` monta os nomes e entrega o
:class:`NomesEvento`, e o domínio responde com o :class:`TopologiaEvento`.

A separação não é preciosismo: é o que permite importar o catálogo de eventos
sem configurar o Django — no microsserviço de inventário, nos scripts de
smoke test e nos testes unitários.

Uma decisão de nomenclatura merece registro: **a exchange AMQP é única**
(``RABBITMQ_EXCHANGE`` = ``pedidos.events``) e os três eventos usam *routing
keys* diferentes. Trocar de exchange exigiria recriar as três filas e as três
ligações; manter uma exchange com chave por evento é a forma comum e deixa o
roteamento explícito. O nome ``pedidos.events`` continua verdadeiro: pagamento e
notificação são eventos **do pedido**, não de outro agregado.
"""

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from events.contracts import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
)

EVENTOS: Tuple[str, ...] = (
    EVENTO_PEDIDO_CRIADO,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_NOTIFICACAO_ENVIADA,
)
"""Os eventos do fluxo, na ordem em que acontecem."""


@dataclass(frozen=True)
class NomesEvento:
    """Os nomes de transporte de um evento nesta implantação.

    É o que muda entre ambientes; o formato da topologia, não.
    """

    topico: str
    dlq: str
    grupo: str
    exchange: str
    dlx: str
    routing_key: str
    fila: str
    fila_dlq: str


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


def construir_topologia(evento: str, nomes: NomesEvento) -> TopologiaEvento:
    """Topologia de um evento a partir dos nomes desta implantação."""
    if evento not in EVENTOS:
        raise ValueError(
            f"evento sem topologia declarada: {evento!r} "
            f"(declarados: {', '.join(EVENTOS)})"
        )
    return TopologiaEvento(
        evento=evento,
        topico=nomes.topico,
        dlq=nomes.dlq,
        grupo=nomes.grupo,
        exchange=nomes.exchange,
        dlx=nomes.dlx,
        routing_key=nomes.routing_key,
        fila=nomes.fila,
        fila_dlq=nomes.fila_dlq,
    )


def construir_topologias(
    nomes_por_evento: Mapping[str, NomesEvento]
) -> Tuple[TopologiaEvento, ...]:
    """Todas as topologias, na ordem do fluxo. Usada por ``declarar_topologia``."""
    faltando = [evento for evento in EVENTOS if evento not in nomes_por_evento]
    if faltando:
        raise ValueError(
            f"eventos sem nomes de transporte: {', '.join(faltando)}"
        )
    return tuple(
        construir_topologia(evento, nomes_por_evento[evento]) for evento in EVENTOS
    )


def chave_de(id_do_registro: int, prefixo: str) -> str:
    """Chave de idempotência dos eventos da Aula 11.

    ``pagamento:15``, ``notificacao:42``. O prefixo é o agregado, e não a chave
    do pedido: a deduplicação é única por ``(evento, idempotency_key)``, então
    um pedido e o seu pagamento são entradas distintas — sem prefixo, as duas
    registrarão a mesma chave em eventos diferentes e a segunda gravação seria
    lida como duplicata.
    """
    return f"{prefixo}:{id_do_registro}"
