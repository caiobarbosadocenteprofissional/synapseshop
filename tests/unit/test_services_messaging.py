"""Testes da fachada de transporte (``services.messaging``).

A escolha do broker é **preguiçosa**: acontece na chamada, e não no import. Por
isso o teste troca ``MENSAGERIA_BROKER`` e pede o produtor — sem recarregar o
módulo, que era o que a versão anterior exigia.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from events.contracts import EVENTO_PEDIDO_CRIADO
from config.topologias import topologia_de
from services import messaging
from services.messaging_kafka import ConsumidorEvento as ConsumidorKafka
from services.messaging_kafka import ProdutorEvento as ProdutorKafka
from services.messaging_rabbit import ConsumidorEvento as ConsumidorAmqp
from services.messaging_rabbit import ProdutorEvento as ProdutorAmqp

pytestmark = pytest.mark.unit


def _topologia():
    return topologia_de(EVENTO_PEDIDO_CRIADO)


def _nao_faz_nada(evento, tentativa):
    return None


def test_fachada_padrao_escolhe_kafka(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    produtor = messaging.produtor_evento(_topologia())
    assert isinstance(produtor, ProdutorKafka)


def test_fachada_escolhe_rabbitmq(settings):
    settings.MENSAGERIA_BROKER = "rabbitmq"
    produtor = messaging.produtor_evento(_topologia())
    assert isinstance(produtor, ProdutorAmqp)


def test_fachada_rejeita_broker_desconhecido(settings):
    settings.MENSAGERIA_BROKER = "oracle"
    with pytest.raises(ImproperlyConfigured):
        messaging.produtor_evento(_topologia())


def test_consumidor_escolhe_o_broker_ativo(settings):
    settings.MENSAGERIA_BROKER = "rabbitmq"
    consumidor = messaging.consumidor_evento(_nao_faz_nada, _topologia())
    assert isinstance(consumidor, ConsumidorAmqp)


def test_consumidor_escolhe_kafka(settings):
    settings.MENSAGERIA_BROKER = "kafka"
    consumidor = messaging.consumidor_evento(_nao_faz_nada, _topologia())
    assert isinstance(consumidor, ConsumidorKafka)


def test_escolha_acompanha_a_configuracao_do_momento(settings):
    """A escolha não é congelada no import: ela segue a configuração atual."""
    settings.MENSAGERIA_BROKER = "kafka"
    assert isinstance(messaging.produtor_evento(_topologia()), ProdutorKafka)
    settings.MENSAGERIA_BROKER = "rabbitmq"
    assert isinstance(messaging.produtor_evento(_topologia()), ProdutorAmqp)


def test_mensageria_indisponivel_vem_da_base():
    from services.messaging_base import MensageriaIndisponivel as DaBase

    assert messaging.MensageriaIndisponivel is DaBase
