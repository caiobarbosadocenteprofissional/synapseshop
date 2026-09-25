from django.http import JsonResponse
from rest_framework import permissions, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from api.serializers import CategorySerializer, ItemSerializer
from repositories.models import Category, Item, User


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