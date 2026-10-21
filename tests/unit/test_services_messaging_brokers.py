"""Testes dos dois transportes de broker, com broker de mentira.

Estes testes não medem a política de reentrega (ela mora em
``services/messaging_base.py`` e é testada lá) — medem o **protocolo**: como
cada transporte conecta, publica, confirma, mata e se recupera. É a parte que
só roda contra um broker real, e por isso precisa de um substituto fiel.
"""

import pytest
from confluent_kafka import KafkaError, KafkaException

from events.contracts import EVENTO_PEDIDO_CRIADO
from events.topology import topologia_de
from services.messaging_base import (
    HEADER_ERRO,
    HEADER_TENTATIVA,
    MensageriaIndisponivel,
    ResultadoPublicacao,
    serializar_evento,
)
from services.messaging_kafka import (
    ConsumidorEvento as ConsumidorKafka,
    ProdutorEvento as ProdutorKafka,
)
from services.messaging_kafka import publicacao as kafka_publicacao
from services.messaging_kafka import topicos as kafka_topicos
from services.messaging_kafka.observabilidade import (
    registrar_ociosidade,
    tempo_de_fila,
)
from services.messaging_rabbit import (
    ConsumidorEvento as ConsumidorAmqp,
    ProdutorEvento as ProdutorAmqp,
)
from services.messaging_rabbit import publicacao as rabbit_publicacao
from services.messaging_rabbit import topologia as rabbit_topologia

pytestmark = pytest.mark.unit


def _topologia():
    return topologia_de(EVENTO_PEDIDO_CRIADO)


def _evento():
    return {
        "event_type": "PedidoCriado",
        "event_id": "evt-1",
        "correlation_id": "corr-1",
        "idempotency_key": "pedido:1",
        "dados": {},
    }


# --------------------------------------------------------------------------- #
# Kafka: produtor de mentira
# --------------------------------------------------------------------------- #
class EntregaFake:
    def __init__(self, particao=2, offset=17):
        self._particao = particao
        self._offset = offset

    def partition(self):
        return self._particao

    def offset(self):
        return self._offset


class ProducerFake:
    """Produtor de mentira: registra o que foi produzido e o desfecho."""

    erro = None
    pendentes = 0
    instancias = []

    def __init__(self, config=None):
        self.config = config or {}
        self.produzidos = []
        self.flushes = []
        ProducerFake.instancias.append(self)

    def produce(self, topic, key=None, value=None, headers=None, on_delivery=None):
        self.produzidos.append(
            {"topic": topic, "key": key, "value": value, "headers": headers}
        )
        if ProducerFake.erro is not None:
            on_delivery(ProducerFake.erro, None)
            return
        on_delivery(None, EntregaFake())

    def flush(self, timeout=None):
        self.flushes.append(timeout)
        return ProducerFake.pendentes


@pytest.fixture
def producer_fake(monkeypatch):
    ProducerFake.erro = None
    ProducerFake.pendentes = 0
    ProducerFake.instancias = []
    monkeypatch.setattr(kafka_publicacao, "Producer", ProducerFake)
    monkeypatch.setattr(kafka_publicacao, "declarar_topologia", lambda: None)
    return ProducerFake


# --------------------------------------------------------------------------- #
# Kafka: consumidor de mentira
# --------------------------------------------------------------------------- #
class ParticaoFake:
    def __init__(self, particao=0):
        self.partition = particao


class ConsumerFake:
    def __init__(self, config=None, estado=None):
        self.config = config or {}
        self.estado = estado
        self.committed = []
        self.fechado = False
        self.topicos = []
        self.fila = []
        self.on_assign = None
        self.on_revoke = None

    def subscribe(self, topicos, on_assign=None, on_revoke=None):
        self.topicos = topicos
        self.on_assign = on_assign
        self.on_revoke = on_revoke

    def poll(self, timeout):
        if self.fila:
            return self.fila.pop(0)
        # Sem tráfego o consumidor fica ocioso; é a hora de encerrar o laço.
        if self.estado is not None and self.estado.get("consumidor") is not None:
            self.estado["consumidor"].parar()
        return None

    def commit(self, message=None, asynchronous=False):
        self.committed.append(message)

    def close(self):
        self.fechado = True

    def memberid(self):
        return "fake-member"


