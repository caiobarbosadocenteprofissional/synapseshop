"""Integração: fluxos de autenticação JWT com a claim ``role``."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_obter_token_deve_incluir_role(api_client, usuario):
    resposta = api_client.post(
        "/api/v1/auth/token/",
        {"username": "cliente", "password": "pass123"},
        format="json",
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "access" in corpo
    assert "refresh" in corpo
    assert corpo["role"] == "user"


@pytest.mark.django_db
def test_obter_token_admin_tem_role_admin(api_client, admin_user):
    resposta = api_client.post(
        "/api/v1/auth/token/",
        {"username": "admin", "password": "admin123"},
        format="json",
    )
    assert resposta.status_code == 200
    assert resposta.json()["role"] == "admin"


@pytest.mark.django_db
def test_obter_token_credenciais_invalidas(api_client, usuario):
    resposta = api_client.post(
        "/api/v1/auth/token/",
        {"username": "cliente", "password": "errada"},
        format="json",
    )
    assert resposta.status_code == 401


@pytest.mark.django_db
def test_refresh_token_deve_conservar_role(api_client, usuario):
    token = api_client.post(
        "/api/v1/auth/token/",
        {"username": "cliente", "password": "pass123"},
        format="json",
    ).json()

    resposta = api_client.post(
        "/api/v1/auth/token/refresh/",
        {"refresh": token["refresh"]},
        format="json",
    )
    assert resposta.status_code == 200
    assert resposta.json()["role"] == "user"


@pytest.mark.django_db
def test_bearer_token_acessa_endpoint_protegido(api_client, usuario):
    token = api_client.post(
        "/api/v1/auth/token/",
        {"username": "cliente", "password": "pass123"},
        format="json",
    ).json()["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resposta = api_client.get("/api/v1/pedidos/999999/")
    # Autenticou (não é 401); o 404 vem de o pedido não existir.
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_rota_protegida_sem_token_rejeita(api_client):
    resposta = api_client.get("/api/v1/pedidos/1/")
    assert resposta.status_code in (401, 403)