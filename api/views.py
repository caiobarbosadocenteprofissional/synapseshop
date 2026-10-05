import json
import logging
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from rest_framework import permissions, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import (
    CategorySerializer,
    ItemSerializer,
    NotificacaoSerializer,
    PagamentoCreateSerializer,
    PagamentoSerializer,
    PedidoCreateSerializer,
    PedidoSerializer,
)
from events.contracts import EventoPedidoCriado, ItemPedidoCriado
from events.topology import topologia_de
from repositories.models import Category, Item, Notificacao, Pedido, PedidoItem, User
from services import cache as cache_service
from services import health as health_service
from services import pagamento as pagamento_service
from services.events import (
    CATEGORIA_ATUALIZADA,
    CATEGORIA_CRIADA,
    CATEGORIA_REMOVIDA,
    ITEM_ATUALIZADO,
    ITEM_CRIADO,
    ITEM_REMOVIDO,
    emitir_apos_commit,
)
from services.publicacao import publicar_evento

logger_pedidos = logging.getLogger("synapseshop.pedidos")


def health(request):
    """Liveness: responde enquanto o processo conseguir atender a requisição.

    É deliberadamente superficial — o Compose reinicia a API quando esta rota
    falha, então ela não pode depender de nada externo. Quem verifica as
    dependências de verdade é ``GET /health/pronto``.
    """
    return JsonResponse({"status": "ok"})


def health_pronto(request):
    """Readiness: PostgreSQL, Redis e broker respondendo? 200 ou 503.

    Distinguir as duas rotas evita o pior modo de falha do Compose: com a
    readiness atrelada ao liveness, o Redis cair faria o contêiner da API ser
    reiniciado em laço — a API não tem culpa e o reinício não conserta o Redis.
    """
    relatorio = health_service.verificar()
    status = 200 if relatorio["pronto"] else 503
    return JsonResponse(relatorio, status=status)


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


def _log_pedido(nome_evento: str, **campos) -> None:
    """Log estruturado do produtor, no mesmo formato dos logs da Aula 8."""
    logger_pedidos.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


