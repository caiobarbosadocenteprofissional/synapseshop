"""Camada de cache-aside do catálogo e do pedido (Aulas 8 e 11).

Implementa o padrão cache-aside sobre o Redis provisionado pelo Compose:

1. **miss** — a chave não existe (ou expirou por TTL);
2. **preenchimento** — o produtor monta a resposta no PostgreSQL e ela é
   gravada com o TTL da chave;
3. **hit** — a chave existe e a resposta é servida sem tocar no banco.

Nomenclatura de chaves (padrão ``entidade:recurso[:variante]`` da spec):

- ``itens:list:<assinatura>`` — listagem paginada/filtrada. A assinatura é um
  resumo (hash) dos query params relevantes, evitando servir a página de um
  filtro para outro (TTL de ``CACHE_TTL_LISTA``).
- ``item:<id>`` — detalhe de um item, consulta mais pesada e estável
  (TTL de ``CACHE_TTL_DETALHE``).
- ``pedido:<id>`` — detalhe do pedido, introduzido na Aula 11
  (TTL de ``CACHE_TTL_PEDIDO``).

Cada variante é registrada em um índice no Redis (``itens:list:indice`` e
``itens:detalhe:indice``) para que a invalidação por evento de domínio apague
todas as combinações sem varrer o keyspace com ``KEYS``/``SCAN``. As métricas de
hit rate são contadas com ``INCR`` no próprio Redis, ficando corretas mesmo com
mais de um processo da API.

O detalhe do pedido **não** usa índice: há uma chave por pedido, e a invalidação
sabe exatamente qual apagar. Registrar a chave em um índice custaria uma escrita
a cada leitura para ganhar a possibilidade de varrer todos os pedidos — que
ninguém faz.
"""

import hashlib
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django_redis import get_redis_connection

logger = logging.getLogger("synapseshop.cache")

# Nomenclatura de chaves de cache (Aula 8).
PREFIXO_LISTA_ITENS = "itens:list"
PREFIXO_ITEM = "item"
PREFIXO_PEDIDO = "pedido"
INDICE_LISTA_ITENS = "itens:list:indice"
INDICE_ITENS_DETALHE = "itens:detalhe:indice"
INDICE_METRICAS = "cache:stats"

# Rótulos de métrica por endpoint instrumentado.
ENDPOINT_LISTA_ITENS = "itens:list"
ENDPOINT_DETALHE_ITEM = "item:detalhe"
ENDPOINT_DETALHE_PEDIDO = "pedido:detalhe"

RESULTADO_HIT = "HIT"
RESULTADO_MISS = "MISS"
RESULTADO_AUSENTE = "AUSENTE"

# Query params que alteram o resultado da listagem e, portanto, a chave do cache.
PARAMETROS_RELEVANTES = (
    "page",
    "page_size",
    "search",
    "ordering",
    "is_active",
    "category",
)


def cache_ativo() -> bool:
    """Indica se o cache-aside está habilitado (kill-switch `CACHE_ENABLED`)."""
    return bool(getattr(settings, "CACHE_ENABLED", False))


def _redis():
    """Cliente Redis para os índices de invalidação; ``None`` se indisponível."""
    if not cache_ativo():
        return None
    try:
        return get_redis_connection("default")
    except Exception:  # noqa: BLE001 - cache nunca deve derrubar a API
        logger.warning("cache_indisponivel: indices nao atualizados", exc_info=True)
        return None


