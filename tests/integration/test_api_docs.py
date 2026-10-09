"""Integração: documentação da API e cabeçalhos de contrato (Aula 13).

Cobre as rotas de documentação (``/docs/``, ``/docs/redoc/`` e ``/openapi.yaml``)
e os cabeçalhos que o contrato OpenAPI publica como parte da interface:
``Idempotency-Key`` (alternativa ao corpo) e ``X-Trace-Id`` (correlação).
"""

from pathlib import Path

import pytest

from api import docs as docs_module
from repositories.models import Pedido

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Interfaces de documentação
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_swagger_ui_aponta_para_o_contrato(api_client):
    resposta = api_client.get("/docs/")
    assert resposta.status_code == 200
    html = resposta.content.decode("utf-8")
    assert "swagger-ui" in html
    assert "/openapi.yaml" in html


@pytest.mark.integration
def test_redoc_aponta_para_o_contrato(api_client):
    resposta = api_client.get("/docs/redoc/")
    assert resposta.status_code == 200
    html = resposta.content.decode("utf-8")
    assert "redoc" in html.lower()
    assert "/openapi.yaml" in html


@pytest.mark.integration
def test_openapi_yaml_servido_na_raiz(api_client):
    resposta = api_client.get("/openapi.yaml")
    assert resposta.status_code == 200
    assert "yaml" in resposta["Content-Type"]
    corpo = resposta.content.decode("utf-8")
    assert "openapi: 3.0.3" in corpo
    assert "/api/v1/pedidos/" in corpo
    assert "/api/v1/pedidos/{id}/pagamento/" in corpo


@pytest.mark.integration
def test_openapi_yaml_ausente_devolve_404(api_client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        docs_module, "OPENAPI_PATH", tmp_path / "inexistente.yaml"
    )
    assert api_client.get("/openapi.yaml").status_code == 404


# --------------------------------------------------------------------------- #
# Cabeçalhos do contrato
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_idempotency_key_no_cabecalho_cria_e_reaproveita_pedido(
    authenticated_client, item, broker_disponivel
):
    corpo = {"itens": [{"item_id": item.pk, "quantidade": 1}]}
    primeira = authenticated_client.post(
        "/api/v1/pedidos/", corpo, format="json", HTTP_IDEMPOTENCY_KEY="pedido-header-1"
    )
    assert primeira.status_code == 201
    assert Pedido.objects.filter(idempotency_key="pedido-header-1").exists()

    segunda = authenticated_client.post(
        "/api/v1/pedidos/", corpo, format="json", HTTP_IDEMPOTENCY_KEY="pedido-header-1"
    )
    assert segunda.status_code == 200
    assert primeira.json()["id"] == segunda.json()["id"]


@pytest.mark.integration
def test_x_trace_id_vira_correlation_id_e_e_ecoado_na_resposta(
    authenticated_client, item, broker_disponivel
):
    resposta = authenticated_client.post(
        "/api/v1/pedidos/",
        {"itens": [{"item_id": item.pk, "quantidade": 1}]},
        format="json",
        HTTP_X_TRACE_ID="trace-abc-123",
    )
    assert resposta.status_code == 201
    assert resposta["X-Trace-Id"] == "trace-abc-123"
    pedido = Pedido.objects.get(pk=resposta.json()["id"])
    assert pedido.correlation_id == "trace-abc-123"


@pytest.mark.integration
def test_cabecalho_idempotency_key_aceita_caminho_do_arquivo_de_contrato():
    """Guarda de regressão: o contrato continua na raiz, fora de ``docs/``.

    Se o ``openapi.yaml`` fosse movido para ``docs/`` (diretório excluído pelo
    ``.dockerignore``), ele não acompanharia a imagem e esta rota quebraria.
    """
    assert docs_module.OPENAPI_PATH == Path(docs_module.settings.BASE_DIR) / "openapi.yaml"
    assert docs_module.OPENAPI_PATH.exists()
    assert docs_module.OPENAPI_PATH.parent.name != "docs"
