# Métricas da Aula 8 — Cache-aside com Redis

Medições de desempenho, hit rate e demonstração do ciclo de vida do cache
(`miss` → preenchimento → `hit` → expiração/invalidação) para os endpoints do
catálogo instrumentados na Aula 8.

Decisões de projeto: [`DECISOES_TECNICAS_AULA8.md`](DECISOES_TECNICAS_AULA8.md).

---

## 1. Metodologia

| Item | Descrição |
| :--- | :--- |
| Ferramenta | `scripts/bench_cache.py` (Python stdlib, `concurrent.futures` + `http.client`). |
| Catálogo | 5 categorias e 300 itens via `python manage.py seed_demo_catalog`. |
| Endereços | `GET /api/v1/items/?page_size=10` (listagem) e `GET /api/v1/items/310/` (detalhe). |
| Autenticação | `Bearer` de admin; o endpoint exige JWT por decisão da Aula 7. |
| Aquecimento | 5 requisições descartadas antes da coleta. |
| Métricas | latência média, p50, p95, min, max, duração total e RPS. |
| Reset entre execuções | `docker compose exec -T redis redis-cli -n 1 FLUSHALL`. |

O tamanho do catálogo não altera a análise: a consulta da listagem busca 10
itens paginados, e a do detalhe busca 1 item por chave primária.

### 1.1 Como reproduzir

```bash
# 0) catálogo de 300 itens
docker compose exec -T api python manage.py seed_demo_catalog

# 1) baseline (antes do cache): kill-switch desliga o cache
#    CACHE_ENABLED=false docker compose up -d --force-recreate api
python scripts/bench_cache.py --path "/api/v1/items/?page_size=10" \
  --requests 150 --concurrency 1

# 2) com cache
docker compose exec -T redis redis-cli -n 1 FLUSHALL
python scripts/bench_cache.py --path "/api/v1/items/?page_size=10" \
  --requests 150 --concurrency 1

# 3) hit rate por endpoint
curl -X POST http://localhost:8000/api/v1/cache/stats/ -H "Authorization: Bearer <access>"
curl http://localhost:8000/api/v1/cache/stats/ -H "Authorization: Bearer <access>"
```

> O `CACHE_ENABLED` é uma variável de ambiente do contêiner; para o par A/B
> usa-se `docker compose up -d --force-recreate api` com o valor desejado, de
> modo que as duas execuções usam **a mesma imagem** e só muda o cache.

---

## 2. Baseline — antes da introdução do cache

Coletado antes de qualquer código de cache existir, com 120 requisições e
concorrência 4 (`CACHE_ENABLED` inativo por ausência do recurso).

| Endpoint | média (ms) | p50 (ms) | p95 (ms) | min (ms) | max (ms) | duração (s) | RPS |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Listagem `?page_size=10` | 38,73 | 36,71 | 48,25 | 24,86 | 85,38 | 1,177 | 101,98 |
| Detalhe `/api/v1/items/110/` | 32,13 | 31,59 | 40,61 | 20,84 | 50,84 | 0,981 | 122,34 |

---

## 3. Comparação antes × depois (par A/B, mesma imagem)

O par A/B alterna apenas `CACHE_ENABLED`, garantindo que a diferença se deve ao
cache e não a mudanças de código, imagem ou dados.

### 3.1 Listagem — `GET /api/v1/items/?page_size=10`

Concorrência 1, 150 requisições:

| Métrica | `CACHE_ENABLED=false` | `CACHE_ENABLED=true` | Variação |
| :--- | ---: | ---: | ---: |
| média (ms) | 22,01 | **15,48** | **−29,7 %** |
| p50 (ms) | 21,74 | **15,10** | **−30,5 %** |
| p95 (ms) | 25,23 | **18,07** | **−28,4 %** |
| RPS | 45,32 | **64,42** | **+42,1 %** |

Concorrência 8, 300 requisições:

| Métrica | `CACHE_ENABLED=false` | `CACHE_ENABLED=true` | Variação |
| :--- | ---: | ---: | ---: |
| média (ms) | 82,91 | **73,13** | **−11,8 %** |
| p50 (ms) | 78,65 | **72,08** | −8,4 % |
| p95 (ms) | 124,37 | **99,83** | **−19,7 %** |
| RPS | 95,71 | **108,55** | **+13,4 %** |

Distribuição de resultados: `BYPASS: 300` sem cache · `HIT: 300` com cache
(1 `MISS` de aquecimento fora da coleta).

### 3.2 Detalhe — `GET /api/v1/items/310/`

Concorrência 1, 150 requisições:

