"""Testes dos modelos — ``__str__`` e propriedades de negócio.

A cobertura de modelos é fina de propósito: a persisência em si é coberta pelos
testes de integração; aqui o foco é a superfície observável.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from repositories.models import (
    EventoProcessado,
    Notificacao,
    Pagamento,
    Pedido,
    PedidoItem,
)

pytestmark = pytest.mark.unit


def test_str_dos_modelos(db, usuario, categoria, item):
    assert str(categoria) == "Eletrônicos"
    assert str(item) == "Fone Bluetooth"

    pedido = Pedido.objects.create(
        usuario=usuario, total=Decimal("1.00"), idempotency_key="k-modelos"
    )
    assert "PENDENTE" in str(pedido)

    linha = PedidoItem.objects.create(
        pedido=pedido, item=item, quantidade=1, preco_unitario=Decimal("1.00")
    )
    assert str(item.pk) in str(linha)

    pagamento = Pagamento.objects.create(
        pedido=pedido,
        valor=Decimal("1.00"),
        forma_pagamento="pix",
        referencia="E1",
    )
    assert "Pagamento" in str(pagamento)
    assert pagamento.aprovado is True

    notificacao = Notificacao.objects.create(
        pedido=pedido,
        pagamento=pagamento,
        destinatario="x@y.com",
        canal="EMAIL",
        assunto="a",
        conteudo="c",
        evento_origem="e-1",
    )
    assert "EMAIL" in str(notificacao)

    processado = EventoProcessado.objects.create(
        evento="E", idempotency_key="k", expira_em=timezone.now()
    )
    assert str(processado) == "E:k"