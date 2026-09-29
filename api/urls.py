from django.urls import path
from rest_framework.routers import DefaultRouter

from api.auth import (
    TokenObtainPairViewWithThrottle,
    TokenRefreshViewWithThrottle,
)
from api.views import CacheStatsView, CategoryViewSet, ItemViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("items", ItemViewSet, basename="item")

# Aula 7: fluxos de autenticação JWT (obtenção e renovação de token).
# Aula 8: métricas de eficácia do cache-aside (somente papel admin).
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
]

urlpatterns += router.urls