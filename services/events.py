"""Eventos de dominio em processo (Aula 8).

A spec exige que a invalidacao do cache esteja associada a **eventos do
negocio** (por exemplo, "PedidoAtualizado" invalida a chave do pedido). Aqui o
dominio instrumentado e o catalogo, entao os eventos sao os do `Item` e da
`Category`.

O dispatcher e deliberadamente **sincrono e in-process**: e apenas um registro
de handlers por nome de evento. Nao ha broker, topico, consumidor ou fila --
a mensageria (RabbitMQ/Kafka) pertence ao bloco das Aulas 9-11 e, pela diretriz
SpecDD, nao e antecipada aqui. O gancho de emissao e sempre
``transaction.on_commit``, para que a invalidacao ocorra somente depois da
confirmacao da transacao no PostgreSQL.
"""

import json
import logging
from collections import defaultdict

from django.db import transaction

logger = logging.getLogger("synapseshop.eventos")

ITEM_CRIADO = "ItemCriado"
ITEM_ATUALIZADO = "ItemAtualizado"
ITEM_REMOVIDO = "ItemRemovido"

CATEGORIA_CRIADA = "CategoriaCriada"
CATEGORIA_ATUALIZADA = "CategoriaAtualizada"
CATEGORIA_REMOVIDA = "CategoriaRemovida"

_handlers = defaultdict(list)


def on(evento: str):
    """Decorator que registra um handler para o evento de dominio."""

    def registrar(funcao):
        _handlers[evento].append(funcao)
        return funcao

    return registrar


def emitir(evento: str, **payload) -> None:
    """Publica um evento de dominio: chama os handlers registrados."""
    logger.info(
        json.dumps(
            {"evento": "dominio.emitido", "nome": evento, "payload": payload},
            ensure_ascii=False,
        )
    )
    for handler in _handlers.get(evento, []):
        try:
            handler(**payload)
        except Exception:  # noqa: BLE001 - evento nunca derruba a requisição
            logger.warning(
                "handler_falhou evento=%s handler=%s",
                evento,
                getattr(handler, "__name__", handler),
                exc_info=True,
            )


def emitir_apos_commit(evento: str, **payload) -> None:
    """Emite o evento somente após o commit da transação corrente."""
    transaction.on_commit(lambda: emitir(evento, **payload))
