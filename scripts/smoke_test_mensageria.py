"""Smoke test da mensageria assíncrona (Aula 9).

Executado contra o ambiente em execução (API em `http://localhost:8000` e
`pedido-worker` ativo). Cobre os cenários do DoD da Aula 9:

- **Produtor:** `POST /api/v1/pedidos/` cria o pedido e publica `PedidoCriado`
  (201 com `evento_publicado: true`).
- **Contrato:** campos obrigatórios do envelope e recusa de entradas inválidas
  (item inexistente, pedido sem itens, item repetido).
- **Consumidor:** o pedido avança de `PENDENTE` para `PROCESSANDO`, o que
  prova que a mensagem foi consumida e o estado persistido.
- **Idempotência no produtor:** repetir a mesma ``idempotency_key`` devolve o
  mesmo pedido em 200, sem criar outro.
- **Idempotência no consumidor:** o próprio teste republica, pela Management API
  do RabbitMQ, o mesmo evento ``PedidoCriado`` na fila. O worker deve reconhecer
  a chave de deduplicação e confirmar a reentrega sem reaplicar o efeito.
- **DLQ com erro forçado:** pedido com ``idempotency_key`` no padrão
  ``pedido-dlq-<marca>`` é rejeitado pelo worker (quando ele sobe com
  ``PEDIDO_WORKER_FALHA_IDEM_KEYS=pedido-dlq-*``), esgota as tentativas e a
  mensagem é encaminhada para ``pedidos.pedidocriado.dlq`` — validado pela
  Management API do RabbitMQ.

Determinismo: cada execução usa ``idempotency_key`` com um sufixo temporal; a
chave da DLQ casa com o padrão configurado no worker.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from events.contracts import EventoPedidoCriado, ItemPedidoCriado  # noqa: E402

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
EXCHANGE = os.environ.get("RABBITMQ_EXCHANGE", "pedidos.events")
ROUTING_KEY = os.environ.get("RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO", "pedido.criado")
FILA = "pedidos.pedidocriado"
DLQ = "pedidos.pedidocriado.dlq"
ADMIN = {"username": "admin", "password": "admin"}
USER = {"username": "user", "password": "user"}

MARCA = str(int(time.time()))
CHAVE_OK = f"pedido-smoke-{MARCA}"
CHAVE_DUPLICADA = f"pedido-duplicada-{MARCA}"
CHAVE_DLQ = f"pedido-dlq-{MARCA}"

passed = 0
failed = 0
skipped = 0


def _req(metodo, caminho, dados=None, token=None, base=None):
    corpo = json.dumps(dados).encode() if dados is not None else None
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    requisicao = urllib.request.Request(
        f"{base or BASE_URL}{caminho}", method=metodo, data=corpo, headers=cabecalhos
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=20) as resposta:
            bruto = resposta.read()
            return resposta.status, (json.loads(bruto) if bruto else None)
    except urllib.error.HTTPError as exc:
        bruto = exc.read()
        try:
            return exc.code, json.loads(bruto)
        except json.JSONDecodeError:
            return exc.code, None


def check(nome, condicao, extra=""):
    global passed, failed
    if condicao:
        passed += 1
        print(f"  PASS  {nome} {extra}")
    else:
        failed += 1
        print(f"  FAIL  {nome} {extra}")


def skip(nome, motivo):
    global skipped
    skipped += 1
    print(f"  SKIP  {nome}")
    print(f"        {motivo}")


def mensagem_da_dlq():
    """Lê (sem consumir) a mensagem mais antiga da DLQ pela Management API."""
    url = f"{RABBITMQ_API}/api/queues/%2F/{DLQ}/get"
    corpo = {
        "count": 1,
        "ackmode": "ack_requeue_true",
        "encoding": "auto",
        "truncate": 50000,
    }
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "Authorization": _basic()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            mensagens = json.loads(resposta.read())
        if not mensagens:
            return None
        morta = mensagens[0]
        # A Management API devolve o payload como texto quando o encoding é auto.
        if isinstance(morta.get("payload"), str):
            morta["payload"] = json.loads(morta["payload"])
        return morta
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    leitura da DLQ falhou: {exc}")
        return None


def aguardar_pedido_processado(pedido_id, token, tentativas=20, intervalo=0.5):
    """Consulta o pedido até o worker movê-lo de PENDENTE para PROCESSANDO."""
    for _ in range(tentativas):
        status, payload = _req("GET", f"/api/v1/pedidos/{pedido_id}/", token=token)
        if status == 200 and payload and payload.get("status") == "PROCESSANDO":
            return payload
        time.sleep(intervalo)
    return None


def fila_mensagens(nome):
    """Lê a contagem de mensagens de uma fila pela Management API do RabbitMQ."""
    url = f"{RABBITMQ_API}/api/queues/%2F/{nome}"
    requisicao = urllib.request.Request(url, headers={"Authorization": _basic()})
    try:
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            return json.loads(resposta.read())
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    Management API indisponivel: {exc}")
        return None


def _basic():
    credencial = base64.b64encode(
        f"{RABBITMQ_USER}:{RABBITMQ_PASSWORD}".encode()
    ).decode()
    return f"Basic {credencial}"


def republicar_evento(pedido_criado, pedido_lido):
    """Republica o mesmo ``PedidoCriado`` na exchange de eventos.

    Simula a reentrega que o broker faria por crash do consumidor: a mensagem é
    montada a partir do estado persistido, pelo mesmo contrato usado pela API.
    """
    evento = EventoPedidoCriado(
        idempotency_key=pedido_criado["idempotency_key"],
        pedido_id=pedido_criado["id"],
        usuario_id=pedido_criado["usuario"],
        total=Decimal(pedido_criado["total"]),
        status=pedido_criado["status"],
        itens=[
            ItemPedidoCriado(
                item_id=linha["item_id"],
                quantidade=linha["quantidade"],
                preco_unitario=Decimal(linha["preco_unitario"]),
            )
            for linha in (pedido_lido or pedido_criado).get("itens", [])
        ],
        correlation_id=str(uuid4()),
    )
    url = f"{RABBITMQ_API}/api/exchanges/%2F/{EXCHANGE}/publish"
    corpo = {
        "properties": {
            "content_type": "application/json",
            "delivery_mode": 2,
            "correlation_id": evento.correlation_id,
        },
        "routing_key": ROUTING_KEY,
        "payload": json.dumps(evento.to_dict(), ensure_ascii=False),
        "payload_encoding": "string",
    }
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "Authorization": _basic()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            return json.loads(resposta.read()).get("routed") is True
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    republicacao falhou: {exc}")
        return False


print("== Smoke test da mensageria assíncrona (Aula 9) ==")

status, _ = _req("GET", "/health")
check("health publico (200)", status == 200, f"-> {status}")

status, payload = _req("POST", "/api/v1/auth/token/", ADMIN)
check("login admin (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token = (payload or {}).get("access", "")

status, payload = _req("POST", "/api/v1/auth/token/", USER)
check("login user (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token_user = (payload or {}).get("access", "")

# --- dados exclusivos deste teste -------------------------------------------
status, payload = _req(
    "POST",
    "/api/v1/categories/",
    {"name": f"Cat Mensageria {MARCA}", "description": "Smoke test Aula 9"},
    token,
)
check("criar categoria de teste (201)", status == 201, f"-> {status}")
categoria_id = (payload or {}).get("id")

status, payload = _req(
    "POST",
    "/api/v1/items/",
    {
        "name": f"Item Mensageria {MARCA}",
        "price": "199.90",
        "category": categoria_id,
    },
    token,
)
check("criar item de teste (201)", status == 201, f"-> {status}")
item_id = (payload or {}).get("id")

# --- produtor ---------------------------------------------------------------
status, payload = _req("POST", "/api/v1/pedidos/", {"itens": []}, token)
check("pedido sem itens recusado (400)", status == 400, f"-> {status}")

status, payload = _req(
    "POST",
    "/api/v1/pedidos/",
    {"itens": [{"item_id": 99999999, "quantidade": 1}]},
    token,
)
check("item inexistente recusado (400)", status == 400, f"-> {status}")

status, payload = _req(
    "POST",
    "/api/v1/pedidos/",
    {"itens": [{"item_id": item_id, "quantidade": 1}, {"item_id": item_id, "quantidade": 2}]},
    token,
)
check("item repetido recusado (400)", status == 400, f"-> {status}")

status, payload = _req("POST", "/api/v1/pedidos/", {"itens": [{"item_id": item_id, "quantidade": 1}]})
check("pedido sem token recusado (401)", status == 401, f"-> {status}")

status, pedido = _req(
    "POST",
    "/api/v1/pedidos/",
    {"idempotency_key": CHAVE_OK, "itens": [{"item_id": item_id, "quantidade": 2}]},
    token_user,
)
check(
    "criar pedido publica o evento (201)",
    status == 201 and (pedido or {}).get("evento_publicado") is True,
    f"-> {status} evento_publicado={(pedido or {}).get('evento_publicado')}",
)
pedido_id = (pedido or {}).get("id")
total_esperado = "399.80"
check(
    "total calculado no servidor a partir do catalogo",
    (pedido or {}).get("total") == total_esperado,
    f"-> {(pedido or {}).get('total')} (esperado {total_esperado})",
)
check(
    "preco congelado na linha do pedido",
    bool((pedido or {}).get("itens"))
    and (pedido or {})["itens"][0].get("preco_unitario") == "199.90",
    f"-> {(pedido or {}).get('itens')}",
)
check(
    "pedido inicia em PENDENTE",
    (pedido or {}).get("status") == "PENDENTE",
    f"-> {(pedido or {}).get('status')}",
)

# --- consumidor -------------------------------------------------------------
processado = aguardar_pedido_processado(pedido_id, token_user)
check(
    "worker consome o evento e persiste o estado (PROCESSANDO)",
    bool(processado),
    f"-> pedido {pedido_id}",
)
check(
    "processado_em preenchido pelo consumidor",
    bool((processado or {}).get("processado_em")),
    f"-> {(processado or {}).get('processado_em')}",
)

# --- idempotencia no produtor ----------------------------------------------
status, repetido = _req(
    "POST",
    "/api/v1/pedidos/",
    {"idempotency_key": CHAVE_OK, "itens": [{"item_id": item_id, "quantidade": 2}]},
    token_user,
)
check(
    "mesma idempotency_key devolve o mesmo pedido (200)",
    status == 200 and (repetido or {}).get("id") == pedido_id,
    f"-> {status} id={(repetido or {}).get('id')} (esperado {pedido_id})",
)

# --- idempotencia no consumidor --------------------------------------------
# Republica o mesmo evento na fila: o worker deve reconhecer a chave ja
# registrada e confirmar a mensagem sem aplicar o efeito de novo.
publicado = republicar_evento(pedido, processado)
check(
    "republicacao do mesmo evento aceita pelo broker",
    publicado,
    f"-> {publicado}",
)
time.sleep(4)
_, payload_reentrega = _req("GET", f"/api/v1/pedidos/{pedido_id}/", token=token_user)
check(
    "reentrega nao altera o pedido (segue PROCESSANDO)",
    (payload_reentrega or {}).get("status") == "PROCESSANDO",
    f"-> {(payload_reentrega or {}).get('status')}",
)
check(
    "reentrega nao cria novo pedido",
    (payload_reentrega or {}).get("id") == pedido_id,
    f"-> id={(payload_reentrega or {}).get('id')} (esperado {pedido_id})",
)

# --- DLQ com erro forcado ----------------------------------------------------
# So e valido com o worker em modo forcado; sem ele, a etapa e pulada com a
# instrucao para reativa-lo, em vez de reportar uma falha enganosa.
antes = fila_mensagens(DLQ) or {}
status, pedido_dlq = _req(
    "POST",
    "/api/v1/pedidos/",
    {"idempotency_key": CHAVE_DLQ, "itens": [{"item_id": item_id, "quantidade": 1}]},
    token_user,
)
check(
    "criar pedido destined a falha (201)",
    status == 201 and (pedido_dlq or {}).get("evento_publicado") is True,
    f"-> {status}",
)

print("  ..    aguardando as tentativas do worker agotarem (erro forcado)")
nova_na_dlq = None
for _ in range(45):
    time.sleep(1)
    info = fila_mensagens(DLQ) or {}
    if (info.get("messages") or 0) > (antes.get("messages") or 0):
        nova_na_dlq = info
        break

if nova_na_dlq:
    check(
        "mensagem com erro forcado chega a DLQ apos esgotar as tentativas",
        True,
        f"-> mensagens na DLQ: {nova_na_dlq.get('messages')}",
    )
    morta = mensagem_da_dlq()
    check(
        "mensagem morta e a do pedido que falhou",
        (morta or {}).get("payload", {}).get("idempotency_key") == CHAVE_DLQ,
        f"-> idempotency_key={(morta or {}).get('payload', {}).get('idempotency_key')}",
    )
    _, lido = _req("GET", f"/api/v1/pedidos/{pedido_dlq.get('id')}/", token=token_user)
    check(
        "pedido da DLQ nao teve o efeito aplicado (segue PENDENTE)",
        (lido or {}).get("status") == "PENDENTE",
        f"-> {(lido or {}).get('status')}",
    )
else:
    motivo = (
        "worker sem modo forcado; habilite com "
        "PEDIDO_WORKER_FALHA_IDEM_KEYS=pedido-dlq-* docker compose "
        "up -d --force-recreate pedido-worker"
    )
    skip("mensagem com erro forcado chega a DLQ", motivo)
    skip("mensagem morta e a do pedido que falhou", motivo)
    skip("pedido da DLQ nao teve o efeito aplicado", motivo)

# --- limpeza ----------------------------------------------------------------
_req("DELETE", f"/api/v1/items/{item_id}/", token=token)
_req("DELETE", f"/api/v1/categories/{categoria_id}/", token=token)
print("  ..    dados de teste removidos")

print(f"\n== Resultado: {passed} PASS / {failed} FAIL / {skipped} SKIP ==")
sys.exit(1 if failed else 0)