"""Testes do cache-aside (``services.cache``).

Cobrem o ciclo miss ➔ preenchimento ➔ hit, o caminho de ausência, o *kill-switch*
de bypass e a invalidação. O Redis é substituído por um ``FakeRedis`` sempre que
o teste precisa observar os índices.
"""

import pytest
from django.core.cache import cache as django_cache
from django.http import QueryDict

from services import cache

pytestmark = pytest.mark.unit


def _produtor(valor):
    return lambda: valor


def _query(params):
    query = QueryDict("", mutable=True)
    for chave, valor in params.items():
        query[chave] = valor
    return query


def test_bypass_quando_cache_desabilitado(sem_cache):
    dados, resultado = cache.get_item(1, _produtor({"id": 1}))
    assert resultado == "BYPASS"
    assert dados == {"id": 1}


def test_get_item_miss_depois_hit(fake_redis):
    chamadas = {"n": 0}

    def produtor():
        chamadas["n"] += 1
        return {"id": 1}

    _, primeiro = cache.get_item(1, produtor)
    _, segundo = cache.get_item(1, produtor)
    assert primeiro == "MISS"
    assert segundo == "HIT"
    assert chamadas["n"] == 1


def test_get_item_ausente_nao_e_cacheado(fake_redis):
    dados, resultado = cache.get_item(99, _produtor(None))
    assert dados is None
    assert resultado == "AUSENTE"
    # Repetir continua indo ao produtor (ausência não vira HIT).
    _, resultado2 = cache.get_item(99, _produtor(None))
    assert resultado2 == "AUSENTE"


def test_get_lista_itens_miss_e_hit(fake_redis):
    dados = {"count": 1, "results": [{"id": 1}]}
    _, primeiro = cache.get_lista_itens(_query({"page": "1"}), _produtor(dados))
    _, segundo = cache.get_lista_itens(_query({"page": "1"}), _produtor(dados))
    assert primeiro == "MISS"
    assert segundo == "HIT"


def test_get_pedido_miss_hit_e_invalidacao(fake_redis):
    _, primeiro = cache.get_pedido(7, _produtor({"id": 7}))
    _, segundo = cache.get_pedido(7, _produtor({"id": 7}))
    assert primeiro == "MISS"
    assert segundo == "HIT"

    assert cache.invalidar_pedido(7) is True
    _, terceiro = cache.get_pedido(7, _produtor({"id": 7}))
    assert terceiro == "MISS"


def test_invalidar_item_remove_chave_e_indice(fake_redis):
    cache.get_item(5, _produtor({"id": 5}))
    assert cache.invalidar_item(5) is True
    _, resultado = cache.get_item(5, _produtor({"id": 5}))
    assert resultado == "MISS"


def test_invalidar_item_retorna_false_se_ausente(fake_redis):
    assert cache.invalidar_item(123) is False


def test_invalidar_item_sem_cache(sem_cache):
    assert cache.invalidar_item(1) is False


def test_invalidar_pedido_sem_cache(sem_cache):
    assert cache.invalidar_pedido(1) is False


def test_invalidar_lista_apaga_todas_as_variantes(fake_redis):
    cache.get_lista_itens(_query({"page": "1"}), _produtor([1]))
    cache.get_lista_itens(_query({"page": "2"}), _produtor([2]))
    assert cache.invalidar_lista_itens() == 2


def test_invalidar_detalhes_apaga_todos_os_itens(fake_redis):
    cache.get_item(1, _produtor({"id": 1}))
    cache.get_item(2, _produtor({"id": 2}))
    assert cache.invalidar_detalhes_itens() == 2


def test_contar_e_registrar_indice_com_redis(fake_redis):
    cache._contar(cache.ENDPOINT_DETALHE_ITEM, cache.RESULTADO_HIT)
    cache._registrar_no_indice("meu:indice", "minha:chave")
    assert any("cache:stats" in chave for chave in fake_redis.counters)
    assert "minha:chave" in fake_redis.sets["meu:indice"]


def test_funcoes_de_metrica_nao_falham_sem_redis(sem_cache):
    cache._contar(cache.ENDPOINT_LISTA_ITENS, cache.RESULTADO_MISS)
    cache._registrar_no_indice("i", "k")
    assert cache._redis() is None


def test_redis_retorna_none_quando_connection_falha(monkeypatch, settings):
    settings.CACHE_ENABLED = True

    def explodir(*args, **kwargs):
        raise RuntimeError("sem redis")

    monkeypatch.setattr(cache, "get_redis_connection", explodir)
    assert cache._redis() is None


def test_metricas_desabilitadas(sem_cache):
    metricas = cache.metricas()
    assert metricas["cache_habilitado"] is False
    cache.reset_metricas()  # no-op, não deve falhar


def test_metricas_habilitadas_calculam_hit_rate(fake_redis):
    django_cache.set(f"{cache.INDICE_METRICAS}:{cache.ENDPOINT_DETALHE_ITEM}:HIT", 3)
    django_cache.set(f"{cache.INDICE_METRICAS}:{cache.ENDPOINT_DETALHE_ITEM}:MISS", 1)

    metricas = cache.metricas()
    endpoint = metricas["endpoints"][cache.ENDPOINT_DETALHE_ITEM]
    assert endpoint["hits"] == 3
    assert endpoint["misses"] == 1
    assert endpoint["hit_rate"] == 0.75
    assert metricas["total_hits"] == 3
    assert metricas["total_lookups"] == 4
    assert metricas["redis_url"] == "synapseshop-tests"


def test_reset_metricas_zera_contadores(fake_redis):
    django_cache.set(f"{cache.INDICE_METRICAS}:{cache.ENDPOINT_LISTA_ITENS}:HIT", 5)
    cache.reset_metricas()
    assert django_cache.get(f"{cache.INDICE_METRICAS}:{cache.ENDPOINT_LISTA_ITENS}:HIT") is None


def test_gravacao_no_cache_que_falha_nao_derruba_o_miss(fake_redis, monkeypatch):
    def explodir(*args, **kwargs):
        raise RuntimeError("cache fora")

    monkeypatch.setattr(cache.cache, "set", explodir)
    _, resultado = cache.get_item(1, _produtor({"id": 1}))
    assert resultado == "MISS"


def test_invalidacao_que_falha_retorna_zero(fake_redis, monkeypatch):
    def explodir(*args, **kwargs):
        raise RuntimeError("redis fora")

    monkeypatch.setattr(fake_redis, "smembers", explodir)
    assert cache.invalidar_lista_itens() == 0


def test_contar_que_falha_nao_propaga(fake_redis, monkeypatch):
    def explodir(*args, **kwargs):
        raise RuntimeError("redis fora")

    monkeypatch.setattr(fake_redis, "incr", explodir)
    cache._contar(cache.ENDPOINT_DETALHE_ITEM, cache.RESULTADO_HIT)


def test_registrar_no_indice_que_falha_nao_propaga(fake_redis, monkeypatch):
    def explodir(*args, **kwargs):
        raise RuntimeError("redis fora")

    monkeypatch.setattr(fake_redis, "sadd", explodir)
    cache._registrar_no_indice(cache.INDICE_LISTA_ITENS, "itens:list:abc")


def test_srem_que_falha_nao_derruba_invalidacao(fake_redis, monkeypatch):
    cache.get_item(5, _produtor({"id": 5}))

    def explodir(*args, **kwargs):
        raise RuntimeError("redis fora")

    monkeypatch.setattr(fake_redis, "srem", explodir)
    assert cache.invalidar_item(5) is True
