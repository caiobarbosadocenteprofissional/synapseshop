"""Integração: liveness e readiness (``/health`` e ``/health/pronto``)."""

import pytest

from services import health

pytestmark = pytest.mark.integration


def test_health_liveness_responde_sempre(client):
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_health_pronto_200_com_dependencias_ok(client, db):
    resposta = client.get("/health/pronto")
    assert resposta.status_code == 200
    assert resposta.json()["pronto"] is True


def test_health_pronto_503_com_broker_fora(client, db, monkeypatch, settings):
    settings.MESSAGERIA_ENABLED = True
    monkeypatch.setattr(
        health, "_verificar_broker", lambda: {"ok": False, "broker": "kafka"}
    )

    resposta = client.get("/health/pronto")
    assert resposta.status_code == 503
    assert resposta.json()["pronto"] is False
    assert "broker" in resposta.json()["fora_do_ar"]