"""Declaração idempotente dos tópicos e DLQs do Kafka."""

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from django.conf import settings

from events.topology import topologias
from services.messaging_base import MensageriaIndisponivel, _log


def _erro_do_broker(exc: Exception) -> str:
    """Extrai a mensagem legível de uma falha de broker, sem o ruído do traceback."""
    erro = getattr(exc, "args", None)
    if isinstance(erro, (list, tuple)) and erro:
        erro = erro[0]
    if isinstance(erro, KafkaError):
        return f"{erro.name()}: {erro.str()}"
    return str(exc)[:500]


def declarar_topologia() -> None:
    """Cria os tópicos de todos os eventos se ainda não existirem. Idempotente.

    A criação é feita pelo mesmo código que publica e consome, e não por um
    contêiner de inicialização: o broker sobe, a API e os workers chamam esta
    função na subida e todos seguem funcionando, sem depender da ordem de start.

    A assinatura de partições e retenção é a mesma para todo evento — a diferença
    está nos nomes, que vêm de ``events/topology.py``.
    """
    cliente = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
    topicos = []
    for topologia in topologias():
        topicos.append(
            NewTopic(
                topologia.topico,
                num_partitions=settings.KAFKA_PARTICOES,
                replication_factor=settings.KAFKA_REPLICAS,
                config={
                    "retention.ms": str(settings.KAFKA_RETENTION_MS),
                    "cleanup.policy": settings.KAFKA_CLEANUP_POLICY,
                },
            )
        )
        topicos.append(
            NewTopic(
                topologia.dlq,
                num_partitions=1,
                replication_factor=settings.KAFKA_REPLICAS,
                config={
                    # A DLQ é a evidência da falha: precisa sobreviver mais que o
                    # tópico de trabalho, senão o diagnóstico se perde com o tempo.
                    "retention.ms": str(settings.KAFKA_RETENTION_MS * 4),
                    "cleanup.policy": settings.KAFKA_CLEANUP_POLICY,
                },
            )
        )
    # `create_topics` devolve o nome do tópico como chave, então a contagem de
    # partições tem de vir do `NewTopic` — que é o objeto que a define.
    particoes_por_topico = {topico.topic: topico.num_partitions for topico in topicos}
    for nome, futuro in cliente.create_topics(topicos, request_timeout=15).items():
        try:
            futuro.result()
            _log(
                "kafka.topico.criado",
                topico=nome,
                particoes=particoes_por_topico.get(nome),
            )
        except KafkaException as exc:
            if exc.args and isinstance(exc.args[0], KafkaError):
                if exc.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS:
                    continue
            raise MensageriaIndisponivel(
                f"nao foi possivel criar o topico {nome}: {_erro_do_broker(exc)}"
            ) from exc
