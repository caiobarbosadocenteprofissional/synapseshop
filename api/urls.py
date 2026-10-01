from django.urls import path
from rest_framework.routers import DefaultRouter

from api.auth import (
    TokenObtainPairViewWithThrottle,
    TokenRefreshViewWithThrottle,
)
from api.views import (
    CacheStatsView,
    CategoryViewSet,
    ItemViewSet,
    PedidoCreateView,
    PedidoDetailView,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("items", ItemViewSet, basename="item")

# Aula 7: fluxos de autenticação JWT (obtenção e renovação de token).
# Aula 8: métricas de eficácia do cache-aside (somente papel admin).
# Aula 9: produtor de `PedidoCriado` — criação de pedido que publica o evento.
urlpatterns = [
    path(
        "auth/token/",
        TokenObtainPairViewWithThrottle.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "auth/token/refresh/",
        TokenRefreshViewWithThrottle.as_view(),
        name="token_refresh",
    ),
    path("cache/stats/", CacheStatsView.as_view(), name="cache_stats"),
    path("pedidos/", PedidoCreateView.as_view(), name="pedido_create"),
    path("pedidos/<int:pk>/", PedidoDetailView.as_view(), name="pedido_detail"),
]

urlpatterns += router.urls