class MensagemKafkaFake:
    def __init__(self, valor=b"{}", headers=None, erro=None):
        self._valor = valor
        self._headers = headers or []
        self._erro = erro

    def value(self):
        return self._valor

    def headers(self):
        return self._headers

    def topic(self):
        return "pedidos.pedidocriado"

    def partition(self):
        return 1

    def offset(self):
        return 42

    def timestamp(self):
        return (0, 0)

    def error(self):
        return self._erro


@pytest.fixture
def consumer_fake(monkeypatch):
    estado = {"consumidor": None, "instancias": []}

    def fabrica(config):
        instancia = ConsumerFake(config, estado)
        estado["instancias"].append(instancia)
        return instancia

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    monkeypatch.setattr("services.messaging_kafka.consumidor.declarar_topologia", lambda: None)
    return estado


# --------------------------------------------------------------------------- #
# AMQP: canal e conexão de mentira
# --------------------------------------------------------------------------- #
class CanalAmqpFake:
    def __init__(self, publica_ok=True):
        self.publica_ok = publica_ok
        self.publicados = []
        self.acks = []
        self.nacks = []
        self.consumidos = []
        self.exchanges = []
        self.queues = []
        self.bindings = []
        self.qos = None
        self.confirmado = False
        self.is_open = True

    def confirm_delivery(self):
        self.confirmado = True

    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        self.publicados.append(
            {
                "exchange": exchange,
                "routing_key": routing_key,
                "body": body,
                "properties": properties,
                "mandatory": mandatory,
            }
        )
        return self.publica_ok

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=False):
        self.nacks.append({"delivery_tag": delivery_tag, "requeue": requeue})

    def basic_consume(self, queue, on_message_callback, auto_ack=False):
        self.consumidos.append({"queue": queue, "auto_ack": auto_ack})

    def exchange_declare(self, exchange, exchange_type=None, durable=None):
        self.exchanges.append(
            {"exchange": exchange, "tipo": exchange_type, "durable": durable}
        )

    def queue_declare(self, queue, durable=None, arguments=None):
        self.queues.append({"queue": queue, "durable": durable, "arguments": arguments})

    def queue_bind(self, exchange, queue, routing_key):
        self.bindings.append(
            {"exchange": exchange, "queue": queue, "routing_key": routing_key}
        )

    def basic_qos(self, prefetch_count=None):
        self.qos = prefetch_count

    def close(self):
        self.is_open = False


class ConexaoAmqpFake:
    def __init__(self, estado=None):
        self.estado = estado
        self.canais = []
        self.fechada = False

    @property
    def is_open(self):
        return not self.fechada

    def channel(self):
        canal = CanalAmqpFake()
        self.canais.append(canal)
        return canal

    def process_data_events(self, time_limit=None):
        if self.estado is not None and self.estado.get("consumidor") is not None:
            self.estado["consumidor"].parar()

    def close(self):
        self.fechada = True


# --------------------------------------------------------------------------- #
# Kafka: produtor
# --------------------------------------------------------------------------- #
def test_produtor_kafka_publica_e_normaliza_o_desfecho(producer_fake):
    with ProdutorKafka(_topologia()) as produtor:
        resultado = produtor.publicar(_evento(), "pedido:1")

    assert isinstance(resultado, ResultadoPublicacao)
    assert resultado.confirmado is True
    assert resultado.particao == 2
    assert resultado.offset == 17
    assert resultado.identificador == "2:17"

    registro = producer_fake.instancias[0].produzidos[0]
    assert registro["topic"] == _topologia().topico
    assert registro["key"] == b"pedido:1"
    assert registro["headers"]["x-retry-count"] == "0"


