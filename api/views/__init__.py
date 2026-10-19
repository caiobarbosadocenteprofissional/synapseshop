"""Views da API, organizadas por área funcional.

Os nomes públicos continuam disponíveis em ``api.views`` — ``config/urls.py`` e
``api/urls.py`` não precisaram mudar. A divisão só existe para dar um dono claro
a cada conjunto de rotas; a superfície importável é a mesma de antes.
"""

from api.views.assist import AssistStatsView, AssistView
from api.views.catalogo import (
    CacheStatsView,
    CategoryViewSet,
    IsAdminRole,
    ItemViewSet,
    resposta_com_cache,
)
from api.views.health import health, health_pronto
from api.views.pedidos import (
    NotificacaoListView,
    PagamentoView,
    PedidoCreateView,
    PedidoDetailView,
)

__all__ = [
    "AssistStatsView",
    "AssistView",
    "CacheStatsView",
    "CategoryViewSet",
    "IsAdminRole",
    "ItemViewSet",
    "NotificacaoListView",
    "PagamentoView",
    "PedidoCreateView",
    "PedidoDetailView",
    "health",
    "health_pronto",
    "resposta_com_cache",
]
