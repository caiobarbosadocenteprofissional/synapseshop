"""Regras operacionais de invalidacao do cache por evento de dominio (Aula 8).

Traduz os eventos de dominio em apagamentos de chaves no Redis:

| Evento                                 | Chaves invalidadas                          |
| :------------------------------------- | :------------------------------------------ |
| `ItemCriado` / `ItemAtualizado`        | `item:<id>` + todas as `itens:list:*`        |
| `ItemRemovido`                         | `item:<id>` + todas as `itens:list:*`        |
| `CategoriaCriada/Atualizada/Removida`  | todas as `itens:list:*` + todos os detalhes |

A lista e invalidada junto com o item porque o nome da categoria aparece em
cada linha da listagem e o total de itens muda a paginacao. Eventos de categoria
tambem invalidam os detalhes, ja que o `category_name` faz parte do payload do
item. O TTL (60s/300s) funciona como rede de seguranca para eventos perdidos.
"""

from services import cache as cache_service
from services.events import (
    CATEGORIA_ATUALIZADA,
    CATEGORIA_CRIADA,
    CATEGORIA_REMOVIDA,
    ITEM_ATUALIZADO,
    ITEM_CRIADO,
    ITEM_REMOVIDO,
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
