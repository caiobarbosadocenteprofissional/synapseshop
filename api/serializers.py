from decimal import Decimal

from rest_framework import serializers

from repositories.models import Category, Item, Pedido, PedidoItem


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("O nome da categoria é obrigatório.")
        return name


class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "description",
            "price",
            "category",
            "category_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "created_at", "updated_at"]

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("O nome do item é obrigatório.")
        return name

    def validate_price(self, value):
        if value is None or value < Decimal("0.00"):
            raise serializers.ValidationError("O preço não pode ser negativo.")
        return value


class PedidoItemInputSerializer(serializers.Serializer):
    """Linha recebida na criação do pedido. O preço vem do catálogo, não do cliente."""

    item_id = serializers.IntegerField()
    quantidade = serializers.IntegerField(min_value=1, max_value=999)

    def validate_item_id(self, value):
        if not Item.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError(f"Item {value} não existe ou está inativo.")
        return value


class PedidoCreateSerializer(serializers.Serializer):
    """Entrada de ``POST /api/v1/pedidos/``.

    ``idempotency_key`` é a chave de negócio do pedido: repeti-la devolve o mesmo
    pedido em vez de criar outro, e é ela que o consumidor usa para deduplicar a
    reentrega do evento.
    """

    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    itens = PedidoItemInputSerializer(many=True)

    def validate_itens(self, value):
        if not value:
            raise serializers.ValidationError("O pedido precisa de ao menos um item.")
        vistos = [linha["item_id"] for linha in value]
        if len(set(vistos)) != len(vistos):
            raise serializers.ValidationError("O mesmo item não pode repetir no pedido.")
        return value

    def validate_idempotency_key(self, value):
        chave = (value or "").strip()
        return chave


class PedidoItemSerializer(serializers.ModelSerializer):
    nome_item = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = PedidoItem
        fields = ["item_id", "nome_item", "quantidade", "preco_unitario"]
        read_only_fields = fields


class PedidoSerializer(serializers.ModelSerializer):
    itens = PedidoItemSerializer(many=True, read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "usuario",
            "status",
            "total",
            "idempotency_key",
            "processado_em",
            "created_at",
            "itens",
        ]
        read_only_fields = fields
