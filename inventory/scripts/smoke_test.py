"""Smoke test do microsserviço de inventário (Aula 5, adaptado na Aula 6).

Valida os endpoints mínimos do FastAPI usando apenas a stdlib (`urllib`),
sem dependências extras. Útil para validar manualmente o serviço e como
base futura para a suíte automatizada de testes (Aula 12).

Desde a Aula 6 o estado é persistido no PostgreSQL, então o teste passa a
usar um SKU único por execução e remove o item criado ao final, mantendo
o banco íntegro entre execuções.

Uso:
    python smoke_test.py [--base http://localhost:8100]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from argparse import ArgumentParser, Namespace

BASE_URL = "http://localhost:8100"


class RawResponse:
    """Empacota o payload bruto de respostas não-JSON (ex.: HTML de /docs)."""

    def __init__(self, content: bytes | str) -> None:
        self.content = content.decode("utf-8") if isinstance(content, bytes) else content


def _request(
    method: str, path: str, *, data: dict | None = None
) -> tuple[int, object]:
    """Executa uma requisição e devolve `(status_code, payload)`.

    O payload é devolvido como `dict`/`list` (JSON) ou `RawResponse`
    para respostas não-JSON (ex.: html de /docs).
    """
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read()
    except urllib.error.HTTPError as exc:
        content = exc.read()
        return exc.code, RawResponse(content)

    decoded = content.decode("utf-8") if isinstance(content, bytes) else content
    try:
        return resp.status, json.loads(decoded)
    except json.JSONDecodeError:
        return resp.status, RawResponse(decoded)


def run(base: str = BASE_URL) -> int:
    global BASE_URL
    BASE_URL = base.rstrip("/")

    results: list[str] = []
    fails = 0

    def check(name: str, got: int, want: int, ok: bool = True) -> None:
        nonlocal fails
        status = "PASS" if ok and got == want else "FAIL"
        if status == "FAIL":
            fails += 1
        results.append(f"[{status}] {name}: {got} (esperado {want})")

    sku = f"SMK-{int(time.time())}"
    created_id: int | None = None

    try:
        # 1. Health
        code, payload = _request("GET", "/health")
        check("GET /health", code, 200, ok=payload.get("status") == "ok")

        # 2. OpenAPI / docs
        code, payload = _request("GET", "/docs")
        check("GET /docs", code, 200, ok=isinstance(payload, RawResponse))
        code, payload = _request("GET", "/openapi.json")
        check("GET /openapi.json", code, 200, ok="openapi" in payload)

        # 3. Lista (deve ser uma lista)
        code, payload = _request("GET", "/inventory/items")
        check("GET /inventory/items", code, 200, ok=isinstance(payload, list))

        # 4. Create (SKU único por execução)
        code, payload = _request(
            "POST", "/inventory/items",
            data={"sku": sku, "name": "Smoke Item", "quantity": 5},
        )
        check("POST /inventory/items", code, 201, ok=payload.get("sku") == sku)
        created_id = payload.get("id")

        # 5. Get by id
        code, payload = _request("GET", f"/inventory/items/{created_id}")
        check("GET /inventory/items/{id}", code, 200, ok=payload.get("quantity") == 5)

        # 6. Patch
        code, payload = _request(
            "PATCH", f"/inventory/items/{created_id}", data={"quantity": 3}
        )
        check("PATCH /inventory/items/{id}", code, 200, ok=payload.get("quantity") == 3)

        # 7. Not found
        code, _ = _request("GET", "/inventory/items/999999")
        check("GET /inventory/items/999999", code, 404)

        # 8. Validation error (422)
        code, _ = _request("POST", "/inventory/items", data={"quantity": -1})
        check("POST /inventory/items (quantity negativa)", code, 422)

        # 9. Ajuste de estoque (transação) — novo na Aula 6
        code, payload = _request(
            "PATCH", f"/inventory/items/{created_id}/stock", data={"delta": -2}
        )
        check(
            "PATCH /inventory/items/{id}/stock (delta negativo)",
            code,
            200,
            ok=payload.get("quantity") == 1,
        )
        code, _ = _request(
            "PATCH", f"/inventory/items/{created_id}/stock", data={"delta": -10}
        )
        check(
            "PATCH /inventory/items/{id}/stock (estoque insuficiente)",
            code,
            409,
        )
    finally:
        # 10. Delete (limpeza do item criado)
        if created_id is not None:
            code, _ = _request("DELETE", f"/inventory/items/{created_id}")
            check("DELETE /inventory/items/{id}", code, 204)

    print("\n".join(results))
    print(f"\nRESULTADO: {len(results) - fails}/{len(results)} PASS")
    return 0 if fails == 0 else 1


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = ArgumentParser(description="Smoke test do microsserviço de inventário.")
    parser.add_argument("--base", default=BASE_URL, help="URL base do serviço (padrão: %(default)s).")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args().base))