def test_produtor_kafka_conecta_com_ack_de_configuracao(producer_fake):
    produtor = ProdutorKafka(_topologia(), client_id="api-1")
    produtor.conectar()
    config = producer_fake.instancias[0].config
    assert config["client.id"] == "api-1"
    assert config["acks"] == "all"
    produtor.fechar()


def test_produtor_kafka_recusa_publicacao_nao_confirmada(producer_fake):
    ProducerFake.pendentes = 3
    with ProdutorKafka(_topologia()) as produtor:
        with pytest.raises(MensageriaIndisponivel):
            produtor.publicar(_evento(), "pedido:1")


def test_produtor_kafka_recusa_publicacao_com_erro_do_broker(producer_fake):
    ProducerFake.erro = KafkaError(KafkaError.TOPIC_ALREADY_EXISTS)
    with ProdutorKafka(_topologia()) as produtor:
        with pytest.raises(MensageriaIndisponivel):
            produtor.publicar(_evento(), "pedido:1")


def test_produtor_kafka_trata_falha_de_conexao(monkeypatch, producer_fake):
    def fabrica(config):
        raise RuntimeError("broker fora do ar")

    monkeypatch.setattr(kafka_publicacao, "Producer", fabrica)
    with pytest.raises(MensageriaIndisponivel):
        ProdutorKafka(_topologia()).conectar()


def test_produtor_kafka_expoe_a_topologia(producer_fake):
    produtor = ProdutorKafka(_topologia())
    assert produtor.topico == _topologia().topico
    assert produtor.topologia == _topologia()


def test_produtor_kafka_fecha_sem_erro(producer_fake, monkeypatch):
    produtor = ProdutorKafka(_topologia())
    produtor.conectar()

    def flush(_timeout=None):
        raise RuntimeError("broker fora do ar")

    produtor._produtor.flush = flush
    produtor.fechar()
    assert produtor._produtor is None


def test_publicar_retencao_aceita_corpo_em_texto(producer_fake):
    entrega = kafka_publicacao.publicar_retencao(
        corpo='{"idempotency_key": "pedido:1"}',
        chave="pedido:1",
        cabecalhos={},
        client_id="worker",
        destino="pedidos.pedidocriado",
    )
    assert entrega == (2, 17)
    assert producer_fake.instancias[0].produzidos[0]["value"] == b'{"idempotency_key": "pedido:1"}'


def test_produtor_kafka_trata_fila_cheia(producer_fake, monkeypatch):
    def produce(_self, **_kwargs):
        raise BufferError("cheio")

    monkeypatch.setattr(ProducerFake, "produce", produce)
    with ProdutorKafka(_topologia()) as produtor:
        with pytest.raises(MensageriaIndisponivel) as erro:
            produtor.publicar(_evento(), "pedido:1")
    assert "fila de envio" in str(erro.value)


# --------------------------------------------------------------------------- #
# Kafka: republicação (reentrega e DLQ)
# --------------------------------------------------------------------------- #
def test_publicar_retencao_preserva_o_corpo_e_a_chave(producer_fake):
    corpo = b'{"idempotency_key": "pedido:1"}'
    entrega = kafka_publicacao.publicar_retencao(
        corpo=corpo,
        chave="pedido:1",
        cabecalhos={HEADER_TENTATIVA: 1, HEADER_ERRO: "boom"},
        client_id="worker",
        destino="pedidos.pedidocriado",
    )
    assert entrega == (2, 17)
    registro = producer_fake.instancias[0].produzidos[0]
    assert registro["value"] == corpo
    assert registro["key"] == b"pedido:1"
    assert registro["headers"]["x-retry-count"] == "1"


def test_publicar_retencao_gera_chave_quando_nao_ha(producer_fake):
    kafka_publicacao.publicar_retencao(
        corpo=b"{}",
        chave=None,
        cabecalhos={},
        client_id="worker",
        destino="pedidos.pedidocriado",
    )
    registro = producer_fake.instancias[0].produzidos[0]
    assert registro["key"]


