"""Testes de paridade entre os dois transportes (RabbitMQ e Kafka).

Os dois transportes implementam o mesmo contrato de domínio e a mesma política
de reentrega. O que muda é o protocolo — *ack* contra *commit*, *nack* contra
publicação na DLQ. Estes testes exercitam os dois com broker de mentira e
verificam o **mesmo desfecho observável**, que é o que garante que trocar de
broker não muda o comportamento da aplicação.

O desfecho observado é o mesmo para os dois:

- **liquidada** — a entrega original foi acertada (ack no AMQP, commit no Kafka);
- **reenfileirada** — a entrega original voltou para o broker, sem ser acertada;
- **republicada** — a mensagem foi reentregue com o contador de tentativa;
- **morta** — a mensagem foi encaminhada para a DLQ.
"""

import pytest

from events.contracts import EVENTO_PEDIDO_CRIADO
from events.topology import topologia_de
from services.messaging_base import HEADER_ERRO, HEADER_TENTATIVA, serializar_evento
from services.messaging_kafka.consumidor import ConsumidorEvento as ConsumidorKafka
from services.messaging_rabbit.consumidor import ConsumidorEvento as ConsumidorAmqp

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Broker de mentira
# --------------------------------------------------------------------------- #
class MetodoFake:
    delivery_tag = 7


class PropriedadesFake:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.correlation_id = "corr-1"
        self.message_id = "msg-1"


class CanalFake:
    def __init__(self, publica_ok=True):
        self.publica_ok = publica_ok
        self.publicados = []
        self.acks = []
        self.nacks = []

    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        self.publicados.append(
            {
                "destino": routing_key,
                "corpo": body,
                "cabecalhos": dict(getattr(properties, "headers", None) or {}),
            }
        )
        return self.publica_ok

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=False):
        self.nacks.append({"delivery_tag": delivery_tag, "requeue": requeue})


class ConsumidorFake:
    def __init__(self):
        self.commits = []

    def commit(self, message=None, asynchronous=False):
        self.commits.append(message)


class MensagemFake:
    def __init__(self, valor, headers=None):
        self._valor = valor
        self._headers = headers or []

    def value(self):
        return self._valor

    def headers(self):
        return self._headers

    def topic(self):
        return "pedidos.pedidocriado"

    def partition(self):
        return 0

    def offset(self):
        return 12

    def timestamp(self):
        return (0, 0)


# --------------------------------------------------------------------------- #
# As duas linguagens, com a mesma interface
# --------------------------------------------------------------------------- #
class DriverAmqp:
    def __init__(self, handler, publica_ok=True):
        self.canal = CanalFake(publica_ok)
        self.consumidor = ConsumidorAmqp(
            handler, topologia_de(EVENTO_PEDIDO_CRIADO), client_id="teste"
        )

    def entregar(self, corpo, headers=None):
        self.consumidor._ao_receber(
            self.canal, MetodoFake(), PropriedadesFake(headers), corpo
        )

    @property
    def liquidada(self):
        acks = len(self.canal.acks)
        nacks = len([n for n in self.canal.nacks if not n["requeue"]])
        return acks + nacks

    @property
    def reenfileirada(self):
        return len([n for n in self.canal.nacks if n["requeue"]])

    @property
    def republicados(self):
        return self.canal.publicados

    @property
    def mortos(self):
        return [n for n in self.canal.nacks if not n["requeue"]]


class DriverKafka:
    def __init__(self, handler, republicacoes):
        self.consumidor = ConsumidorKafka(
            handler, topologia_de(EVENTO_PEDIDO_CRIADO), client_id="teste"
        )
        self.consumidor._consumidor = ConsumidorFake()
        self._republicacoes = republicacoes

    def entregar(self, corpo, headers=None):
        self.consumidor._ao_receber(MensagemFake(corpo, headers))

    @property
    def liquidada(self):
        return len(self.consumidor._consumidor.commits)

    @property
    def reenfileirada(self):
        return 0 if self.liquidada else 1

    @property
    def republicados(self):
        topico = self.consumidor.topologia.topico
        return [p for p in self._republicacoes["publicacoes"] if p["destino"] == topico]

    @property
    def mortos(self):
        dlq = self.consumidor.topologia.dlq
        return [p for p in self._republicacoes["publicacoes"] if p["destino"] == dlq]


