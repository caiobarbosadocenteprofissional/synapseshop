"""Inspeção e republicação nos brokers usados pelos smoke tests de mensageria.

Concentra o que é específico de broker (Kafka e RabbitMQ) para que o roteiro do
smoke test fique legível. Os nomes de tópicos, filas e credenciais vêm do mesmo
ambiente que a aplicação usa, com os padrões do Compose.
"""

import json
import os
from decimal import Decimal
from uuid import uuid4

from _comum import contar_mortas_dlq, management
from events.contracts import EventoPedidoCriado, ItemPedidoCriado

BROKER = os.environ.get("MENSAGERIA_BROKER", "kafka").strip().lower()

RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
EXCHANGE = os.environ.get("RABBITMQ_EXCHANGE", "pedidos.events")
ROUTING_KEY = os.environ.get("RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO", "pedido.criado")
FILA = "pedidos.pedidocriado"
DLQ = "pedidos.pedidocriado.dlq"

KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICO = os.environ.get("KAFKA_TOPICO_PEDIDO_CRIADO", "pedidos.pedidocriado")
TOPICO_DLQ = os.environ.get(
    "KAFKA_TOPICO_PEDIDO_CRIADO_DLQ", "pedidos.pedidocriado.dlq"
)
PARTICOES = int(os.environ.get("KAFKA_PARTICOES", "3"))


def kafka_produzir(topico, chave, evento):
    """Publica um evento no tópico e devolve a partição da entrega."""
    from confluent_kafka import Producer

    entrega = []
    erro = []

    def confirmado(falha, msg):
        if falha is not None:
            erro.append(falha.str())
            return
        entrega.append((msg.partition(), msg.offset()))

    produtor = Producer({"bootstrap.servers": KAFKA_SERVERS, "acks": "all"})
    produtor.produce(
        topic=topico,
        key=chave.encode("utf-8"),
        value=json.dumps(evento, ensure_ascii=False).encode("utf-8"),
        headers={"x-retry-count": "0", "event_type": evento.get("event_type", "")},
        on_delivery=confirmado,
    )
    pendentes = produtor.flush(15)
    if erro or pendentes or not entrega:
        print(f"  ..    publicacao no topico {topico} falhou: {erro or pendentes}")
        return None
    return entrega[0]


