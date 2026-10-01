"""Idempotência do consumidor de eventos (Aula 9).

A garantia do broker é de entrega **pelo menos uma vez**: a mesma mensagem pode
chegar mais de uma vez (reentrega após falha, *requeue* em queda de conexão,
redelivery em restart do consumidor). Para que a reentrega seja inofensiva, cada
evento carrega uma ``idempotency_key`` — a chave de negócio do pedido — e esta
módulo guarda as chaves já aplicadas com **prazo de validade (TTL)**.

Duas camadas, com papéis diferentes:

- **Redis** (``SET NX`` com TTL): caminho rápido e barato de consultar, com o
  TTL nativo. É volátil — ``allkeys-lru`` pode despejá-lo — e o cache do projeto
  roda com ``IGNORE_EXCEPTIONS``.
- **PostgreSQL** (``EventoProcessado``): fonte durável, com ``expira_em`` e
  índice para a limpeza. A unicidade ``(evento, idempotency_key)`` resolve
  corrida entre consumidores.

O registro da chave acontece **depois** do processamento bem-sucedido, nunca
antes: reservar a chave antes corre o risco de descartar uma reentrega cujo
processamento falhou, o que entregaria o pedido com efeito zero.
"""

import json
import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from repositories.models import EventoProcessado

logger = logging.getLogger("synapseshop.idempotencia")

PREFIXO_CHAVE = "evento:processado"


def _chave_cache(evento: str, idempotency_key: str) -> str:
    return f"{PREFIXO_CHAVE}:{evento}:{idempotency_key}"


def _log(nome_evento: str, **campos) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `evento` e a colisão de nome seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


def limpar_expirados() -> int:
    """Remove chaves expiradas. Chamado pelo worker antes de cada lote."""
    removidos, _ = EventoProcessado.objects.filter(expira_em__lte=timezone.now()).delete()
    return removidos


def ja_processado(evento: str, idempotency_key: str) -> bool:
    """Informa se a chave já foi aplicada — decide pular o processamento."""
    try:
        from django.core.cache import cache

        if cache.get(_chave_cache(evento, idempotency_key)) is not None:
            return True
    except Exception:  # noqa: BLE001 - cache indisponível não é erro
        logger.warning("idempotencia_cache_indisponivel evento=%s", evento, exc_info=True)

    return EventoProcessado.objects.filter(
        evento=evento, idempotency_key=idempotency_key
    ).exists()


def registrar(evento: str, idempotency_key: str, duracao_ms: Optional[float] = None) -> bool:
    """Marca a chave como aplicada. Devolve ``False`` se já existia.

    ``False`` significa que outra entrega foi a responsável — quem chamou deve
    tratar como no-op, pois o efeito já existe.
    """
    ttl = settings.IDEMPOTENCIA_TTL_SEGUNDOS
    registrado = _registrar_postgresql(evento, idempotency_key, ttl)
    _registrar_cache(evento, idempotency_key, ttl)
    _log(
        "idempotencia.registrada",
        evento=evento,
        idempotency_key=idempotency_key,
        ttl_segundos=ttl,
        duracao_ms=duracao_ms,
        novo=registrado,
    )
    return registrado


def _registrar_cache(evento: str, idempotency_key: str, ttl: int) -> None:
    try:
        from django.core.cache import cache

        cache.set(_chave_cache(evento, idempotency_key), timezone.now().isoformat(), timeout=ttl)
    except Exception:  # noqa: BLE001 - a fonte durável já registrou
        logger.warning("idempotencia_cache_falhou evento=%s", evento, exc_info=True)


def _registrar_postgresql(evento: str, idempotency_key: str, ttl: int) -> bool:
    try:
        with transaction.atomic():
            EventoProcessado.objects.create(
                evento=evento,
                idempotency_key=idempotency_key,
                expira_em=timezone.now() + timedelta(seconds=ttl),
            )
        return True
    except IntegrityError:
        # Corrida entre entregas: a constraint única decidiu, e a chave existe.
        return False