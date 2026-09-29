"""Benchmark de leitura da API para a avaliação de desempenho da Aula 8.

Ferramenta de medição (avaliação de desempenho exigida pelo DoD da Aula 8):
compara latência média, p95 e RPS **antes** e **depois** da introdução do
cache-aside. Usa apenas a stdlib (`urllib` + `threading`), no mesmo padrão do
smoke test da Aula 7, para não adicionar dependências ao projeto.

Exemplos:

    # baseline (cache desligado) e medido (cache ligado) na mesma imagem
    python scripts/bench_cache.py --path "/api/v1/items/?page_size=10"
    python scripts/bench_cache.py --path "/api/v1/items/1/" --requests 200 --concurrency 8

Observação: para medições acima de `THROTTLE_USER` (200/min na Aula 7) suba a
taxa via env do serviço `api` no Compose; o throttle conta como falha aqui.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BASE_URL = "http://localhost:8000"
ADMIN = {"username": "admin", "password": "admin"}


def _request(method, url, data=None, token=None, timeout=15):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as res:
        raw = res.read()
        return res.status, (json.loads(raw) if raw else None), dict(res.headers)


def login(base_url):
    status, payload, _ = _request("POST", f"{base_url}/api/v1/auth/token/", ADMIN)
    if status != 200 or "access" not in payload:
        sys.exit(f"Falha no login do benchmark (HTTP {status}): {payload}")
    return payload["access"]


def _measure_one(url, token, results):
    started = time.perf_counter()
    try:
        status, _, headers = _request("GET", url, token=token)
        elapsed = (time.perf_counter() - started) * 1000
        results.append((status, elapsed, headers.get("X-Cache", "-"), None))
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        results.append((exc.code, elapsed, "-", None))
    except Exception as exc:  # noqa: BLE001 - erro de rede entra no relatório
        elapsed = (time.perf_counter() - started) * 1000
        results.append((0, elapsed, "-", str(exc)))


def run_load(url, token, requests_qty, concurrency):
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_measure_one, url, token, results) for _ in range(requests_qty)
        ]
        for future in futures:
            future.result()
    wall_clock = time.perf_counter() - started

    latencies = sorted(item[1] for item in results)
    statuses = {}
    cache_states = {}
    errors = [item[3] for item in results if item[3]]

    for status, _, cache_state, _ in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        cache_states[cache_state] = cache_states.get(cache_state, 0) + 1

    p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95) - 1))

    return {
        "path": url,
        "requests": requests_qty,
        "concurrency": concurrency,
        "status_counts": statuses,
        "cache_header": cache_states,
        "errors": errors[:3],
        "latencia_media_ms": round(statistics.fmean(latencies), 2),
        "latencia_p50_ms": round(statistics.median(latencies), 2),
        "latencia_p95_ms": round(latencies[p95_index], 2),
        "latencia_min_ms": round(latencies[0], 2),
        "latencia_max_ms": round(latencies[-1], 2),
        "duracao_total_s": round(wall_clock, 3),
        "rps": round(requests_qty / wall_clock, 2) if wall_clock else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark de leitura (Aula 8).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--path", default="/api/v1/items/?page_size=10")
    parser.add_argument("--requests", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--label", default="")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    token = login(args.base_url)
    url = f"{args.base_url.rstrip('/')}{args.path}"

    for _ in range(args.warmup):
        _measure_one(url, token, [])

    report = run_load(url, token, args.requests, args.concurrency)
    if args.label:
        report["label"] = args.label

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)

    ok = set(report["status_counts"]) <= {"200"}
    return 0 if ok and not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
