"""Topologia AMQP: conexão, exchanges, filas e DLQs.

Fica num módulo só porque topologia e conexão são a mesma coisa no AMQP: quem
declara as filas precisa de um canal, e quem tem um canal já tem a conexão.
No Kafka as duas coisas são separadas (``confluent_kafka.admin`` fala com o
broker sem passar pelo consumidor).
"""

import pika
from django.conf import settings

from config.topologias import topologias


def conexao(client_id: str = "") -> pika.BlockingConnection:
    """Abre uma conexão AMQP com heartbeat e timeout de bloqueio definidos.

    ``client_id`` vira o nome da conexão na Management UI do RabbitMQ. No Kafka o
    equivalente é o `client.id`, e sem ele a pergunta "qual worker está conectado
    aqui?" só se responde por Advando Closed ou pela Management API do próprio
    broker — de qualquer modo, com mais trabalho.
    """
    parametros = pika.ConnectionParameters(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        virtual_host=settings.RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(
            settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
        ),
        heartbeat=30,
        blocked_connection_timeout=30,
        connection_attempts=3,
        retry_delay=2,
        socket_timeout=10,
        client_properties={"connection_name": client_id} if client_id else None,
    )
    return pika.BlockingConnection(parametros)


def fechar_recursos(canal, conexao_ativa) -> None:
    """Fecha canal e conexão best effort; recursos já fechados são ignorados."""
    for recurso in (canal, conexao_ativa):
        try:
            if recurso is not None and recurso.is_open:
                recurso.close()
        except Exception:  # noqa: BLE001 - encerramento é best effort
            pass


def declarar_topologia(canal) -> None:
    """Declara exchanges, filas, DLX e DLQs de todos os eventos. Idempotente.

    A exchange de eventos e a *dead-letter exchange* são únicas; o que varia por
    evento é a fila, a DLQ e o *routing key*. Declarar tudo numa função só
    significa que nenhuma API ou worker precisa saber se o outro já subiu.
    """
    canal.exchange_declare(
        exchange=settings.RABBITMQ_EXCHANGE, exchange_type="topic", durable=True
    )
    canal.exchange_declare(exchange=settings.RABBITMQ_DLX, exchange_type="direct", durable=True)

    for topologia in topologias():
        canal.queue_declare(queue=topologia.fila_dlq, durable=True)
        canal.queue_bind(
            exchange=settings.RABBITMQ_DLX,
            queue=topologia.fila_dlq,
            routing_key=topologia.routing_key,
        )

        # A fila principal morre para a DLQ: basta um nack sem requeue para que o
        # broker rota a mensagem, sem que o consumidor precise republicar nada.
        canal.queue_declare(
            queue=topologia.fila,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.RABBITMQ_DLX,
                "x-dead-letter-routing-key": topologia.routing_key,
            },
        )
        canal.queue_bind(
            exchange=topologia.exchange,
            queue=topologia.fila,
            routing_key=topologia.routing_key,
        )
    canal.basic_qos(prefetch_count=settings.RABBITMQ_PREFETCH)