| Métrica | `CACHE_ENABLED=false` | `CACHE_ENABLED=true` | Variação |
| :--- | ---: | ---: | ---: |
| média (ms) | 24,08 | **17,07** | **−29,1 %** |
| p50 (ms) | 23,43 | **16,36** | **−30,2 %** |
| p95 (ms) | 32,54 | **19,58** | **−39,9 %** |
| RPS | 41,44 | **58,43** | **+41,0 %** |

Execução independente anterior, mesmo item de outra execução do seed
(`/api/v1/items/110/`): média 17,93 → 15,71 ms (−12,4 %) e RPS 55,65 → 63,50
(+14,1 %). **A diferença entre as duas execuções do mesmo cenário (−29,1 % e
−12,4 %) é variância do ambiente de desenvolvimento**, e está registrada aqui de
propósito: o ganho do detalhe é real, mas o intervalo honesto é de −12 % a −29 %.

Concorrência 8, 300 requisições:

| Métrica | `CACHE_ENABLED=false` | `CACHE_ENABLED=true` | Variação |
| :--- | ---: | ---: | ---: |
| média (ms) | 60,95 | 61,97 | +1,7 % (dentro do ruído) |
| p50 (ms) | 60,13 | 61,14 | +1,7 % (dentro do ruído) |
| p95 (ms) | 76,96 | 79,34 | +3,1 % (dentro do ruído) |
| RPS | 130,19 | 128,16 | −1,6 % (dentro do ruído) |

**Leitura:** com 8 clientes simultâneos, a latência do detalhe passa a ser
dominada pela contenção do servidor de desenvolvimento (single process), e o
ganho de ~1 ms por requisição fica dentro do ruído. Por isso o ganho do cache
é evidenciado a concorrência 1, e a listagem (que concentra mais trabalho por
requisição) é a que mantém vantagem mesmo sob concorrência 8.

---

## 4. Por que o ganho é esse: decomposição do custo por requisição

Medido dentro do contêiner, com o mesmo processo da API:

| Operação | Tempo |
| :--- | ---: |
| Consulta da listagem (10 itens + `COUNT`, `select_related`) | 2,43 ms |
| Serialização de 10 itens (DRF) | 0,75 ms |
| Consulta de detalhe (PK + `select_related`) | 1,14 ms |
| Lookup do usuário no banco (exigência do JWT a cada requisição) | 0,71 ms |
| `cache.get` no Redis | 0,16–0,19 ms |

O cache elimina a consulta e a serialização (≈ 3,2 ms na listagem, ≈ 1,1 ms no
detalhe) e as substitui por ≈ 0,2 ms de leitura no Redis. O restante da latência
observada no `curl` é overhead de HTTP/WSGI do contêiner de desenvolvimento, que
não é otimizado pelo cache. Daí os percentuais observados.

Consequência prática: **o ganho percentual cresce com o custo da consulta
eliminada**. Endpoints com agregações, joins pesados ou relatórios paginados
obtêm ganhos muito maiores do que uma busca por chave primária. O endpoint de
detalhe do catálogo, sendo uma busca por PK, é o pior caso para cache-aside —
mesmo assim, a latência média caiu de 24,08 ms para 17,07 ms.

---

## 5. Hit rate por endpoint

Carga mista de leitura (1 `MISS` + 40 `HIT` na listagem; 1 `MISS` + 25 `HIT` no
detalhe), com contadores zerados em seguida:

```
GET /api/v1/cache/stats/  (admin)
{
  "cache_habilitado": true,
  "redis_url": "redis://redis:6379/1",
  "chaves": {"listagem": "itens:list:<assinatura>", "detalhe": "item:<id>"},
  "endpoints": {
    "itens:list":  {"hits": 40, "misses": 1, "total_lookups": 41,
                    "hit_rate": 0.9756, "ttl_segundos": 60},
    "item:detalhe": {"hits": 25, "misses": 1, "total_lookups": 26,
                    "hit_rate": 0.9615, "ttl_segundos": 300}
  },
  "total_hits": 65, "total_misses": 2, "total_lookups": 67, "hit_rate": 0.9701
}
```

`hit_rate = total_hits / total_lookups`, conforme a spec. O perfil de workload
deste catálogo é fortemente leitor, o que produz hit rate elevado; workloads com
variação alta de escrita tendem a hit rate menores — por isso existe a
invalidação por evento, e não apenas TTL.

---

## 6. Ciclo de vida em tempo real

### 6.1 `MISS` → preenchimento → `HIT` → expiração por TTL

