"""Integração: ciclo de vida completo do pedido.

Cobre pedido ➔ pagamento ➔ notificação na API: criação com publicação do
evento, consulta com cache, pagamento aprovado/recusado idempotente e a
notificação registrada pelo consumidor observável via ``GET /api/v1/notificacoes/``.
"""

import pytest
from django.db import IntegrityError

from events.contracts import EventoPagamentoProcessado
from repositories.models import Notificacao, Pagamento, Pedido
from services import notificacao

pytestmark = pytest.mark.django_db


def _criar_pedido(client, item, key="pedido-int-1", quantidade=2):
    return client.post(
        "/api/v1/pedidos/",
        {"idempotency_key": key, "itens": [{"item_id": item.pk, "quantidade": quantidade}]},
        format="json",
    )


@pytest.mark.integration
def test_pedido_lifecycle_completo(
    authenticated_client, usuario, item, broker_disponivel
):
    # 1) Criação publica PedidoCriado e persiste com total calculado no servidor.
    criacao = _criar_pedido(authenticated_client, item, key="pedido-1")
    assert criacao.status_code == 201
    corpo = criacao.json()
    assert corpo["evento_publicado"] is True
    pedido_id = corpo["id"]
    assert corpo["total"] == str(item.price * 2)
    assert Pedido.objects.filter(pk=pedido_id, usuario=usuario).exists()
    assert broker_disponivel[-1]["evento"]["event_type"] == "PedidoCriado"

    # 2) Consulta: MISS, depois HIT (cache do detalhe do pedido).
    primeira = authenticated_client.get(f"/api/v1/pedidos/{pedido_id}/")
    assert primeira.status_code == 200
    assert primeira.headers["X-Cache"] == "MISS"
    segunda = authenticated_client.get(f"/api/v1/pedidos/{pedido_id}/")
    assert segunda.headers["X-Cache"] == "HIT"

    # 3) Pagamento aprovado publica PagamentoProcessado e move o pedido para PAGO.
    pagamento = authenticated_client.post(
        f"/api/v1/pedidos/{pedido_id}/pagamento/",
        {"resultado": "APROVADO", "forma_pagamento": "pix"},
        format="json",
    )
    assert pagamento.status_code == 201
    assert pagamento.json()["evento_publicado"] is True
    assert Pagamento.objects.filter(pedido_id=pedido_id, status="APROVADO").exists()
    assert Pedido.objects.get(pk=pedido_id).status == Pedido.Status.PAGO

    # 4) Repetir o pagamento é idempotente: 200 e nenhum evento novo.
    repetido = authenticated_client.post(
        f"/api/v1/pedidos/{pedido_id}/pagamento/", {}, format="json"
    )
    assert repetido.status_code == 200
    assert repetido.json()["evento_publicado"] is False

    # 5) O consumidor (notificacao-worker) processa o evento e grava a notificação.
    pedido = Pedido.objects.get(pk=pedido_id)
    registro = Pagamento.objects.get(pedido_id=pedido_id)
    evento = EventoPagamentoProcessado(
        idempotency_key=f"pagamento:{registro.pk}",
        pagamento_id=registro.pk,
        pedido_id=pedido_id,
        usuario_id=usuario.pk,
        valor=registro.valor,
        status=registro.status,
        forma_pagamento=registro.forma_pagamento,
        referencia=registro.referencia,
        correlation_id=pedido.correlation_id,
    )
    notificacao.processar_pagamento_processado(evento.to_dict())
    assert Notificacao.objects.filter(pedido_id=pedido_id).count() == 1

    # 6) A notificação é observável pela API.
    resposta = authenticated_client.get("/api/v1/notificacoes/")
    assert resposta.status_code == 200
    assert any(linha["pedido"] == pedido_id for linha in resposta.json()["results"])


@pytest.mark.integration
def test_pedido_duplicado_devolve_mesmo_pedido(
    authenticated_client, item, broker_disponivel
):
    primeira = _criar_pedido(authenticated_client, item, key="pedido-dup")
    segunda = _criar_pedido(authenticated_client, item, key="pedido-dup")

    assert primeira.status_code == 201
    assert segunda.status_code == 200
    assert primeira.json()["id"] == segunda.json()["id"]


