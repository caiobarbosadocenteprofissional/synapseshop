"""Testes do serviço de pagamento simulado (``services.pagamento``)."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from repositories.models import Pagamento, Pedido
from services import pagamento

pytestmark = pytest.mark.unit


def test_registrar_pagamento_aprovado_move_pedido_para_pago(db, pedido):
    registro, criado = pagamento.registrar_pagamento(
        pedido, Pagamento.Status.APROVADO, Pagamento.Formas.PIX
    )
    assert criado is True
    assert registro.status == Pagamento.Status.APROVADO
    assert registro.valor == pedido.total
    pedido.refresh_from_db()
    assert pedido.status == Pedido.Status.PAGO
    assert pedido.processado_em is not None


def test_registrar_pagamento_recusado_move_pedido_para_cancelado(db, pedido):
    registro, criado = pagamento.registrar_pagamento(
        pedido, Pagamento.Status.RECUSADO, Pagamento.Formas.BOLETO
    )
    assert criado is True
    assert registro.status == Pagamento.Status.RECUSADO
    pedido.refresh_from_db()
    assert pedido.status == Pedido.Status.CANCELADO


def test_registrar_pagamento_e_idempotente_por_pedido(db, pedido):
    primeiro, criado1 = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    segundo, criado2 = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    assert criado1 is True
    assert criado2 is False
    assert primeiro.pk == segundo.pk
    assert Pagamento.objects.filter(pedido=pedido).count() == 1


def test_registrar_pagamento_resolve_conflito_de_corrida(db, pedido, monkeypatch):
    vencedor = Pagamento.objects.create(
        pedido=pedido,
        status=Pagamento.Status.APROVADO,
        valor=pedido.total,
        forma_pagamento="pix",
        referencia="E" + "a" * 32,
        processado_em=timezone.now(),
    )
    respostas = [None, vencedor]

    class ConsultaFalsa:
        def first(self):
            return respostas.pop(0)

    monkeypatch.setattr(Pagamento.objects, "filter", lambda **kwargs: ConsultaFalsa())

    def criar_conflito(**kwargs):
        raise IntegrityError("unicidade do pagamento")

    monkeypatch.setattr(Pagamento.objects, "create", criar_conflito)

    registro, criado = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    assert criado is False
    assert registro.pk == vencedor.pk


def test_registrar_pagamento_conflito_sem_vencedor_levanta(db, pedido, monkeypatch):
    class ConsultaVazia:
        def first(self):
            return None

    monkeypatch.setattr(Pagamento.objects, "filter", lambda **kwargs: ConsultaVazia())

    def criar_conflito(**kwargs):
        raise IntegrityError("unicidade do pagamento")

    monkeypatch.setattr(Pagamento.objects, "create", criar_conflito)

    with pytest.raises(IntegrityError):
        pagamento.registrar_pagamento(pedido, "APROVADO", "pix")


def test_evento_pagamento_processado_carrega_campos(db, pedido):
    registro, _ = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    evento = pagamento.evento_pagamento_processado(registro)

    assert evento.idempotency_key == f"pagamento:{registro.pk}"
    assert evento.pagamento_id == registro.pk
    assert evento.pedido_id == pedido.pk
    assert evento.usuario_id == pedido.usuario_id
    assert evento.aprovado is True
    assert evento.correlation_id == pedido.correlation_id


def test_publicar_pagamento_processado_sucesso(db, pedido, broker_disponivel):
    registro, _ = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    assert pagamento.publicar_pagamento_processado(registro) is True
    assert broker_disponivel[-1]["evento"]["event_type"] == "PagamentoProcessado"


def test_publicar_pagamento_processado_broker_fora(db, pedido, broker_indisponivel):
    registro, _ = pagamento.registrar_pagamento(pedido, "APROVADO", "pix")
    assert pagamento.publicar_pagamento_processado(registro) is False


def test_referencia_simulada_tem_formato_pix():
    referencia = pagamento._referencia_simulada()
    assert referencia.startswith("E")
    assert len(referencia) == 33