@pytest.fixture
def republicacoes(monkeypatch):
    """Registra as republicações do Kafka e decide se o broker confirma."""
    registro = {"publicacoes": [], "confirma": True}

    def fake_publicar_retencao(*, corpo, chave, cabecalhos, client_id, destino):
        registro["publicacoes"].append(
            {
                "corpo": corpo,
                "chave": chave,
                "cabecalhos": dict(cabecalhos or {}),
                "destino": destino,
            }
        )
        return (0, 1) if registro["confirma"] else None

    monkeypatch.setattr(
        "services.messaging_kafka.consumidor.publicar_retencao", fake_publicar_retencao
    )
    return registro


@pytest.fixture(params=["rabbitmq", "kafka"])
def criar_driver(request, republicacoes, settings):
    """Fábrica de driver, uma instância por broker."""
    settings.MENSAGERIA_BACKOFF_BASE_MS = 0
    settings.MENSAGERIA_BACKOFF_MAX_MS = 0

    def criar(handler, publica_ok=True):
        if request.param == "rabbitmq":
            return DriverAmqp(handler, publica_ok=publica_ok)
        republicacoes["confirma"] = publica_ok
        return DriverKafka(handler, republicacoes)

    return criar


def _corpo():
    return serializar_evento({"idempotency_key": "pedido:1", "event_type": "PedidoCriado"})


def _falha(evento, tentativa):
    raise RuntimeError("boom")


# --------------------------------------------------------------------------- #
# O mesmo desfecho nos dois brokers
# --------------------------------------------------------------------------- #
def test_sucesso_liquidada_a_original(criar_driver):
    driver = criar_driver(lambda evento, tentativa: None)
    driver.entregar(_corpo())

    assert driver.liquidada == 1
    assert driver.reenfileirada == 0
    assert driver.republicados == []
    assert driver.mortos == []


def test_falha_reentrega_e_liquidada(criar_driver):
    driver = criar_driver(_falha)
    driver.entregar(_corpo(), headers=[(HEADER_TENTATIVA, "0")])

    assert driver.liquidada == 1
    assert driver.reenfileirada == 0
    assert len(driver.republicados) == 1
    cabecalhos = driver.republicados[0]["cabecalhos"]
    assert cabecalhos[HEADER_TENTATIVA] == 1
    assert cabecalhos[HEADER_ERRO] == "boom"
    assert driver.mortos == []


def test_republicacao_nao_confirmada_deixa_a_original_no_broker(criar_driver):
    driver = criar_driver(_falha, publica_ok=False)
    driver.entregar(_corpo())

    assert driver.liquidada == 0
    assert driver.reenfileirada == 1
    assert driver.mortos == []


def test_tentativas_esgotadas_matem_para_a_dlq(criar_driver, settings):
    settings.MENSAGERIA_MAX_RETRIES = 3
    driver = criar_driver(_falha)
    driver.entregar(_corpo(), headers=[(HEADER_TENTATIVA, "3")])

    assert driver.liquidada == 1
    assert driver.reenfileirada == 0
    assert driver.republicados == []
    assert len(driver.mortos) == 1


def test_corpo_invalido_vai_direto_para_a_dlq(criar_driver):
    driver = criar_driver(lambda evento, tentativa: None)
    driver.entregar(b"{isto nao e json")

    assert len(driver.mortos) == 1
    assert driver.republicados == []


def test_o_corpo_original_viaja_inteiro_para_a_dlq(criar_driver):
    """A DLQ é a evidência da falha: o corpo tem de chegar como veio."""
    driver = criar_driver(_falha)
    corpo = _corpo()
    driver.entregar(corpo, headers=[(HEADER_TENTATIVA, "3")])

    if driver.mortos and isinstance(driver.mortos[0], dict) and "corpo" in driver.mortos[0]:
        assert driver.mortos[0]["corpo"] == corpo
    else:
        # No AMQP o broker leva o corpo original: o nack não republica nada.
        assert driver.mortos


def test_dlq_nao_confirmada_deixa_a_original_no_broker(republicacoes, settings):
    """Caminho exclusivo do Kafka: o AMQP tem *dead-letter exchange* nativa.

    No AMQP quem encaminha para a DLQ é o broker, no nack — não há publicação
    que possa falhar. No Kafka a publicação na DLQ é da aplicação, e uma falha
    dela não pode virar perda: o offset não é commitado.
    """
    settings.MENSAGERIA_BACKOFF_BASE_MS = 0
    settings.MENSAGERIA_BACKOFF_MAX_MS = 0
    settings.MENSAGERIA_MAX_RETRIES = 3
    republicacoes["confirma"] = False
    driver = DriverKafka(_falha, republicacoes)
    driver.entregar(_corpo(), headers=[(HEADER_TENTATIVA, "3")])

    assert driver.liquidada == 0
    assert driver.reenfileirada == 1