def test_publicar_retencao_devolve_none_quando_o_broker_falha(producer_fake):
    ProducerFake.erro = KafkaError(KafkaError.TOPIC_ALREADY_EXISTS)
    assert (
        kafka_publicacao.publicar_retencao(
            corpo=b"{}",
            chave="pedido:1",
            cabecalhos={},
            client_id="worker",
            destino="pedidos.pedidocriado",
        )
        is None
    )


def test_publicar_retencao_devolve_none_quando_a_producao_explode(producer_fake, monkeypatch):
    def produce(_self, **_kwargs):
        raise RuntimeError("broker fora do ar")

    monkeypatch.setattr(ProducerFake, "produce", produce)
    assert (
        kafka_publicacao.publicar_retencao(
            corpo=b"{}",
            chave="pedido:1",
            cabecalhos={},
            client_id="worker",
            destino="pedidos.pedidocriado",
        )
        is None
    )


def test_publicar_retencao_substitui_corpo_que_nao_e_reenviavel(producer_fake):
    kafka_publicacao.publicar_retencao(
        corpo=None,
        chave=None,
        cabecalhos={},
        client_id="worker",
        destino="pedidos.pedidocriado",
    )
    registro = producer_fake.instancias[0].produzidos[0]
    assert b"sem corpo reenvi" in registro["value"]


# --------------------------------------------------------------------------- #
# Kafka: topologia
# --------------------------------------------------------------------------- #
class FuturoFake:
    def __init__(self, erro=None):
        self._erro = erro

    def result(self):
        if self._erro is not None:
            raise self._erro


class AdminClientFake:
    erro = None
    instancias = []

    def __init__(self, config=None):
        self.config = config or {}
        self.criados = []
        AdminClientFake.instancias.append(self)

    def create_topics(self, topicos, request_timeout=15):
        self.criados = list(topicos)
        return {topico.topic: FuturoFake(AdminClientFake.erro) for topico in topicos}


def test_declarar_topologia_kafka_cria_o_par_de_topicos(monkeypatch, settings):
    AdminClientFake.erro = None
    monkeypatch.setattr(kafka_topicos, "AdminClient", AdminClientFake)
    kafka_topicos.declarar_topologia()

    nomes = {topico.topic for topico in AdminClientFake.instancias[0].criados}
    assert _topologia().topico in nomes
    assert _topologia().dlq in nomes


def test_declarar_topologia_kafka_ignora_topico_que_ja_existe(monkeypatch):
    AdminClientFake.erro = KafkaException(
        KafkaError(KafkaError.TOPIC_ALREADY_EXISTS)
    )
    monkeypatch.setattr(kafka_topicos, "AdminClient", AdminClientFake)
    kafka_topicos.declarar_topologia()


def test_declarar_topologia_kafka_propaga_falha_real(monkeypatch):
    AdminClientFake.erro = KafkaException(KafkaError(KafkaError._TIMED_OUT))
    monkeypatch.setattr(kafka_topicos, "AdminClient", AdminClientFake)
    with pytest.raises(MensageriaIndisponivel):
        kafka_topicos.declarar_topologia()


def test_erro_do_broker_extrai_o_nome_da_falha():
    erro = KafkaException(KafkaError(KafkaError._TIMED_OUT))
    assert "TIMED_OUT" in kafka_topicos._erro_do_broker(erro)


# --------------------------------------------------------------------------- #
# Kafka: consumidor
# --------------------------------------------------------------------------- #
def test_consumidor_kafka_consome_e_encerra(consumer_fake):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor
    consumidor.executar()

    instancia = consumer_fake["instancias"][0]
    assert instancia.topicos == [_topologia().topico]
    assert instancia.fechado is True
    assert instancia.config["enable.auto.commit"] is False


