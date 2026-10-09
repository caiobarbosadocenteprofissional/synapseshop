"""Testes dos serializers da API — validação de entrada (caminhos felizes e erro)."""

import pytest
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers as drf

from api import serializers

pytestmark = pytest.mark.unit


def test_category_validate_name_aplica_strip(db):
    serializer = serializers.CategorySerializer(
        data={"name": "  Eletrônicos  ", "description": "x"}
    )
    assert serializer.is_valid()
    assert serializer.validated_data["name"] == "Eletrônicos"


def test_category_validate_name_vazio_rejeita():
    serializer = serializers.CategorySerializer(data={"name": "    "})
    assert not serializer.is_valid()
    assert "name" in serializer.errors


def test_item_validate_name_vazio_rejeita(db, categoria):
    serializer = serializers.ItemSerializer(
        data={"name": "   ", "price": "1.00", "category": categoria.pk}
    )
    assert not serializer.is_valid()
    assert "name" in serializer.errors


def test_item_validate_price_negativo_rejeita(db, categoria):
    serializer = serializers.ItemSerializer(
        data={"name": "Mouse", "price": "-1.00", "category": categoria.pk}
    )
    assert not serializer.is_valid()
    assert "price" in serializer.errors


def test_pedido_create_valido(db, item):
    serializer = serializers.PedidoCreateSerializer(
        data={"itens": [{"item_id": item.pk, "quantidade": 2}]}
    )
    assert serializer.is_valid(), serializer.errors


def test_pedido_create_item_inexistente(db):
    serializer = serializers.PedidoCreateSerializer(
        data={"itens": [{"item_id": 99999, "quantidade": 1}]}
    )
    assert not serializer.is_valid()
    assert "itens" in serializer.errors


def test_pedido_create_item_inativo(db, item):
    item.is_active = False
    item.save(update_fields=["is_active"])
    serializer = serializers.PedidoCreateSerializer(
        data={"itens": [{"item_id": item.pk, "quantidade": 1}]}
    )
    assert not serializer.is_valid()


def test_pedido_create_sem_itens(db):
    serializer = serializers.PedidoCreateSerializer(data={"itens": []})
    assert not serializer.is_valid()
    assert "itens" in serializer.errors


def test_pedido_create_item_repetido(db, item):
    serializer = serializers.PedidoCreateSerializer(
        data={
            "itens": [
                {"item_id": item.pk, "quantidade": 1},
                {"item_id": item.pk, "quantidade": 1},
            ]
        }
    )
    assert not serializer.is_valid()


def test_pedido_create_quantidade_abaixo_do_minimo(db, item):
    serializer = serializers.PedidoCreateSerializer(
        data={"itens": [{"item_id": item.pk, "quantidade": 0}]}
    )
    assert not serializer.is_valid()


def test_pedido_create_idempotency_key_e_normalizada(db, item):
    serializer = serializers.PedidoCreateSerializer(
        data={"idempotency_key": "  chave-1  ", "itens": [{"item_id": item.pk, "quantidade": 1}]}
    )
    assert serializer.is_valid()
    assert serializer.validated_data["idempotency_key"] == "chave-1"


def test_pagamento_create_usa_defaults(db):
    serializer = serializers.PagamentoCreateSerializer(data={})
    assert serializer.is_valid()
    assert serializer.validated_data["resultado"] == "APROVADO"
    assert serializer.validated_data["forma_pagamento"] == "cartao_credito"


def test_pagamento_create_aceita_desfecho_recusado():
    serializer = serializers.PagamentoCreateSerializer(data={"resultado": "RECUSADO"})
    assert serializer.is_valid()
    assert serializer.validated_data["resultado"] == "RECUSADO"


def test_pagamento_create_resultado_invalido_rejeita():
    serializer = serializers.PagamentoCreateSerializer(data={"resultado": "XX"})
    assert not serializer.is_valid()


# Os validadores customizados de nome/preço são defensivos: a validação de campo
# do DRF costuma interceptar os valores inválidos antes. Chamá-los diretamente
# cobre o ramo de erro que o ramo feliz dos testes de integração também exerce.
def test_category_validate_name_ramo_de_erro():
    serializer = serializers.CategorySerializer()
    with pytest.raises(drf.ValidationError):
        serializer.validate_name("   ")


def test_item_validate_name_ramo_de_erro():
    serializer = serializers.ItemSerializer()
    with pytest.raises(drf.ValidationError):
        serializer.validate_name("   ")


def test_item_validate_price_ramo_de_erro():
    serializer = serializers.ItemSerializer()
    with pytest.raises(drf.ValidationError):
        serializer.validate_price(Decimal("-1.00"))