"""Regras operacionais de invalidacao do cache por evento de dominio (Aulas 8 e 11).

Traduz os eventos de dominio em apagamentos de chaves no Redis:

| Evento                                 | Chaves invalidadas                          |
| :------------------------------------- | :------------------------------------------ |
| `ItemCriado` / `ItemAtualizado`        | `item:<id>` + todas as `itens:list:*`        |
| `ItemRemovido`                         | `item:<id>` + todas as `itens:list:*`        |
| `CategoriaCriada/Atualizada/Removida`  | todas as `itens:list:*` + todos os detalhes |
| `PedidoEmProcessamento`                | `pedido:<id>`                                |
| `PagamentoAprovado` / `PagamentoRecusado` | `pedido:<id>`                            |
| `NotificacaoRegistrada`                | `pedido:<id>`                                |

A lista e invalidada junto com o item porque o nome da categoria aparece em
cada linha da listagem e o total de itens muda a paginacao. Eventos de categoria
tambem invalidam os detalhes, ja que o `category_name` faz parte do payload do
item. O TTL (60s/300s) funciona como rede de seguranca para eventos perdidos.

O pedido tem TTL curto (`CACHE_TTL_PEDIDO`) porque muda de estado o tempo todo,
e cada processo que muda emite o evento **depois do commit** — api, `pedido-worker`
e `notificacao-worker`. O evento e in-process (ver `services/events.py`), e ainda
assim a invalidacao vale para todos: a chave esta no Redis compartilhado, entao
apagar nela surte efeito em qualquer processo da API. E por isso que emissor e
invalidador sao o mesmo passo, e nao ha um segundo caminho de invalidacao para
manter em dia.
"""

from services import cache as cache_service
from services.events import (
    CATEGORIA_ATUALIZADA,
    CATEGORIA_CRIADA,
    CATEGORIA_REMOVIDA,
    ITEM_ATUALIZADO,
    ITEM_CRIADO,
    ITEM_REMOVIDO,
    NOTIFICACAO_REGISTRADA,
    PAGAMENTO_APROVADO,
    PAGAMENTO_RECUSADO,
    PEDIDO_EM_PROCESSAMENTO,
    on,
)


@on(ITEM_CRIADO)
@on(ITEM_ATUALIZADO)
@on(ITEM_REMOVIDO)
def _invalida_item(item_id: int) -> None:
    cache_service.invalidar_item(item_id)
    cache_service.invalidar_lista_itens()


@on(CATEGORIA_CRIADA)
@on(CATEGORIA_ATUALIZADA)
@on(CATEGORIA_REMOVIDA)
def _invalida_categoria(categoria_id: int) -> None:
    cache_service.invalidar_lista_itens()
    cache_service.invalidar_detalhes_itens()


@on(PEDIDO_EM_PROCESSAMENTO)
@on(PAGAMENTO_APROVADO)
@on(PAGAMENTO_RECUSADO)
@on(NOTIFICACAO_REGISTRADA)
def _invalida_pedido(pedido_id: int) -> None:
    """Apaga a chave do pedido: o estado dele acabou de mudar."""
    cache_service.invalidar_pedido(pedido_id)
