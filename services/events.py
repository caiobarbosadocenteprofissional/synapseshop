"""Eventos de dominio em processo (Aulas 8 e 11).

A spec exige que a invalidacao do cache esteja associada a **eventos do
negocio** (por exemplo, "PedidoAtualizado" invalida a chave do pedido). Nas
Aulas 8 e 9 o dominio instrumentado e o catalogo, entao os eventos sao os do
`Item` e da `Category`; a Aula 11 acrescenta os do pedido.

O dispatcher e deliberadamente **sincrono e in-process**: e apenas um registro
de handlers por nome de evento. Nao ha broker, topico, consumidor ou fila --
a mensageria (RabbitMQ/Kafka) pertence ao bloco das Aulas 9-11 e, pela diretriz
SpecDD, nao e antecipada aqui. O gancho de emissao e sempre
``transaction.on_commit``, para que a invalidacao ocorra somente depois da
confirmacao da transacao no PostgreSQL.

**O limite deste mecanismo aparece exatamente na Aula 11**: o pedido muda de
estado em tres processos (api grava o pagamento, `pedido-worker` avanca para
`PROCESSANDO`, `notificacao-worker` registra a notificacao). O evento continua
sendo in-process, mas a chave que ele invalida vive no **Redis compartilhado**,
e nao em memoria do processo: quem escreve apaga a chave e todos os processos da
API passam a ver o dado novo. O dispatcher in-process e o gatilho, e o cache
compartilhado e o que torna a invalidacao valida entre processos. Um barramento
que atravessasse processos resolveria o outro lado do problema (quem nao gravou
precisa saber que mudou) — essa e a evolucao natural, registrada em
`docs/DECISOES_TECNICAS_AULA11.md`.
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

PAGAMENTO_APROVADO = "PagamentoAprovado"
PAGAMENTO_RECUSADO = "PagamentoRecusado"
PEDIDO_EM_PROCESSAMENTO = "PedidoEmProcessamento"
NOTIFICACAO_REGISTRADA = "NotificacaoRegistrada"

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
