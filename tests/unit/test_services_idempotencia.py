"""Testes da idempotência do consumidor (``services.idempotencia``)."""

from datetime import timedelta

import pytest
from django.core.cache import cache as django_cache
from django.utils import timezone

from repositories.models import EventoProcessado
from services import idempotencia

pytestmark = pytest.mark.unit


def test_chave_cache_tem_prefixo():
    assert (
        idempotencia._chave_cache("PedidoCriado", "k")
        == "evento:processado:PedidoCriado:k"
    )


def test_nao_processado_antes_de_registrar(db):
    assert idempotencia.ja_processado("PedidoCriado", "k1") is False


def test_registrar_e_consultar(db):
    assert idempotencia.registrar("PedidoCriado", "k1") is True
    assert idempotencia.ja_processado("PedidoCriado", "k1") is True


def test_registrar_duplicado_retorna_false(db):
    assert idempotencia.registrar("PedidoCriado", "k2") is True
    assert idempotencia.registrar("PedidoCriado", "k2") is False


def test_registro_grava_no_cache(db):
    idempotencia.registrar("PedidoCriado", "k3")
    assert django_cache.get(idempotencia._chave_cache("PedidoCriado", "k3")) is not None


def test_ja_processado_com_cache_indisponivel_cai_no_postgresql(db, monkeypatch):
    idempotencia.registrar("PedidoCriado", "k4")

    def explodir(*args, **kwargs):
        raise RuntimeError("cache fora")

    monkeypatch.setattr(django_cache, "get", explodir)
    assert idempotencia.ja_processado("PedidoCriado", "k4") is True


def test_registrar_com_cache_indisponivel_ainda_persiste(db, monkeypatch):
    def explodir(*args, **kwargs):
        raise RuntimeError("cache fora")

    monkeypatch.setattr(django_cache, "set", explodir)
    assert idempotencia.registrar("PedidoCriado", "k5") is True
    assert EventoProcessado.objects.filter(idempotency_key="k5").exists()


def test_limpar_expirados_remove_apenas_vencidos(db):
    EventoProcessado.objects.create(
        evento="E",
        idempotency_key="vencido",
        expira_em=timezone.now() - timedelta(days=1),
    )
    EventoProcessado.objects.create(
        evento="E",
        idempotency_key="vigente",
        expira_em=timezone.now() + timedelta(days=1),
    )

    assert idempotencia.limpar_expirados() == 1
    assert EventoProcessado.objects.filter(idempotency_key="vigente").exists()