def _chave_lista_itens(query_params) -> str:
    """Monta ``itens:list:<assinatura>`` a partir dos query params relevantes."""
    if hasattr(query_params, "lists"):
        query_params = query_params.lists()
    relevantes = {
        chave: valores for chave, valores in sorted(query_params) if chave in PARAMETROS_RELEVANTES
    }
    assinatura = hashlib.sha1(
        json.dumps(relevantes, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    return f"{PREFIXO_LISTA_ITENS}:{assinatura}"


def _chave_item(item_id) -> str:
    return f"{PREFIXO_ITEM}:{item_id}"


def _chave_pedido(pedido_id) -> str:
    return f"{PREFIXO_PEDIDO}:{pedido_id}"


def _contar(endpoint: str, resultado: str) -> None:
    """Conta hit/miss com ``INCR`` (atomico e compartilhado entre processos)."""
    cliente = _redis()
    if cliente is None:
        return
    try:
        cliente.incr(cache.make_key(f"{INDICE_METRICAS}:{endpoint}:{resultado}"))
    except Exception:  # noqa: BLE001
        logger.warning("cache_stats_indisponiveis endpoint=%s", endpoint, exc_info=True)


def _registrar_no_indice(indice: str, chave: str) -> None:
    cliente = _redis()
    if cliente is None:
        return
    try:
        cliente.sadd(indice, chave)
    except Exception:  # noqa: BLE001
        logger.warning("cache_indice_indisponivel indice=%s", indice, exc_info=True)


def _texto(chave) -> str:
    """O cliente Redis devolve bytes; as chaves do cache do Django sao `str`."""
    return chave.decode() if isinstance(chave, bytes) else chave


def _log_lookup(endpoint: str, chave: str, resultado: str, ttl: int, origem: str) -> None:
    logger.info(
        json.dumps(
            {
                "evento": "cache.lookup",
                "endpoint": endpoint,
                "chave": chave,
                "resultado": resultado,
                "ttl": ttl,
                "origem": origem,
            },
            ensure_ascii=False,
        )
    )


def _cache_aside(chave: str, endpoint: str, ttl: int, produtor):
    """Executa o cache-aside e devolve ``(dados, resultado)``.

    Só o que foi **serializado** pelo DRF (``ReturnList``/``dict``) é gravado —
    nunca o objeto ``Response``, que carrega referência da requisição. O
    produtor é uma callable executada somente no miss.
    """
    if not cache_ativo():
        return produtor(), "BYPASS"

    dados = cache.get(chave)
    if dados is not None:
        _contar(endpoint, RESULTADO_HIT)
        _log_lookup(endpoint, chave, RESULTADO_HIT, ttl, "redis")
        return dados, RESULTADO_HIT

    dados = produtor()
    if dados is None:
        # Ausência não é cacheada: guardar "não existe" transformaria um 404 em
        # HIT por 60 s, e um registro criado logo depois ficaria invisível.
        _contar(endpoint, RESULTADO_MISS)
        _log_lookup(endpoint, chave, "AUSENTE", ttl, "postgresql")
        return None, "AUSENTE"
    try:
        cache.set(chave, dados, timeout=ttl)
    except Exception:  # noqa: BLE001 - falha de cache não derruba a requisição
        logger.warning("cache_gravacao_falhou chave=%s", chave, exc_info=True)
    _contar(endpoint, RESULTADO_MISS)
    _log_lookup(endpoint, chave, RESULTADO_MISS, ttl, "postgresql")
    return dados, RESULTADO_MISS


def get_lista_itens(query_params, produtor):
    """Cache-aside da listagem de itens (TTL `CACHE_TTL_LISTA`)."""
    chave = _chave_lista_itens(query_params)
    _registrar_no_indice(INDICE_LISTA_ITENS, chave)
    return _cache_aside(
        chave, ENDPOINT_LISTA_ITENS, settings.CACHE_TTL_LISTA, produtor
    )


def get_item(item_id, produtor):
    """Cache-aside do detalhe de um item (TTL `CACHE_TTL_DETALHE`)."""
    chave = _chave_item(item_id)
    _registrar_no_indice(INDICE_ITENS_DETALHE, chave)
    return _cache_aside(
        chave, ENDPOINT_DETALHE_ITEM, settings.CACHE_TTL_DETALHE, produtor
    )


def _invalidar_indice(indice: str) -> int:
    """Apaga todas as chaves registradas em um índice e limpa o índice."""
    cliente = _redis()
    if cliente is None:
        return 0
    try:
        chaves = [_texto(chave) for chave in cliente.smembers(indice)]
        if chaves:
            cache.delete_many(chaves)
        cliente.delete(indice)
    except Exception:  # noqa: BLE001
        logger.warning("cache_invalidacao_falhou indice=%s", indice, exc_info=True)
        return 0
    _log_lookup(indice, f"{indice}:*", "INVALIDADO", 0, "evento_dominio")
    return len(chaves)


def invalidar_lista_itens() -> int:
    """Invalida todas as variantes (filtros/páginas) da listagem de itens."""
    return _invalidar_indice(INDICE_LISTA_ITENS)


def invalidar_item(item_id) -> bool:
    """Invalida o detalhe de um item especifico."""
    if not cache_ativo():
        return False
    chave = _chave_item(item_id)
    removido = bool(cache.delete(chave))
    cliente = _redis()
    if cliente is not None:
        try:
            cliente.srem(INDICE_ITENS_DETALHE, chave)
        except Exception:  # noqa: BLE001
            logger.warning("cache_indice_indisponivel", exc_info=True)
    _log_lookup(ENDPOINT_DETALHE_ITEM, chave, "INVALIDADO", 0, "evento_dominio")
    return removido


def invalidar_detalhes_itens() -> int:
    """Invalida todos os detalhes em cache (mudança em uma categoria)."""
    return _invalidar_indice(INDICE_ITENS_DETALHE)


def get_pedido(pedido_id, produtor):
    """Cache-aside do detalhe do pedido (TTL `CACHE_TTL_PEDIDO`).

    O TTL é curto **por construção**: o estado do pedido muda por eventos
    processes em outras máquinas (pagamento na API, notificação no worker), e
    embora quem grava invalide a chave, o TTL é o que limita o estrago quando a
    invalidação não acontece.
    """
    return _cache_aside(
        _chave_pedido(pedido_id),
        ENDPOINT_DETALHE_PEDIDO,
        settings.CACHE_TTL_PEDIDO,
        produtor,
    )


def invalidar_pedido(pedido_id) -> bool:
    """Invalida o detalhe de um pedido. Chamado por **qualquer** processo que o altere.

    É esta função que fecha o acordo da Aula 11: a chave vive no Redis
    compartilhado, então a API que grava o pagamento e o worker que grava a
    notificação alcançam a mesma chave — não há cache por processo para ficar
    inconsistente.
    """
    if not cache_ativo():
        return False
    chave = _chave_pedido(pedido_id)
    removido = bool(cache.delete(chave))
    _log_lookup(ENDPOINT_DETALHE_PEDIDO, chave, "INVALIDADO", 0, "gravacao_do_pedido")
    return removido


def ttls() -> dict:
    return {
        ENDPOINT_LISTA_ITENS: settings.CACHE_TTL_LISTA,
        ENDPOINT_DETALHE_ITEM: settings.CACHE_TTL_DETALHE,
        ENDPOINT_DETALHE_PEDIDO: settings.CACHE_TTL_PEDIDO,
    }


def metricas() -> dict:
    """Métricas de eficácia do cache: hits, misses e hit rate por endpoint."""
    if not cache_ativo():
        return {
            "cache_habilitado": False,
            "endpoints": {},
            "observacao": "CACHE_ENABLED=false: as consultas vao direto ao PostgreSQL.",
        }

    endpoints = {}
    total_hits = 0
    total_misses = 0
    for endpoint, ttl in ttls().items():
        hits = cache.get(f"{INDICE_METRICAS}:{endpoint}:{RESULTADO_HIT}", 0) or 0
        misses = cache.get(f"{INDICE_METRICAS}:{endpoint}:{RESULTADO_MISS}", 0) or 0
        lookups = hits + misses
        endpoints[endpoint] = {
            "hits": hits,
            "misses": misses,
            "total_lookups": lookups,
            "hit_rate": round(hits / lookups, 4) if lookups else 0.0,
            "ttl_segundos": ttl,
        }
        total_hits += hits
        total_misses += misses

    lookups_total = total_hits + total_misses
    return {
        "cache_habilitado": True,
        "redis_url": settings.CACHES["default"]["LOCATION"],
        "chaves": {
            "listagem": f"{PREFIXO_LISTA_ITENS}:<assinatura>",
            "detalhe": f"{PREFIXO_ITEM}:<id>",
            "pedido": f"{PREFIXO_PEDIDO}:<id>",
        },
        "endpoints": endpoints,
        "total_hits": total_hits,
        "total_misses": total_misses,
        "total_lookups": lookups_total,
        "hit_rate": round(total_hits / lookups_total, 4) if lookups_total else 0.0,
    }


def reset_metricas() -> None:
    """Zera os contadores de hit/miss para uma nova janela de medição."""
    if not cache_ativo():
        return
    for endpoint in ttls():
        cache.delete(f"{INDICE_METRICAS}:{endpoint}:{RESULTADO_HIT}")
        cache.delete(f"{INDICE_METRICAS}:{endpoint}:{RESULTADO_MISS}")
