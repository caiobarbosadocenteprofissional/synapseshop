from django.http import JsonResponse
from rest_framework import permissions, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import CategorySerializer, ItemSerializer
from repositories.models import Category, Item, User
from services import cache as cache_service
from services.events import (
    CATEGORIA_ATUALIZADA,
    CATEGORIA_CRIADA,
    CATEGORIA_REMOVIDA,
    ITEM_ATUALIZADO,
    ITEM_CRIADO,
    ITEM_REMOVIDO,
    emitir_apos_commit,
)


def health(request):
    return JsonResponse({"status": "ok"})


class IsAdminRole(permissions.BasePermission):
    """Permite apenas usuários com o papel ``admin`` (Aula 7)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", None) == User.Roles.ADMIN
        )


def resposta_com_cache(dados, resultado):
    """Resposta do DRF com o desfecho da consulta no header ``X-Cache`` (Aula 8).

    Valores: ``HIT`` (servido do Redis), ``MISS`` (preenchimento a partir do
    PostgreSQL) e ``BYPASS`` (cache desligado por ``CACHE_ENABLED``). Torna o
    ciclo miss/preenchimento/hit observavel em tempo real.
    """
    response = Response(dados, status=200)
    response["X-Cache"] = resultado
    return response


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    # Aula 8: escrita de categoria emite evento de dominio que invalida o cache.
    def perform_create(self, serializer):
        categoria = serializer.save()
        emitir_apos_commit(CATEGORIA_CRIADA, categoria_id=categoria.pk)

    def perform_update(self, serializer):
        categoria = serializer.save()
        emitir_apos_commit(CATEGORIA_ATUALIZADA, categoria_id=categoria.pk)

    def perform_destroy(self, instance):
        categoria_id = instance.pk
        instance.delete()
        emitir_apos_commit(CATEGORIA_REMOVIDA, categoria_id=categoria_id)


class ItemViewSet(viewsets.ModelViewSet):
    serializer_class = ItemSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "price", "created_at"]

    def get_queryset(self):
        queryset = Item.objects.select_related("category").all()
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            active = is_active.lower() in ("1", "true", "yes")
            queryset = queryset.filter(is_active=active)
        category = self.request.query_params.get("category")
        if category is not None:
            queryset = queryset.filter(category_id=category)
        return queryset

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    # Aula 8: cache-aside na listagem (TTL CACHE_TTL_LISTA). O envelope paginado
    # completo e cacheado, para que o hit nao volte a consultar o banco.
    def list(self, request, *args, **kwargs):
        def produtor():
            consulta = self.filter_queryset(self.get_queryset())
            pagina = self.paginate_queryset(consulta)
            if pagina is not None:
                return self.get_paginated_response(
                    self.get_serializer(pagina, many=True).data
                ).data
            return self.get_serializer(consulta, many=True).data

        dados, resultado = cache_service.get_lista_itens(request.query_params, produtor)
        return resposta_com_cache(dados, resultado)

    # Aula 8: cache-aside no detalhe (TTL CACHE_TTL_DETALHE).
    def retrieve(self, request, *args, **kwargs):
        def produtor():
            return self.get_serializer(self.get_object()).data

        dados, resultado = cache_service.get_item(kwargs.get("pk"), produtor)
        return resposta_com_cache(dados, resultado)

    # Aula 8: escrita de item emite evento de dominio que invalida o cache.
    def perform_create(self, serializer):
        item = serializer.save()
        emitir_apos_commit(ITEM_CRIADO, item_id=item.pk)

    def perform_update(self, serializer):
        item = serializer.save()
        emitir_apos_commit(ITEM_ATUALIZADO, item_id=item.pk)

    def perform_destroy(self, instance):
        item_id = instance.pk
        instance.delete()
        emitir_apos_commit(ITEM_REMOVIDO, item_id=item_id)


class CacheStatsView(APIView):
    """Métricas de eficácia do cache-aside (Aula 8), restritas ao papel admin.

    ``GET`` devolve hits, misses, total de lookups e hit rate por endpoint.
    ``POST`` zera os contadores, abrindo uma nova janela de medição.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        return Response(cache_service.metricas())

    def post(self, request):
        cache_service.reset_metricas()
        return Response(cache_service.metricas())
