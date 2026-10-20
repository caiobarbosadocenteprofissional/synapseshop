"""Esperas e consultas do smoke test do fluxo criar ➔ pagar ➔ notificar."""

import os

from _comum import aguardar, contar_mortas_dlq, pedir

RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
FILA_DLQ = os.environ.get(
    "RABBITMQ_FILA_PAGAMENTO_PROCESSADO_DLQ", "pagamentos.pagamentoprocessado.dlq"
)
KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICO_DLQ = os.environ.get(
    "KAFKA_TOPICO_PAGAMENTO_PROCESSADO_DLQ", "pagamentos.pagamentoprocessado.dlq"
)


def contar_mortas(broker):
    """Quantas mensagens estão na DLQ de ``PagamentoProcessado``."""
    return contar_mortas_dlq(
        broker,
        kafka_servers=KAFKA_SERVERS,
        topico=TOPICO_DLQ,
        fila=FILA_DLQ,
        rabbit_api=RABBITMQ_API,
        usuario=RABBITMQ_USER,
        senha=RABBITMQ_PASSWORD,
        grupo="smoke-fluxo",
    )


def aguardar_status(pedido_id, token, desejado, tentativas=30, intervalo=0.5):
    """Consulta o pedido até ele alcançar um dos estados desejados.

    Espera por condição, e não por tempo fixo: o worker é assíncrono e o tempo
    total varia com a fila, com o rebalanceamento do grupo e com o clock.
    """

    def consultar():
        status, payload, _ = pedir(
            "GET", f"/api/v1/pedidos/{pedido_id}/", token=token
        )
        if status == 200 and payload and payload.get("status") in desejado:
            return payload
        return None

    return aguardar(consultar, tentativas=tentativas, intervalo=intervalo)


def aguardar_notificacao(pedido_id, token, tentativas=30, intervalo=0.5):
    """Aguarda a notificação do pedido aparecer em ``GET /api/v1/notificacoes/``."""

    def consultar():
        status, payload, _ = pedir(
            "GET", "/api/v1/notificacoes/?page_size=50", token=token
        )
        if status != 200:
            return None
        for linha in (payload or {}).get("results") or []:
            if linha.get("pedido") == pedido_id:
                return linha
        return None

    return aguardar(consultar, tentativas=tentativas, intervalo=intervalo)


def contar_notificacoes(pedido_id, token):
    status, payload, _ = pedir(
        "GET", "/api/v1/notificacoes/?page_size=50", token=token
    )
    if status != 200:
        return None
    return len(
        [
            n
            for n in (payload or {}).get("results") or []
            if n.get("pedido") == pedido_id
        ]
    )


def criar_pedido(token, item_id, chave):
    status, payload, _ = pedir(
        "POST",
        "/api/v1/pedidos/",
        {"idempotency_key": chave, "itens": [{"item_id": item_id, "quantidade": 2}]},
        token,
    )
    return status, payload