@pytest.mark.integration
def test_pedido_sem_broker_devolve_202(authenticated_client, item):
    resposta = _criar_pedido(authenticated_client, item, key="pedido-sem-broker")
    assert resposta.status_code == 202
    assert resposta.json()["evento_publicado"] is False


@pytest.mark.integration
def test_pedido_pagamento_recusado_cancela_pedido(authenticated_client, pedido):
    resposta = authenticated_client.post(
        f"/api/v1/pedidos/{pedido.pk}/pagamento/", {"resultado": "RECUSADO"}, format="json"
    )
    assert resposta.status_code == 201
    pedido.refresh_from_db()
    assert pedido.status == Pedido.Status.CANCELADO


def test_pedido_de_outro_usuario_nao_e_visivel(api_client, outro_usuario, pedido):
    api_client.force_authenticate(outro_usuario)
    assert api_client.get(f"/api/v1/pedidos/{pedido.pk}/").status_code == 404


def test_admin_enxerga_pedido_de_qualquer_usuario(admin_client, pedido):
    resposta = admin_client.get(f"/api/v1/pedidos/{pedido.pk}/")
    assert resposta.status_code == 200


def test_pagamento_de_pedido_de_outro_usuario_404(api_client, outro_usuario, pedido):
    api_client.force_authenticate(outro_usuario)
    resposta = api_client.post(
        f"/api/v1/pedidos/{pedido.pk}/pagamento/", {}, format="json"
    )
    assert resposta.status_code == 404


def test_item_inexistente_na_criacao_de_pedido_400(authenticated_client):
    resposta = authenticated_client.post(
        "/api/v1/pedidos/",
        {"itens": [{"item_id": 99999, "quantidade": 1}]},
        format="json",
    )
    assert resposta.status_code == 400


def test_pedido_sem_itens_400(authenticated_client):
    resposta = authenticated_client.post(
        "/api/v1/pedidos/", {"itens": []}, format="json"
    )
    assert resposta.status_code == 400


def test_pedido_duplicado_simultaneo_devolve_409(
    authenticated_client, item, monkeypatch
):
    class ConsultaVazia:
        def first(self):
            return None

    chamadas = {"n": 0}
    filtro_real = Pedido.objects.filter

    def filtro_falso(*args, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return ConsultaVazia()
        return filtro_real(*args, **kwargs)

    monkeypatch.setattr(Pedido.objects, "filter", filtro_falso)

    def criar_com_conflito(**kwargs):
        raise IntegrityError("unicidade da idempotency_key")

    monkeypatch.setattr(Pedido.objects, "create", criar_com_conflito)

    resposta = authenticated_client.post(
        "/api/v1/pedidos/",
        {"idempotency_key": "pedido-conflito", "itens": [{"item_id": item.pk, "quantidade": 1}]},
        format="json",
    )
    assert resposta.status_code == 409


def test_pedido_duplicado_simultaneo_vencedor_devolve_200(
    authenticated_client, item, pedido, monkeypatch
):
    chamadas = {"n": 0}

    class ConsultaVazia:
        def first(self):
            return None

    class ConsultaComPedido:
        def first(self):
            return pedido

    filtro_real = Pedido.objects.filter

    def filtro_falso(*args, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return ConsultaVazia()
        return ConsultaComPedido()

    monkeypatch.setattr(Pedido.objects, "filter", filtro_falso)

    def criar_com_conflito(**kwargs):
        raise IntegrityError("unicidade da idempotency_key")

    monkeypatch.setattr(Pedido.objects, "create", criar_com_conflito)

    resposta = authenticated_client.post(
        "/api/v1/pedidos/",
        {"idempotency_key": "pedido-vencedor", "itens": [{"item_id": item.pk, "quantidade": 1}]},
        format="json",
    )
    assert resposta.status_code == 200
    assert resposta.json()["id"] == pedido.pk


def test_admin_pode_pagar_pedido_de_outro_usuario(admin_client, pedido):
    resposta = admin_client.post(
        f"/api/v1/pedidos/{pedido.pk}/pagamento/",
        {"resultado": "APROVADO"},
        format="json",
    )
    assert resposta.status_code == 201