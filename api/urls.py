from django.urls import path
from rest_framework.routers import DefaultRouter

from api.auth import (
    TokenObtainPairViewWithThrottle,
    TokenRefreshViewWithThrottle,
)
from api.views import CategoryViewSet, ItemViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("items", ItemViewSet, basename="item")

# Aula 7: fluxos de autenticação JWT (obtenção e renovação de token).
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
]

urlpatterns += router.urls