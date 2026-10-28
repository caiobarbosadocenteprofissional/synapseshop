"""Testes da coleta real de métricas da Aula 20."""

import pytest
from django.test import override_settings

from repositories.models import ApiRequestLog


@pytest.mark.django_db
@override_settings(API_METRICS_ENABLED=True)
def test_middleware_registra_requisicao_api(admin_client):
    resposta = admin_client.get("/api/v1/categories/")

    assert resposta.status_code == 200
    registro = ApiRequestLog.objects.get()
    assert registro.method == "GET"
    assert registro.endpoint == "/api/v1/categories/"
    assert registro.status_code == 200
    assert registro.response_time_ms >= 0


@pytest.mark.django_db
@override_settings(API_METRICS_ENABLED=True)
def test_middleware_registra_status_de_erro(admin_client):
    resposta = admin_client.get("/api/v1/rota-inexistente/")

    assert resposta.status_code == 404
    registro = ApiRequestLog.objects.get()
    assert registro.status_code == 404


@pytest.mark.django_db
@override_settings(API_METRICS_ENABLED=True)
def test_middleware_ignora_rotas_fora_da_api(api_client):
    resposta = api_client.get("/")

    assert resposta.status_code == 404
    assert not ApiRequestLog.objects.exists()


@pytest.mark.django_db
@override_settings(API_METRICS_ENABLED=False)
def test_kill_switch_desliga_coleta(admin_client):
    resposta = admin_client.get("/api/v1/categories/")

    assert resposta.status_code == 200
    assert not ApiRequestLog.objects.exists()