def kafka_ler_ultima(topico, tentativas=40, espera=0.5):
    """Lê (sem commit e sem mover o grupo) a última mensagem de um tópico.

    A posição de leitura é a *high watermark* da partição 0 menos 1: é o
    registro mais recente, que é o que a DLQ recebe do cenário de erro.
    """
    from confluent_kafka import Consumer, TopicPartition

    consumidor = Consumer(
        {
            "bootstrap.servers": KAFKA_SERVERS,
            "group.id": f"smoke-inspecao-{uuid4().hex[:8]}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    try:
        metadata = consumidor.list_topics(topico, timeout=15)
        if topico not in metadata.topics or metadata.topics[topico].error is not None:
            return None
        fim = consumidor.get_watermark_offsets(
            TopicPartition(topico, 0), timeout=10, cached=False
        )
        inicio = max(fim[1] - 1, 0)
        consumidor.assign([TopicPartition(topico, 0, inicio)])
        for _ in range(tentativas):
            msg = consumidor.poll(espera)
            if msg is None:
                continue
            if msg.error():
                return None
            corpo = json.loads(msg.value().decode("utf-8"))
            return {"payload": corpo, "headers": dict(msg.headers() or [])}
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    leitura do topico {topico} falhou: {exc}")
        return None
    finally:
        consumidor.close()


def kafka_particoes_de(chaves, evento_base):
    """Republica um evento **válido** sob cada chave e devolve sua partição.

    O corpo é o de um pedido real de propósito: uma sonda inválida seria
    rejeitada pelo worker, passaria pelas tentativas e acabaria na DLQ, poluindo
    justamente a verificação que vem depois. Com corpo válido e chave já
    registrada, a sonda é reconhecida como reentrega e não gera efeito nem
    mensagem morta.
    """
    resultado = {}
    for chave in chaves:
        evento = dict(evento_base)
        evento["idempotency_key"] = chave
        evento["event_id"] = str(uuid4())
        evento["correlation_id"] = str(uuid4())
        entrega = kafka_produzir(TOPICO, chave, evento)
        if entrega is None:
            return resultado
        resultado.setdefault(chave, []).append(entrega[0])
    return resultado


def mensagem_da_dlq():
    """Lê (sem consumir) a mensagem mais antiga da DLQ pela Management API."""
    url = f"{RABBITMQ_API}/api/queues/%2F/{DLQ}/get"
    corpo = {
        "count": 1,
        "ackmode": "ack_requeue_true",
        "encoding": "auto",
        "truncate": 50000,
    }
    try:
        mensagens = management(
            url,
            RABBITMQ_USER,
            RABBITMQ_PASSWORD,
            metodo="POST",
            dados=corpo,
        )
        if not mensagens:
            return None
        morta = mensagens[0]
        # A Management API devolve o payload como texto quando o encoding é auto.
        if isinstance(morta.get("payload"), str):
            morta["payload"] = json.loads(morta["payload"])
        return morta
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    leitura da DLQ falhou: {exc}")
        return None


def republicar_rabbitmq(evento):
    """Republica o evento na exchange de eventos via Management API.

    Simula a reentrega que o broker faria por crash do consumidor: usa o mesmo
    contrato publicado pela API e a mesma chave de deduplicação, para que o
    worker reconheça o efeito já aplicado.
    """
    url = f"{RABBITMQ_API}/api/exchanges/%2F/{EXCHANGE}/publish"
    corpo = {
        "properties": {
            "content_type": "application/json",
            "delivery_mode": 2,
            "correlation_id": evento.correlation_id,
        },
        "routing_key": ROUTING_KEY,
        "payload": json.dumps(evento.to_dict(), ensure_ascii=False),
        "payload_encoding": "string",
    }
    try:
        resposta = management(
            url,
            RABBITMQ_USER,
            RABBITMQ_PASSWORD,
            metodo="POST",
            dados=corpo,
        )
        return (resposta or {}).get("routed") is True
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    republicação falhou: {exc}")
        return False


def republicar(pedido_criado, pedido_lido):
    """Republica o evento no broker ativo. Devolve ``True`` se foi aceito.

    O evento e remontado a partir do estado já persistido, com a mesma
    ``idempotency_key`` da criação original: é assim que a reentrega se
    comportaria depois de um crash, e é o que o consumidor deve reconhecer.
    """
    evento = EventoPedidoCriado(
        idempotency_key=pedido_criado["idempotency_key"],
        pedido_id=pedido_criado["id"],
        usuario_id=pedido_criado["usuario"],
        total=Decimal(pedido_criado["total"]),
        status=pedido_criado["status"],
        itens=[
            ItemPedidoCriado(
                item_id=linha["item_id"],
                quantidade=linha["quantidade"],
                preco_unitario=Decimal(linha["preco_unitario"]),
            )
            for linha in (pedido_lido or pedido_criado).get("itens", [])
        ],
        correlation_id=str(uuid4()),
    )
    if BROKER == "kafka":
        return kafka_produzir(TOPICO, evento.idempotency_key, evento.to_dict()) is not None
    return republicar_rabbitmq(evento)


def contar_mortas():
    """Quantas mensagens estão na DLQ. No Kafka, o total do tópico."""
    return contar_mortas_dlq(
        BROKER,
        kafka_servers=KAFKA_SERVERS,
        topico=TOPICO_DLQ,
        fila=DLQ,
        rabbit_api=RABBITMQ_API,
        usuario=RABBITMQ_USER,
        senha=RABBITMQ_PASSWORD,
    )


def ler_morta():
    """Lê a mensagem morta mais recente, sem consumi-la do broker."""
    if BROKER == "kafka":
        morta = kafka_ler_ultima(TOPICO_DLQ)
        return (morta or {}).get("payload")
    return (mensagem_da_dlq() or {}).get("payload")
