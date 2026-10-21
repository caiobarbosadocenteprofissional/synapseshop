"""Topologias resolvidas para esta implantação (Settings → eventos).

Este é o adaptador do lado da aplicação: lê o ``settings`` do Django, monta os
:class:`NomesEvento` de cada evento e entrega ao domínio neutro
(``events/topology.py``), que devolve a :class:`TopologiaEvento`.

A divisão é deliberada. ``events/`` sabe *que formato* um transporte tem —
tópico, DLQ, grupo, exchange, chave de roteamento, fila — mas não *como esta
implantação os chama*: isso muda entre o Compose de desenvolvimento e o de
produção, e é por isso que fica no ``settings``. O ganho é que o catálogo de
eventos deixa de depender do Django e passa a poder ser importado pelo
microsserviço de inventário, pelos scripts de smoke test e pelos testes
unitários sem configurar nada.
"""

from functools import lru_cache
from typing import Dict, Tuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from events.contracts import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
)
from events.topology import (
    NomesEvento,
    TopologiaEvento,
    construir_topologia,
    construir_topologias,
)


def nomes_por_evento() -> Dict[str, NomesEvento]:
    """Os nomes de transporte de cada evento, lidos do ``settings``."""
    return {
        EVENTO_PEDIDO_CRIADO: NomesEvento(
            topico=settings.KAFKA_TOPICO_PEDIDO_CRIADO,
            dlq=settings.KAFKA_TOPICO_PEDIDO_CRIADO_DLQ,
            grupo=settings.KAFKA_GRUPO_CONSUMIDORES,
            exchange=settings.RABBITMQ_EXCHANGE,
            dlx=settings.RABBITMQ_DLX,
            routing_key=settings.RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO,
            fila=settings.RABBITMQ_FILA_PEDIDO_CRIADO,
            fila_dlq=settings.RABBITMQ_FILA_PEDIDO_CRIADO_DLQ,
        ),
        EVENTO_PAGAMENTO_PROCESSADO: NomesEvento(
            topico=settings.KAFKA_TOPICO_PAGAMENTO_PROCESSADO,
            dlq=settings.KAFKA_TOPICO_PAGAMENTO_PROCESSADO_DLQ,
            # Grupo próprio: escalar o consumo da notificação não pode competir com o
            # do pedido, e os offsets dos dois fluxos são independentes.
            grupo=settings.KAFKA_GRUPO_NOTIFICACAO,
            exchange=settings.RABBITMQ_EXCHANGE,
            dlx=settings.RABBITMQ_DLX,
            routing_key=settings.RABBITMQ_ROUTING_KEY_PAGAMENTO_PROCESSADO,
            fila=settings.RABBITMQ_FILA_PAGAMENTO_PROCESSADO,
            fila_dlq=settings.RABBITMQ_FILA_PAGAMENTO_PROCESSADO_DLQ,
        ),
        EVENTO_NOTIFICACAO_ENVIADA: NomesEvento(
            topico=settings.KAFKA_TOPICO_NOTIFICACAO_ENVIADA,
            dlq=settings.KAFKA_TOPICO_NOTIFICACAO_ENVIADA_DLQ,
            grupo=settings.KAFKA_GRUPO_NOTIFICACAO,
            exchange=settings.RABBITMQ_EXCHANGE,
            dlx=settings.RABBITMQ_DLX,
            routing_key=settings.RABBITMQ_ROUTING_KEY_NOTIFICACAO_ENVIADA,
            fila=settings.RABBITMQ_FILA_NOTIFICACAO_ENVIADA,
            fila_dlq=settings.RABBITMQ_FILA_NOTIFICACAO_ENVIADA_DLQ,
        ),
    }


@lru_cache(maxsize=None)
def _topologia_por_nomes(evento: str, nomes: NomesEvento) -> TopologiaEvento:
    """Memoizado por *valor*: mudar o ``settings`` muda a chave do cache."""
    return construir_topologia(evento, nomes)


def topologia_de(evento: str) -> TopologiaEvento:
    """Topologia de um evento nesta implantação. Erro claro para evento sem nome."""
    nomes = nomes_por_evento().get(evento)
    if nomes is None:
        raise ImproperlyConfigured(
            f"evento sem topologia declarada: {evento!r} "
            f"(declarados: {', '.join(sorted(nomes_por_evento()))})"
        )
    return _topologia_por_nomes(evento, nomes)


def topologias() -> Tuple[TopologiaEvento, ...]:
    """Todas as topologias, na ordem do fluxo. Usada por ``declarar_topologia``."""
    return construir_topologias(nomes_por_evento())
