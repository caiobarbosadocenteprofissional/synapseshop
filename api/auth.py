"""Fluxos de autenticação JWT da Aula 7.

Serializers e views do `djangorestframework-simplejwt` com a claim ``role``
(admin/user) incluída no token e resposta, além de throttling escopado em
``login`` nas rotas de obtenção/renovação de token.
"""

from django.contrib.auth import get_user_model
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = getattr(user, "role", User.Roles.USER)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["role"] = self.user.role
        return data


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = RefreshToken(attrs["refresh"])
        user = User.objects.get(id=refresh["user_id"])
        data["role"] = user.role
        return data


class TokenObtainPairViewWithThrottle(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class TokenRefreshViewWithThrottle(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"