class PedidoCreateView(APIView):
    """Produtor do evento ``PedidoCriado`` (Aula 9).

    Grava o pedido e publica o evento **depois do commit** — publicar antes
    deixaria o consumidor CHDando uma mensagem de um pedido que pode ainda ter
    sido revertido por uma falha na transação.

    Idempotência no produtor: repetir a mesma ``idempotency_key`` devolve o
    pedido já existente com **200**, sem novo pedido e sem novo evento.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PedidoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        idempotency_key = dados["idempotency_key"] or f"pedido-{uuid4().hex}"
        existente = Pedido.objects.filter(idempotency_key=idempotency_key).first()
        if existente is not None:
            _log_pedido(
                "pedido.duplicado",
                idempotency_key=idempotency_key,
                pedido_id=existente.pk,
                usuario_id=existente.usuario_id,
            )
            return Response(PedidoSerializer(existente).data, status=200)

        # Preço e total são calculados no servidor a partir do catálogo ativo:
        # o cliente informa apenas o item e a quantidade.
        itens_catalogo = {
            item.pk: item
            for item in Item.objects.filter(
                pk__in=[linha["item_id"] for linha in dados["itens"]]
            )
        }
        total = Decimal("0.00")
        for linha in dados["itens"]:
            total += itens_catalogo[linha["item_id"]].price * linha["quantidade"]

        try:
            with transaction.atomic():
                pedido = Pedido.objects.create(
                    usuario=request.user,
                    status=Pedido.Status.PENDENTE,
                    total=total,
                    idempotency_key=idempotency_key,
                    # Identificador que atravessa pagamento e notificação: sem ele,
                    # cada evento da cadeia teria um id próprio e os logs não
                    # permitiriam ler o fluxo inteiro de um pedido.
                    correlation_id=str(uuid4()),
                )
                PedidoItem.objects.bulk_create(
                    [
                        PedidoItem(
                            pedido=pedido,
                            item=itens_catalogo[linha["item_id"]],
                            quantidade=linha["quantidade"],
                            preco_unitario=itens_catalogo[linha["item_id"]].price,
                        )
                        for linha in dados["itens"]
                    ]
                )
        except IntegrityError:
            # Duas requisições com a mesma chave chegaram ao mesmo tempo: a
            # constraint única do banco decide, e a perdedora devolve o pedido.
            existente = Pedido.objects.filter(idempotency_key=idempotency_key).first()
            if existente is None:
                return Response(
                    {"detail": "Conflito ao registrar o pedido."}, status=409
                )
            return Response(PedidoSerializer(existente).data, status=200)

        itens_pedido = list(pedido.itens.all())
        _log_pedido(
            "pedido.criado",
            pedido_id=pedido.pk,
            usuario_id=pedido.usuario_id,
            idempotency_key=idempotency_key,
            total=str(pedido.total),
            itens=len(itens_pedido),
            correlation_id=pedido.correlation_id,
        )

        evento = EventoPedidoCriado(
            idempotency_key=idempotency_key,
            pedido_id=pedido.pk,
            usuario_id=pedido.usuario_id,
            total=pedido.total,
            status=pedido.status,
            itens=[
                ItemPedidoCriado(
                    item_id=linha.item_id,
                    quantidade=linha.quantidade,
                    preco_unitario=linha.preco_unitario,
                )
                for linha in itens_pedido
            ],
            correlation_id=pedido.correlation_id,
        )
        publicado = publicar_evento(
            evento=evento.to_dict(),
            idempotency_key=idempotency_key,
            topologia=topologia_de(evento.event_type),
            prefixo_log="pedido",
            extra={"pedido_id": pedido.pk, "usuario_id": pedido.usuario_id},
        )

        corpo = PedidoSerializer(pedido).data
        if not publicado:
            # O pedido está no banco mas o broker não aceitou o evento. 202
            # informa que o processamento ainda vai acontecer (a fila pode
            # ser reprocessada pela chave de idempotência) sem prometer estado.
            return Response({**corpo, "evento_publicado": False}, status=202)
        return Response({**corpo, "evento_publicado": True}, status=201)


class PagamentoView(APIView):
    """Produtor do evento ``PagamentoProcessado`` (Aula 11).

    A simulação acontece aqui: o corpo traz o desfecho desejado
    (``{"resultado": "APROVADO"}``) e o servidor o persiste como resposta de um
    adquirente. O pagamento move o pedido para ``PAGO`` ou ``CANCELADO`` e publica
    o evento que dispara a notificação.

    Repetir a chamada devolve **200** com o pagamento existente e **não publica
    evento novo** — a unicidade é do banco (``OneToOne``), não de uma condição
    aqui. Por isso não existe chave de idempotência no corpo: ela seria uma
    segunda forma de dizer a mesma coisa.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = PagamentoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        pedido = Pedido.objects.select_related("usuario").filter(pk=pk).first()
        if pedido is None or not _pedido_visivel(request, pedido):
            return Response({"detail": "Pedido não encontrado."}, status=404)

        pagamento, criado = pagamento_service.registrar_pagamento(
            pedido,
            resultado=dados["resultado"],
            forma_pagamento=dados["forma_pagamento"],
        )
        if not criado:
            _log_pedido(
                "pagamento.duplicado.resposta",
                pedido_id=pedido.pk,
                pagamento_id=pagamento.pk,
                status=pagamento.status,
            )
            return Response(
                {
                    **PagamentoSerializer(pagamento).data,
                    "evento_publicado": False,
                },
                status=200,
            )

        publicado = pagamento_service.publicar_pagamento_processado(pagamento)
        return Response(
            {**PagamentoSerializer(pagamento).data, "evento_publicado": publicado},
            status=201,
        )


def _pedido_visivel(request, pedido) -> bool:
    """O pedido pertence a quem o criou; o papel ``admin`` enxerga qualquer um."""
    if getattr(request.user, "role", None) == User.Roles.ADMIN:
        return True
    return pedido.usuario_id == request.user.id


class PedidoDetailView(APIView):
    """Consulta o estado de um pedido — a forma de observar o efeito do consumidor.

    O pedido pertence a quem o criou; o papel ``admin`` enxerga qualquer um.
    Existe para tornar observável a transição ``PENDENTE`` -> ``PROCESSANDO``
    feita pelo worker, sem duplicar o ViewSet de escrita.

    Aula 11: a resposta é cacheada em ``pedido:<id>`` (TTL ``CACHE_TTL_PEDIDO``) e o
    header ``X-Cache`` diz se veio do Redis ou do PostgreSQL. A chave é por pedido
    e não por usuário — o ``usuario`` está no próprio payload, então a posse é
    conferida sobre o dado, inclusive quando ele vem do cache, e um HIT não
    precisa tocar o banco para decidir se pode responder.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        eh_admin = getattr(request.user, "role", None) == User.Roles.ADMIN

        def produtor():
            pedido = Pedido.objects.filter(pk=pk).first()
            if pedido is None:
                return None
            return PedidoSerializer(pedido).data

        dados, resultado = cache_service.get_pedido(pk, produtor)
        if dados is None or (not eh_admin and dados["usuario"] != request.user.id):
            return Response({"detail": "Pedido não encontrado."}, status=404)
        return resposta_com_cache(dados, resultado)


class NotificacaoListView(ListAPIView):
    """Notificações do usuário autenticado (Aula 11), mais recentes primeiro.

    É a forma de observar o efeito do ``notificacao-worker`` por fora: a notificação
    é gravada por um consumidor, em outro processo, a partir de um evento.
    """

    serializer_class = NotificacaoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Notificacao.objects.filter(pedido__usuario=self.request.user)
            .select_related("pedido", "pagamento")
            .all()
        )