def test_consumidor_kafka_trata_falha_do_broker_e_reconecta(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor
    chamadas = {"n": 0}

    def fabrica(config):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("broker fora do ar")
        return ConsumerFake(config, consumer_fake)

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    monkeypatch.setattr("services.messaging_kafka.consumidor.time.sleep", lambda _s: None)
    consumidor.executar()
    assert chamadas["n"] >= 2


def test_consumidor_kafka_ignora_fim_de_particao(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor
    consumer_fake["instancias"] = []

    def fabrica(config):
        instancia = ConsumerFake(config, consumer_fake)
        instancia.fila.append(MensagemKafkaFake(erro=KafkaError(KafkaError._PARTITION_EOF)))
        return instancia

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    consumidor.executar()


def test_consumidor_kafka_registra_rebalanceamento(consumer_fake):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumidor._ao_atribuir(ConsumerFake(), [ParticaoFake(0), ParticaoFake(1)])
    assert consumidor.particoes == [0, 1]
    consumidor._ao_revogar(ConsumerFake(), [ParticaoFake(1)])
    assert consumidor.particoes == []


def test_consumidor_kafka_registra_falha_de_commit(consumer_fake):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    instancia = ConsumerFake()
    instancia.commit = lambda message=None, asynchronous=False: (_ for _ in ()).throw(
        RuntimeError("commit falhou")
    )
    consumidor._consumidor = instancia
    consumidor._confirma(MensagemKafkaFake(), "ok")


def test_consumidor_kafka_processa_a_mensagem_entregue(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor
    recebidos = []

    def fabrica(config):
        instancia = ConsumerFake(config, consumer_fake)
        instancia.fila.append(
            MensagemKafkaFake(serializar_evento(_evento()), [(HEADER_TENTATIVA, "0")])
        )
        return instancia

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    consumidor._handler = lambda evento, tentativa: recebidos.append(evento)
    consumidor.executar()
    assert recebidos[0]["idempotency_key"] == "pedido:1"


def test_consumidor_kafka_propaga_erro_do_broker(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor
    chamadas = {"n": 0}

    def fabrica(config):
        chamadas["n"] += 1
        instancia = ConsumerFake(config, consumer_fake)
        if chamadas["n"] == 1:
            instancia.fila.append(MensagemKafkaFake(erro=KafkaError(KafkaError._TRANSPORT)))
        return instancia

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    monkeypatch.setattr("services.messaging_kafka.consumidor.time.sleep", lambda _s: None)
    consumidor.executar()
    assert chamadas["n"] >= 2


def test_consumidor_kafka_trata_interrupcao(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor

    def fabrica(config):
        raise KeyboardInterrupt

    monkeypatch.setattr("services.messaging_kafka.consumidor.Consumer", fabrica)
    consumidor.executar()


def test_consumidor_kafka_ignora_falha_no_encerramento(consumer_fake, monkeypatch):
    consumidor = ConsumidorKafka(lambda evento, tentativa: None, _topologia())
    consumer_fake["consumidor"] = consumidor

    class ConsumidorQuebrado(ConsumerFake):
        def close(self):
            raise RuntimeError("ja fechado")

    monkeypatch.setattr(
        "services.messaging_kafka.consumidor.Consumer", lambda config: ConsumidorQuebrado(config, consumer_fake)
    )
    consumidor.executar()


# --------------------------------------------------------------------------- #
# AMQP: produtor
# --------------------------------------------------------------------------- #
@pytest.fixture
def conexao_amqp_fake(monkeypatch):
    estado = {"consumidor": None, "instancias": []}

    def fabrica(client_id=""):
        instancia = ConexaoAmqpFake(estado)
        instancia.client_id = client_id
        estado["instancias"].append(instancia)
        return instancia

    monkeypatch.setattr(rabbit_publicacao, "conexao", fabrica)
    monkeypatch.setattr(rabbit_publicacao, "declarar_topologia", lambda canal: None)
    return estado


def test_produtor_amqp_publica_e_normaliza_o_desfecho(conexao_amqp_fake):
    with ProdutorAmqp(_topologia()) as produtor:
        resultado = produtor.publicar(_evento(), "pedido:1")

    assert isinstance(resultado, ResultadoPublicacao)
    assert resultado.confirmado is True
    assert resultado.identificador == "corr-1"

    publicado = conexao_amqp_fake["instancias"][0].canais[0].publicados[0]
    assert publicado["routing_key"] == _topologia().routing_key
    assert publicado["mandatory"] is True
    assert publicado["properties"].delivery_mode == 2
    assert publicado["properties"].headers[HEADER_TENTATIVA] == 0


def test_produtor_amqp_recusa_publicacao_nao_confirmada(conexao_amqp_fake, monkeypatch):
    monkeypatch.setattr(rabbit_publicacao, "declarar_topologia", lambda canal: None)
    produtor = ProdutorAmqp(_topologia())
    produtor.conectar()
    produtor._canal.publica_ok = False
    with pytest.raises(MensageriaIndisponivel):
        produtor.publicar(_evento(), "pedido:1")


def test_produtor_amqp_trata_falha_de_conexao(monkeypatch):
    def fabrica(client_id=""):
        raise RuntimeError("broker fora do ar")

    monkeypatch.setattr(rabbit_publicacao, "conexao", fabrica)
    with pytest.raises(MensageriaIndisponivel):
        ProdutorAmqp(_topologia()).conectar()


# --------------------------------------------------------------------------- #
# AMQP: consumidor
# --------------------------------------------------------------------------- #
@pytest.fixture
def conexao_amqp_consumidor(monkeypatch):
    estado = {"consumidor": None, "instancias": []}

    def fabrica(client_id=""):
        instancia = ConexaoAmqpFake(estado)
        instancia.client_id = client_id
        estado["instancias"].append(instancia)
        return instancia

    monkeypatch.setattr("services.messaging_rabbit.consumidor.conexao", fabrica)
    monkeypatch.setattr(
        "services.messaging_rabbit.consumidor.declarar_topologia", lambda canal: None
    )
    return estado


def test_consumidor_amqp_consome_e_encerra(conexao_amqp_consumidor):
    consumidor = ConsumidorAmqp(lambda evento, tentativa: None, _topologia())
    conexao_amqp_consumidor["consumidor"] = consumidor
    consumidor.executar()

    canal = conexao_amqp_consumidor["instancias"][0].canais[0]
    assert canal.consumidos[0]["queue"] == _topologia().fila
    assert canal.consumidos[0]["auto_ack"] is False


def test_consumidor_amqp_trata_falha_do_broker(conexao_amqp_consumidor, monkeypatch):
    consumidor = ConsumidorAmqp(lambda evento, tentativa: None, _topologia())
    conexao_amqp_consumidor["consumidor"] = consumidor
    chamadas = {"n": 0}

    def fabrica(client_id=""):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("broker fora do ar")
        return ConexaoAmqpFake(conexao_amqp_consumidor)

    monkeypatch.setattr("services.messaging_rabbit.consumidor.conexao", fabrica)
    monkeypatch.setattr("services.messaging_rabbit.consumidor.time.sleep", lambda _s: None)
    consumidor.executar()
    assert chamadas["n"] >= 2


def test_consumidor_amqp_expoe_a_topologia(conexao_amqp_consumidor):
    consumidor = ConsumidorAmqp(lambda evento, tentativa: None, _topologia())
    assert consumidor.topologia == _topologia()


def test_produtor_amqp_expoe_a_topologia(conexao_amqp_fake):
    produtor = ProdutorAmqp(_topologia())
    assert produtor.topologia == _topologia()


def test_produtor_amqp_converte_falha_de_publicacao(conexao_amqp_fake):
    produtor = ProdutorAmqp(_topologia())
    produtor.conectar()

    def publica(**_kwargs):
        raise RuntimeError("canal fechado")

    produtor._canal.basic_publish = publica
    with pytest.raises(MensageriaIndisponivel):
        produtor.publicar(_evento(), "pedido:1")


def test_consumidor_amqp_trata_interrupcao(conexao_amqp_consumidor, monkeypatch):
    consumidor = ConsumidorAmqp(lambda evento, tentativa: None, _topologia())
    conexao_amqp_consumidor["consumidor"] = consumidor

    def fabrica(client_id=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("services.messaging_rabbit.consumidor.conexao", fabrica)
    consumidor.executar()


# --------------------------------------------------------------------------- #
# AMQP: topologia
# --------------------------------------------------------------------------- #
def test_declarar_topologia_amqp_declara_filas_e_dlq(settings):
    canal = CanalAmqpFake()
    rabbit_topologia.declarar_topologia(canal)

    assert canal.exchanges[0]["exchange"] == settings.RABBITMQ_EXCHANGE
    assert canal.exchanges[1]["exchange"] == settings.RABBITMQ_DLX
    assert settings.RABBITMQ_FILA_PEDIDO_CRIADO in [q["queue"] for q in canal.queues]
    assert canal.qos == settings.RABBITMQ_PREFETCH
    principal = [q for q in canal.queues if q["queue"] == settings.RABBITMQ_FILA_PEDIDO_CRIADO][0]
    assert principal["arguments"]["x-dead-letter-exchange"] == settings.RABBITMQ_DLX


def test_conexao_amqp_monta_os_parametros(monkeypatch, settings):
    capturados = {}

    class ParametrosFake:
        def __init__(self, **kwargs):
            capturados.update(kwargs)

    class ConexaoFake:
        def __init__(self, parametros):
            capturados["parametros"] = parametros

    monkeypatch.setattr(rabbit_topologia.pika, "ConnectionParameters", ParametrosFake)
    monkeypatch.setattr(rabbit_topologia.pika, "BlockingConnection", ConexaoFake)
    rabbit_topologia.conexao("worker-1")

    assert capturados["host"] == settings.RABBITMQ_HOST
    assert capturados["client_properties"] == {"connection_name": "worker-1"}


def test_fechar_recursos_ignora_o_que_ja_fechou():
    canal = CanalAmqpFake()
    canal.is_open = False
    conexao = ConexaoAmqpFake()
    conexao.fechada = True
    rabbit_topologia.fechar_recursos(canal, conexao)
    assert canal.is_open is False


def test_fechar_recursos_ignora_excecao():
    class RecursoQuebrado:
        is_open = True

        def close(self):
            raise RuntimeError("ja fechado")

    rabbit_topologia.fechar_recursos(RecursoQuebrado(), None)


# --------------------------------------------------------------------------- #
# Kafka: observabilidade
# --------------------------------------------------------------------------- #
def test_tempo_de_fila_calcula_a_espera():
    class Mensagem:
        def timestamp(self):
            return (0, 1_000_000)

    assert tempo_de_fila(Mensagem()) is not None


def test_tempo_de_fila_ignora_marca_invalida():
    class Mensagem:
        def timestamp(self):
            return (0, -1)

    assert tempo_de_fila(Mensagem()) is None


def test_tempo_de_fila_ignora_mensagem_sem_timestamp():
    class Mensagem:
        def timestamp(self):
            raise RuntimeError("sem timestamp")

    assert tempo_de_fila(Mensagem()) is None


def test_registrar_ociosidade_nao_loga_antes_do_limite(settings, monkeypatch):
    settings.MENSAGERIA_HEARTBEAT_S = 60
    import time as _tempo

    agora = _tempo.monotonic()
    assert registrar_ociosidade(
        topologia=_topologia(),
        client_id="worker",
        particoes=[0],
        ultimo_evento=agora,
    ) == agora


def test_registrar_ociosidade_registra_o_silencio(settings):
    settings.MENSAGERIA_HEARTBEAT_S = 1
    import time as _tempo

    antes = _tempo.monotonic()
    depois = registrar_ociosidade(
        topologia=_topologia(),
        client_id="worker",
        particoes=[0],
        ultimo_evento=antes - 10,
    )
    assert depois >= antes


def test_registrar_ociosidade_devolve_o_instante_do_silencio(settings, monkeypatch):
    settings.MENSAGERIA_HEARTBEAT_S = 1
    instantes = iter([100.0, 160.0])
    monkeypatch.setattr(
        "services.messaging_kafka.observabilidade.time.monotonic",
        lambda: next(instantes),
    )
    assert (
        registrar_ociosidade(
            topologia=_topologia(),
            client_id="worker",
            particoes=[0],
            ultimo_evento=90.0,
        )
        == 160.0
    )
