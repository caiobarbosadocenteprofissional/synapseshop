"""Smoke test da camada de autenticação JWT e segurança mínima (Aula 7).

Executado contra a API em execução (ex.: `manage.py runserver` local ou
`http://localhost:8000` via Docker). Cobre os cenários do DoD:

- Login admin/user com sucesso (200) e credencial inválida (401).
- Acesso negado: GET sem token (401) e escrita sem papel admin (403).
- Rotas administrativas (escrita) funcionando para admin (201/204).
- Paginação e filtros nos endpoints críticos (200).
- Throttling escopado em `login` (429 após a taxa `THROTTLE_LOGIN`).
"""

import json
import sys
import urllib.error
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ADMIN = {"username": "admin", "password": "admin"}
USER = {"username": "user", "password": "user"}

passed = 0
failed = 0


def _req(method, path, data=None, token=None):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE_URL}{path}", method=method, data=body, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload


def check(name, condition, extra=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name} {extra}")
    else:
        failed += 1
        print(f"  FAIL  {name} {extra}")


print("== Smoke test autenticação JWT (Aula 7) ==")

status, _ = _req("GET", "/health")
check("health publico (200)", status == 200, f"-> {status}")

status, payload = _req("POST", "/api/v1/auth/token/", ADMIN)
check(
    "login admin (200, access/refresh/role)",
    status == 200
    and "access" in payload
    and "refresh" in payload
    and payload.get("role") == "admin",
    f"-> {status}",
)
admin_token = payload["access"]
admin_refresh = payload["refresh"]

status, payload = _req("POST", "/api/v1/auth/token/", USER)
check(
    "login user (200, role=user)",
    status == 200 and payload.get("role") == "user",
    f"-> {status}",
)
user_token = payload["access"]

status, payload = _req("POST", "/api/v1/auth/token/", {"username": "admin", "password": "errada"})
check("login invalido (401)", status == 401, f"-> {status}")

status, payload = _req("POST", "/api/v1/auth/token/refresh/", {"refresh": admin_refresh})
check(
    "refresh token (200, access/role)",
    status == 200
    and "access" in payload
    and payload.get("role") == "admin",
    f"-> {status}",
)

status, _ = _req("GET", "/api/v1/categories/")
check("GET lista sem token (401)", status == 401, f"-> {status}")

status, payload = _req("GET", "/api/v1/categories/", token=admin_token)
check(
    "GET categorias autenticado paginado (200)",
    status == 200 and "results" in payload and "count" in payload,
    f"-> {status}",
)

status, payload = _req(
    "POST",
    "/api/v1/categories/",
    {"name": "Eletronicos", "description": "Produtos eletronicos"},
    token=admin_token,
)
check("POST categoria como admin (201)", status == 201, f"-> {status}")
category_id = payload["id"]

status, payload = _req(
    "POST",
    "/api/v1/categories/",
    {"name": "Proibido", "description": "Sem permissao"},
    token=user_token,
)
check("POST categoria como user (403)", status == 403, f"-> {status}")

status, payload = _req(
    "POST",
    "/api/v1/items/",
    {"name": "Notebook", "price": "4999.90", "category": category_id, "is_active": True},
    token=admin_token,
)
check("POST item como admin (201)", status == 201, f"-> {status}")

status, payload = _req(
    "GET",
    f"/api/v1/items/?category={category_id}&is_active=true&search=Notebook&ordering=price",
    token=admin_token,
)
check(
    "GET itens com filtros/paginação (200)",
    status == 200 and len(payload["results"]) >= 1,
    f"-> {status}",
)

status, _ = _req("DELETE", f"/api/v1/categories/{category_id}/", token=admin_token)
check("DELETE categoria como admin (204)", status == 204, f"-> {status}")

throttled = None
for _ in range(12):
    status, _ = _req("POST", "/api/v1/auth/token/", USER)
    if status == 429:
        throttled = True
        break
check("throttling login (429)", throttled is True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)