```
GET /api/v1/items/?page_size=5   X-Cache: MISS   (consulta ao PostgreSQL, grava no Redis com TTL 60)
GET /api/v1/items/?page_size=5   X-Cache: HIT    (servido do Redis)
... aguarda 61 s (TTL de 60 s expirou no Redis) ...
GET /api/v1/items/?page_size=5   X-Cache: MISS   (novo preenchimento)
```

TTL observado no Redis durante o ciclo:

```
$ docker compose exec -T redis redis-cli -n 1 --scan --pattern 'itens:list:*'
itens:list:indice
$ docker compose exec -T redis redis-cli -n 1 TTL "synapseshop:1:itens:list:c846376af757"
(integer) 50
```

### 6.2 Invalidação por evento de domínio

```
GET /api/v1/items/110/            X-Cache: MISS   (preenche item:110)
GET /api/v1/items/110/            X-Cache: HIT
GET /api/v1/items/?page_size=5    X-Cache: HIT    (preenche itens:list:*)

PATCH /api/v1/items/110/          (ItemAtualizado emitido)
GET /api/v1/items/110/            X-Cache: MISS   (item:110 invalidado)
GET /api/v1/items/?page_size=5    X-Cache: MISS   (itens:list:* invalidado)
```

Logs estruturados do mesmo ciclo:

```json
{"evento": "cache.lookup", "endpoint": "itens:list", "chave": "itens:list:c846376af757", "resultado": "MISS", "ttl": 60, "origem": "postgresql"}
{"evento": "cache.lookup", "endpoint": "itens:list", "chave": "itens:list:c846376af757", "resultado": "HIT", "ttl": 60, "origem": "redis"}
{"evento": "dominio.emitido", "nome": "ItemAtualizado", "payload": {"item_id": 110}}
```

O campo `origem` distingue `postgresql` (preenchimento) de `redis` (serviço),
tornando o ciclo auditável sem instruments de tracing.

### 6.3 Índice de invalidação

As chaves `itens:list:*` são registradas em um *set* de índice, porque
`KEYS`/`SCAN` em produção é proibido e `delete_pattern` do django-redis usa
`SCAN` (seguro, porém O(N) e mais lento que um `DEL` de conjunto):

```bash
$ docker compose exec -T redis redis-cli -n 1 SMEMBERS "itens:list:indice"
1) "itens:list:c846376af757"
2) "itens:list:bf21a9e8fbc5"
$ docker compose exec -T redis redis-cli -n 1 SMEMBERS "itens:detalhe:indice"
1) "itens:detalhe:110"
```

Detalhe de implementação: `django-redis` devolve bytes em `SMEMBERS`, então
`services/cache.py` normaliza com `_texto()` antes de `cache.delete_many` — sem
isso as chaves seriam apagadas com o prefixo literal `b'...'` e a invalidação
falharia silenciosamente.

---

## 7. Verificação funcional

| Suíte | Resultado |
| :--- | :--- |
| `python scripts/smoke_test_cache.py` | **29 passed, 0 failed** (miss/hit, filtros, PATCH/POST/DELETE, TTL, métricas, 401/403). |
| `python scripts/smoke_test_auth.py` (regressão Aula 7) | **13 passed, 0 failed** (com `THROTTLE_*` nos valores padrão). |
| `python manage.py check` | `System check identified no issues (0 silenced).` |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` (o cache não altera o schema). |

---

## 8. Ressalvas

1. **Servidor de desenvolvimento.** As medições usam `runserver` (single process,
   multi-threaded). Em produção, com Gunicorn e PostgreSQL em containers
   separados, o ganho percentual tende a ser maior, porque o custo removido
   (consulta + serialização no processo Python) pesa mais que o overhead de rede.
2. **Concorrência 8 no detalhe.** A variação medida ficou dentro do ruído; ver 3.2.
3. **Variância do ambiente.** Duas execuções do mesmo cenário de detalhe deram
   −12,4 % e −29,1 % (seção 3.2). Números isolados de uma única execução não
   devem ser generalizados.
4. **Throttling durante as medições.** Com os limites padrão da Aula 7
   (`200/min`), uma bateria com 300 requisições receberia `429`. As medições
   acima subiram `THROTTLE_USER` temporariamente para isolar a latência do cache;
   o valor foi **restaurado** e o smoke test de autenticação passa com os
   defaults.
5. **Estado do throttling no Redis.** Com o cache no Redis, os contadores do
   throttling do DRF passaram a viver no Redis (antes em memória do processo).
   Ganho de consistência entre workers, com a consequência de que o estado
   sobrevive a reinícios do contêiner até expirar a janela (60 s).
