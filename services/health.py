"""Verificação de saúde das dependências (Aula 11).

Duas perguntas, e a distinção entre elas é o ponto:

- **liveness** (``GET /health``) — "este processo ainda responde?" É o healthcheck
  do Compose. Não consulta nada externo, e é assim que precisa ser: se o
  healthcheck dependesse do Redis, uma queda do Redis reiniciaria a API em laço,
  sem que o reinício consertasse o Redis e com o efeito colateral de derrubar o
  serviço que estava funcionando.
- **readiness** (``GET /health/pronto``) — "este processo pode atender agora?"
  Consulta PostgreSQL, Redis e o broker e devolve 503 enquanto algum deles não
  responde. É ela que diz ao balanceador e ao Compose que a API ainda não está
  apta a receber tráfego.

Cada dependência é verificada **em isolamento**: uma falha não interrompe as
demais, senão o relatório só contaria a primeira. O tempo de resposta de cada uma
entra no relatório — é o que distingue "Redis lento" de "Redis fora", dois
problemas que exigem ações diferentes e aparecem igual na ausência de latência.
"""

import logging
import socket
import time
from typing import Any, Dict, List

from django.conf import settings
from django.db import connections

logger = logging.getLogger("synapseshop.health")


def _verificar_postgres() -> Dict[str, Any]:
    """``SELECT 1`` com o menor caminho possível — o que se prova é a conexão."""
    inicio = time.perf_counter()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"ok": True, "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3)}
    except Exception as exc:  # noqa: BLE001 - o relatório é a resposta
        return {
            "ok": False,
            "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3),
            "erro": str(exc)[:200],
        }


def _verificar_redis() -> Dict[str, Any]:
    """Ida e volta ao cache compartilhado (``SET`` + ``GET``).

    O teste é deliberadamente o round-trip e não a leitura do cache do pedido: o
    ponto é provar que o cache compartilhado responde, e o ``IGNORE_EXCEPTIONS``
    do projeto transformaria uma falha de Redis em um ``None`` silencioso.
    """
    if not getattr(settings, "CACHE_ENABLED", False):
        return {"ok": True, "observacao": "CACHE_ENABLED=false (cache em processo)"}

    inicio = time.perf_counter()
    try:
        from django.core.cache import cache

        marca = f"saude:{time.time_ns()}"
        cache.set(marca, "ok", timeout=10)
        if cache.get(marca) != "ok":
            raise RuntimeError("resposta inesperada do cache")
        return {"ok": True, "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3)}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3),
            "erro": str(exc)[:200],
        }


def _alvo_do_broker() -> Dict[str, Any]:
    """Host e porta do broker ativo, derivados das settings de cada transporte."""
    if settings.MENSAGERIA_BROKER == "kafka":
        primeiro = settings.KAFKA_BOOTSTRAP_SERVERS.split(",")[0].strip()
        host, _, porta = primeiro.partition(":")
        return {"host": host, "porta": int(porta or 9092), "broker": "kafka"}
    return {
        "host": settings.RABBITMQ_HOST,
        "porta": settings.RABBITMQ_PORT,
        "broker": "rabbitmq",
    }


def _verificar_broker() -> Dict[str, Any]:
    """Abertura de conexão TCP com o broker.

    Um ``connect`` não diz se o broker está saudável, diz se o endereço responde.
    É o que a readiness precisa: um serviço que não está nem na rede não pode
    receber tráfego, e o teste de AMQP/Kafka completo custaria uma autenticação e
    um *handshake* em toda verificação de liveness do Compose.
    """
    alvo = _alvo_do_broker()
    inicio = time.perf_counter()
    try:
        with socket.create_connection((alvo["host"], alvo["porta"]), timeout=2):
            pass
        return {
            "ok": True,
            "broker": alvo["broker"],
            "alvo": f"{alvo['host']}:{alvo['porta']}",
            "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "broker": alvo["broker"],
            "alvo": f"{alvo['host']}:{alvo['porta']}",
            "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3),
            "erro": str(exc)[:200],
        }


def verificar() -> Dict[str, Any]:
    """Relatório de prontidão. ``pronto=False`` devolve HTTP 503 na view."""
    dependencias: Dict[str, Any] = {
        "postgresql": _verificar_postgres(),
        "redis": _verificar_redis(),
    }
    # Mensageria desligada por configuração não é falha de prontidão: sem broker
    # a API ainda atende o catálogo e a leitura de pedidos.
    if settings.MESSAGERIA_ENABLED:
        dependencias["broker"] = _verificar_broker()
    else:
        dependencias["broker"] = {"ok": True, "observacao": "MESSAGERIA_ENABLED=false"}

    fora: List[str] = [nome for nome, estado in dependencias.items() if not estado.get("ok")]
    pronto = not fora
    if not pronto:
        logger.warning("saude.nao_pronto dependencias=%s", ",".join(fora))
    return {
        "status": "ok" if pronto else "degradado",
        "pronto": pronto,
        "broker_selecionado": settings.MENSAGERIA_BROKER,
        "mensageria_habilitada": bool(settings.MESSAGERIA_ENABLED),
        "cache_habilitado": bool(getattr(settings, "CACHE_ENABLED", False)),
        "dependencias": dependencias,
        "fora_do_ar": fora,
    }
