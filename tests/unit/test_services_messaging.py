"""Testes da fachada de transporte (``services.messaging``).

A escolha do broker acontece no import. Para exercitar os outros ramos sem
subir um broker de verdade, recarregamos o módulo com ``MENSAGERIA_BROKER``
alterado e, ao final, restauramos o transporte padrão (kafka).
"""

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

from services import messaging

pytestmark = pytest.mark.unit


def test_fachada_padrao_carrega_kafka():
    assert messaging.ProdutorEvento.__module__ == "services.messaging_kafka"


def test_fachada_carrega_transporte_rabbitmq(settings, monkeypatch):
    monkeypatch.setattr(settings, "MENSAGERIA_BROKER", "rabbitmq")
    importlib.reload(messaging)
    try:
        assert messaging.ProdutorEvento.__module__ == "services.messaging_rabbit"
    finally:
        monkeypatch.undo()
        importlib.reload(messaging)
        assert messaging.ProdutorEvento.__module__ == "services.messaging_kafka"


def test_fachada_rejeita_broker_desconhecido(settings, monkeypatch):
    monkeypatch.setattr(settings, "MENSAGERIA_BROKER", "oracle")
    try:
        with pytest.raises(ImproperlyConfigured):
            importlib.reload(messaging)
    finally:
        monkeypatch.undo()
        importlib.reload(messaging)