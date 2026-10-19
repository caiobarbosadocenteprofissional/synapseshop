"""Smoke test do cache-aside com Redis (Aula 8).

Executado contra a API em execução (ex.: `http://localhost:8000` via Docker).
Cobre os cenários do DoD da Aula 8:

- Ciclo completo miss -> preenchimento -> hit no endpoint de listagem e no de
  detalhe (verificado pelo header `X-Cache`).
- Invalidação por evento de domínio: `ItemAtualizado` derruba `item:<id>` e a
  listagem, e o dado novo passa a ser servido (sem leitura obsoleta).
- Invalidação em create/delete de item.
- Métricas de eficácia (hit rate) por endpoint, com acesso restrito ao admin.

Determinismo: cada execução usa um termo de busca e um item recém-criado, o que
gera chaves de cache ainda inexistentes (miss garantido) sem precisar limpar o
Redis. Execuções repetidas não se interferem.
"""

import sys
import time

from _comum import ADMIN, USER, Relatorio, configurar_base, pedir

BASE_URL = configurar_base(
    sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
)
MARCA = str(int(time.time()))

relatorio = Relatorio("== Smoke test cache-aside com Redis (Aula 8) ==")
check = relatorio.check

status, _, _ = pedir("GET", "/health")
check("health publico (200)", status == 200, f"-> {status}")

status, payload, _ = pedir("POST", "/api/v1/auth/token/", ADMIN)
check("login admin (200)", status == 200 and "access" in payload, f"-> {status}")
admin_token = payload["access"]

status, payload, _ = pedir("POST", "/api/v1/auth/token/", USER)
check("login user (200)", status == 200 and "access" in payload, f"-> {status}")
user_token = payload["access"]

# --- dados exclusivos deste teste -------------------------------------------
status, payload, _ = pedir(
    "POST",
    "/api/v1/categories/",
    {"name": f"Cache {MARCA}", "description": "Categoria do smoke test de cache"},
    token=admin_token,
)
check("POST categoria auxiliar (201)", status == 201, f"-> {status}")
categoria_id = payload["id"]

nome_item = f"Item Cache {MARCA}"
status, payload, _ = pedir(
    "POST",
    "/api/v1/items/",
    {
        "name": nome_item,
        "description": "Item do smoke test de cache",
        "price": "199.90",
        "category": categoria_id,
    },
    token=admin_token,
)
check("POST item auxiliar (201)", status == 201, f"-> {status}")
item_id = payload["id"]

