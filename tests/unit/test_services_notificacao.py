"""Testes do serviço de notificação (``services.notificacao``).

É o lado consumidor do segundo elo do fluxo: ``PagamentoProcessado`` aprovado
gera notificação; recusado não gera. Reentrega não duplica.
"""

import pytest
from django.utils import timezone

from events.contracts import EventoPagamentoProcessado
from repositories.models import Notificacao, Pagamento
from services import notificacao
from services.notificacao import PagamentoInexistente

pytestmark = pytest.mark.unit


def _criar_pagamento(pedido, status=Pagamento.Status.APROVADO):
    return Pagamento.objects.create(
        pedido=pedido,
        status=status,
        valor=pedido.total,
        forma_pagamento=Pagamento.Formas.PIX,
        referencia="E" + "b" * 32,
        processado_em=timezone.now(),
    )


def _evento(pagamento, status=None, **overrides):
    evento = EventoPagamentoProcessado(
        idempotency_key=f"pagamento:{pagamento.pk}",
        pagamento_id=pagamento.pk,
        pedido_id=pagamento.pedido_id,
        usuario_id=pagamento.pedido.usuario_id,
        valor=pagamento.valor,
        status=status or pagamento.status,
        forma_pagamento=pagamento.forma_pagamento,
        referencia=pagamento.referencia,
        correlation_id="corr",
    )
    bruto = evento.to_dict()
    bruto.update(overrides)
    return bruto


def test_destinatario_usa_email_quando_existe(pedido):
    assert notificacao._destinatario(pedido.usuario) == "cliente@synapseshop.com"


def test_destinatario_sem_email_usa_fallback(db, pedido):
    pedido.usuario.email = ""
    pedido.usuario.save(update_fields=["email"])
    assert notificacao._destinatario(pedido.usuario).startswith("usuario-")


def test_mensagem_deriva_de_pedido_e_pagamento(db, pedido):
    registro = _criar_pagamento(pedido)
    assunto, conteudo = notificacao._mensagem(pedido, registro)
    assert f"#{pedido.pk}" in assunto
    assert "aprovado" in conteudo
    assert str(registro.valor) in conteudo


def test_processar_aprovado_cria_notificacao(db, pedido, broker_disponivel):
    registro = _criar_pagamento(pedido)
    notificacao.processar_pagamento_processado(_evento(registro))

    assert Notificacao.objects.filter(pedido=pedido).count() == 1
    assert broker_disponivel[-1]["evento"]["event_type"] == "NotificacaoEnviada"


def test_processar_aprovado_sem_broker_ainda_cria(db, pedido):
    registro = _criar_pagamento(pedido)
    notificacao.processar_pagamento_processado(_evento(registro))
    assert Notificacao.objects.filter(pedido=pedido).count() == 1


def test_processar_duplicado_nao_duplica_notificacao(db, pedido, broker_disponivel):
    registro = _criar_pagamento(pedido)
    bruto = _evento(registro)

    notificacao.processar_pagamento_processado(bruto)
    notificacao.processar_pagamento_processado(bruto)

    assert Notificacao.objects.filter(pedido=pedido).count() == 1


def test_processar_recusado_nao_cria_notificacao(db, pedido, broker_disponivel):
    registro = _criar_pagamento(pedido, status=Pagamento.Status.RECUSADO)
    notificacao.processar_pagamento_processado(_evento(registro, status="RECUSADO"))
    assert Notificacao.objects.count() == 0


def test_processar_pagamento_inexistente_levanta(db, pedido):
    registro = _criar_pagamento(pedido)
    bruto = _evento(registro)
    bruto["dados"]["pagamento_id"] = 99999

    with pytest.raises(PagamentoInexistente):
        notificacao.processar_pagamento_processado(bruto)


def test_processar_pedido_divergente_levanta(db, pedido):
    registro = _criar_pagamento(pedido)
    bruto = _evento(registro)
    bruto["dados"]["pedido_id"] = 12345

    with pytest.raises(PagamentoInexistente):
        notificacao.processar_pagamento_processado(bruto)


def test_registrar_e_idempotente_por_evento_de_origem(db, pedido):
    registro = _criar_pagamento(pedido)
    evento = EventoPagamentoProcessado.from_dict(_evento(registro))

    primeira = notificacao._registrar(evento, registro, pedido)
    segunda = notificacao._registrar(evento, registro, pedido)

    assert primeira.pk == segunda.pk
    assert Notificacao.objects.count() == 1


def test_registrar_resolve_corrida_de_reentrega(db, pedido, monkeypatch):
    from django.db import IntegrityError

    registro = _criar_pagamento(pedido)
    evento = EventoPagamentoProcessado.from_dict(_evento(registro))

    vencedor = Notificacao.objects.create(
        pedido=pedido,
        pagamento=registro,
        destinatario="vencedor@y.com",
        canal=Notificacao.Canais.EMAIL,
        assunto="a",
        conteudo="c",
        evento_origem=evento.event_id,
    )
    respostas = [None, vencedor]

    class ConsultaFalsa:
        def first(self):
            return respostas.pop(0)

    monkeypatch.setattr(Notificacao.objects, "filter", lambda **kwargs: ConsultaFalsa())

    def criar_conflito(**kwargs):
        raise IntegrityError("indice unico de evento_origem")

    monkeypatch.setattr(Notificacao.objects, "create", criar_conflito)

    linha = notificacao._registrar(evento, registro, pedido)
    assert linha.pk == vencedor.pk


def test_registrar_reentrega_sem_vencedor_levanta(db, pedido, monkeypatch):
    from django.db import IntegrityError

    registro = _criar_pagamento(pedido)
    evento = EventoPagamentoProcessado.from_dict(_evento(registro))

    class ConsultaVazia:
        def first(self):
            return None

    monkeypatch.setattr(Notificacao.objects, "filter", lambda **kwargs: ConsultaVazia())

    def criar_conflito(**kwargs):
        raise IntegrityError("indice unico de evento_origem")

    monkeypatch.setattr(Notificacao.objects, "create", criar_conflito)

    with pytest.raises(IntegrityError):
        notificacao._registrar(evento, registro, pedido)


def test_evento_notificacao_enviada_carrega_campos(db, pedido):
    registro = _criar_pagamento(pedido)
    linha = Notificacao.objects.create(
        pedido=pedido,
        pagamento=registro,
        destinatario="x@y.com",
        canal=Notificacao.Canais.EMAIL,
        assunto="a",
        conteudo="c",
        evento_origem="evento-1",
    )
    evento = notificacao.evento_notificacao_enviada(linha)
    assert evento.notificacao_id == linha.pk
    assert evento.pagamento_id == registro.pk
    assert evento.canal == Notificacao.Canais.EMAIL


def test_publicar_notificacao_sucesso(db, pedido, broker_disponivel):
    registro = _criar_pagamento(pedido)
    linha = Notificacao.objects.create(
        pedido=pedido,
        pagamento=registro,
        destinatario="x@y.com",
        canal="EMAIL",
        assunto="a",
        conteudo="c",
        evento_origem="evento-2",
    )
    assert notificacao.publicar_notificacao_enviada(linha) is True


def test_publicar_notificacao_broker_fora(db, pedido, broker_indisponivel):
    registro = _criar_pagamento(pedido)
    linha = Notificacao.objects.create(
        pedido=pedido,
        pagamento=registro,
        destinatario="x@y.com",
        canal="EMAIL",
        assunto="a",
        conteudo="c",
        evento_origem="evento-3",
    )
    assert notificacao.publicar_notificacao_enviada(linha) is False
