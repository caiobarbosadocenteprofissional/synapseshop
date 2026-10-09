"""Testes das verificações de saúde (``services.health``).

Cada dependência é exercitada isoladamente, com sucesso e com falha — é o
relatório agregado que decide se ``/health/pronto`` devolve 200 ou 503.
"""

import pytest
from django.core.cache import cache as django_cache

from services import health

pytestmark = pytest.mark.unit


class _CursorContexto:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_verificar_postgres_ok(db):
    resultado = health._verificar_postgres()
    assert resultado["ok"] is True


def test_verificar_postgres_falha(monkeypatch):
    class ConexaoRuim:
        def cursor(self):
            raise RuntimeError("banco fora")

    monkeypatch.setattr(health, "connections", {"default": ConexaoRuim()})
    resultado = health._verificar_postgres()
    assert resultado["ok"] is False
    assert "banco fora" in resultado["erro"]


def test_verificar_redis_desabilitado(sem_cache):
    resultado = health._verificar_redis()
    assert resultado["ok"] is True
    assert "CACHE_ENABLED=false" in resultado["observacao"]


def test_verificar_redis_ok(db):
    resultado = health._verificar_redis()
    assert resultado["ok"] is True


def test_verificar_redis_resposta_inesperada(settings, monkeypatch):
    settings.CACHE_ENABLED = True
    monkeypatch.setattr(django_cache, "get", lambda *args, **kwargs: None)
    resultado = health._verificar_redis()
    assert resultado["ok"] is False


def test_alvo_broker_kafka(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    settings.KAFKA_BOOTSTRAP_SERVERS = "kafka1:9092,kafka2:9093"
    assert health._alvo_do_broker() == {"host": "kafka1", "porta": 9092, "broker": "kafka"}


def test_alvo_broker_kafka_sem_porta_usa_default(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    settings.KAFKA_BOOTSTRAP_SERVERS = "kafka1"
    assert health._alvo_do_broker()["porta"] == 9092


def test_alvo_broker_rabbitmq(settings):
    settings.MENSAGERIA_BROKER = "rabbitmq"
    settings.RABBITMQ_HOST = "rabbit"
    settings.RABBITMQ_PORT = 5672
    assert health._alvo_do_broker() == {"host": "rabbit", "porta": 5672, "broker": "rabbitmq"}


def test_verificar_broker_ok(settings, monkeypatch):
    settings.MENSAGERIA_BROKER = "kafka"
    settings.KAFKA_BOOTSTRAP_SERVERS = "host:9092"
    monkeypatch.setattr(
        health.socket, "create_connection", lambda *a, **k: _CursorContexto()
    )
    assert health._verificar_broker()["ok"] is True


def test_verificar_broker_falha(settings, monkeypatch):
    settings.MENSAGERIA_BROKER = "kafka"
    settings.KAFKA_BOOTSTRAP_SERVERS = "host:9092"

    def recusar(*args, **kwargs):
        raise OSError("conexao recusada")

    monkeypatch.setattr(health.socket, "create_connection", recusar)
    resultado = health._verificar_broker()
    assert resultado["ok"] is False
    assert "conexao recusada" in resultado["erro"]


def test_verificar_agrega_tudo_pronto(db):
    relatorio = health.verificar()
    assert relatorio["pronto"] is True
    assert relatorio["status"] == "ok"
    assert relatorio["dependencias"]["broker"]["observacao"] == "MESSAGERIA_ENABLED=false"


def test_verificar_broker_habilitado_e_fora_do_ar(db, settings, monkeypatch):
    settings.MESSAGERIA_ENABLED = True
    monkeypatch.setattr(
        health, "_verificar_broker", lambda: {"ok": False, "broker": "kafka"}
    )
    relatorio = health.verificar()
    assert relatorio["pronto"] is False
    assert relatorio["status"] == "degradado"
    assert "broker" in relatorio["fora_do_ar"]