# --- detalhe: miss -> hit ----------------------------------------------------
status, payload, headers = pedir("GET", f"/api/v1/items/{item_id}/", token=admin_token)
check(
    "detalhe 1a chamada (200, MISS = preenchimento)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)

status, payload, headers = pedir("GET", f"/api/v1/items/{item_id}/", token=admin_token)
check(
    "detalhe 2a chamada (200, HIT = servido do Redis)",
    status == 200 and headers.get("X-Cache") == "HIT",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)
check("detalhe servido do cache mantem o payload", payload.get("name") == nome_item)

# --- listagem: miss -> hit ---------------------------------------------------
caminho_lista = f"/api/v1/items/?search=Cache+{MARCA}"
status, payload, headers = pedir("GET", caminho_lista, token=admin_token)
check(
    "listagem 1a chamada (200, MISS = preenchimento)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)

status, payload, headers = pedir("GET", caminho_lista, token=admin_token)
check(
    "listagem 2a chamada (200, HIT = servido do Redis)",
    status == 200 and headers.get("X-Cache") == "HIT",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)

# filtros distintos geram chaves distintas (evita servir a pagina de um filtro)
status, _, headers = pedir(
    "GET", f"{caminho_lista}&page_size=1", token=admin_token
)
check(
    "listagem com outro filtro (200, MISS = chave distinta)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)

# --- invalidação por evento de domínio (ItemAtualizado) ----------------------
status, payload, _ = pedir(
    "PATCH",
    f"/api/v1/items/{item_id}/",
    {"price": "249.90", "name": f"{nome_item} atualizado"},
    token=admin_token,
)
check("PATCH item como admin (200)", status == 200, f"-> {status}")

status, payload, headers = pedir("GET", f"/api/v1/items/{item_id}/", token=admin_token)
check(
    "detalhe apos PATCH (200, MISS = item:<id> invalidado)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)
check(
    "detalhe apos PATCH devolve o valor novo (sem dado obsoleto)",
    payload.get("price") == "249.90",
    f"-> {payload.get('price')}",
)

status, payload, headers = pedir("GET", caminho_lista, token=admin_token)
check(
    "listagem apos PATCH (200, MISS = lista invalidada)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)
nomes = [item["name"] for item in payload.get("results", [])]
check(
    "listagem apos PATCH reflete o novo nome",
    any("atualizado" in nome for nome in nomes),
    f"-> {len(nomes)} registro(s)",
)

# --- invalidação em create e delete -----------------------------------------
status, payload, _ = pedir(
    "POST",
    "/api/v1/items/",
    {
        "name": f"{nome_item} extra",
        "price": "99.90",
        "category": categoria_id,
    },
    token=admin_token,
)
check("POST item que invalida a listagem (201)", status == 201, f"-> {status}")
item_extra_id = payload["id"]

status, payload, headers = pedir("GET", caminho_lista, token=admin_token)
check(
    "listagem apos POST (200, MISS = lista invalidada)",
    status == 200 and headers.get("X-Cache") == "MISS",
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)
check(
    "listagem apos POST inclui o item novo",
    payload.get("count") == 2,
    f"-> count={payload.get('count')}",
)

status, payload, _ = pedir("GET", f"/api/v1/items/{item_extra_id}/", token=admin_token)
check("preenche cache do item extra (200, MISS)", status == 200)

status, _, _ = pedir("DELETE", f"/api/v1/items/{item_extra_id}/", token=admin_token)
check("DELETE item (204)", status == 204, f"-> {status}")

status, _, headers = pedir("GET", f"/api/v1/items/{item_extra_id}/", token=admin_token)
check(
    "detalhe apos DELETE (404, nada obsoleto em cache)",
    status == 404,
    f"-> {status} X-Cache={headers.get('X-Cache')}",
)

status, _, _ = pedir("DELETE", f"/api/v1/items/{item_id}/", token=admin_token)
status, _, _ = pedir("DELETE", f"/api/v1/categories/{categoria_id}/", token=admin_token)
check("limpeza dos dados do teste (204)", status == 204, f"-> {status}")

# --- métricas de eficácia ----------------------------------------------------
status, payload, _ = pedir("GET", "/api/v1/cache/stats/", token=admin_token)
check(
    "metricas como admin (200, hit_rate por endpoint)",
    status == 200
    and "endpoints" in payload
    and "itens:list" in payload["endpoints"]
    and "item:detalhe" in payload["endpoints"],
    f"-> {status}",
)
check(
    "metricas com hits e misses contabilizados",
    payload["total_hits"] > 0 and payload["total_misses"] > 0,
    f"-> hits={payload['total_hits']} misses={payload['total_misses']} "
    f"hit_rate={payload['hit_rate']}",
)
check(
    "metricas informam o TTL por endpoint",
    payload["endpoints"]["itens:list"]["ttl_segundos"] == 60
    and payload["endpoints"]["item:detalhe"]["ttl_segundos"] == 300,
    f"-> {payload['endpoints']['itens:list']['ttl_segundos']}/"
    f"{payload['endpoints']['item:detalhe']['ttl_segundos']}",
)

status, _, _ = pedir("GET", "/api/v1/cache/stats/", token=user_token)
check("metricas como user (403)", status == 403, f"-> {status}")

status, _, _ = pedir("GET", "/api/v1/cache/stats/")
check("metricas sem token (401)", status == 401, f"-> {status}")

status, payload, _ = pedir("POST", "/api/v1/cache/stats/", {}, token=admin_token)
check(
    "reset das metricas como admin (200, contadores zerados)",
    status == 200 and payload["total_lookups"] == 0,
    f"-> {status} lookups={payload['total_lookups']}",
)

sys.exit(relatorio.resultado("curto"))
