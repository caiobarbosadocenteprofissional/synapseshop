"""Integração: endpoint de métricas do cache, restrito ao papel admin."""

import pytest

pytestmark = pytest.mark.django_db


def test_get_metricas_para_admin(admin_client):
    resposta = admin_client.get("/api/v1/cache/stats/")
    assert resposta.status_code == 200
    assert resposta.json()["cache_habilitado"] is True


def test_post_reseta_metricas(admin_client):
    resposta = admin_client.post("/api/v1/cache/stats/")
    assert resposta.status_code == 200
    assert resposta.json()["total_lookups"] == 0


def test_metricas_negadas_para_usuario_comum(authenticated_client):
    assert authenticated_client.get("/api/v1/cache/stats/").status_code == 403


def test_metricas_negadas_para_anonimo(api_client):
    assert api_client.get("/api/v1/cache/stats/").status_code in (401, 403)