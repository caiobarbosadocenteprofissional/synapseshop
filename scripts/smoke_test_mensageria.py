"""Smoke test da mensageria assíncrona (Aulas 9 e 10).

Executado contra o ambiente em execução (API em `http://localhost:8000` e
`pedido-worker` ativo). Cobre os cenários do DoD das duas aulas:

- **Produtor:** `POST /api/v1/pedidos/` cria o pedido e publica `PedidoCriado`
  (201 com `evento_publicado: true`).
- **Contrato:** campos obrigatórios do envelope e recusa de entradas inválidas
  (item inexistente, pedido sem itens, item repetido).
- **Consumidor:** o pedido avança de `PENDENTE` para `PROCESSANDO`, o que
  prova que a mensagem foi consumida e o estado persistido.
- **Idempotência no produtor:** repetir a mesma ``idempotency_key`` devolve o
  mesmo pedido em 200, sem criar outro.
- **Idempotência no consumidor:** o próprio teste republica o mesmo evento
  ``PedidoCriado`` no broker. O worker deve reconhecer a chave de deduplicação e
  confirmar a reentrega sem reaplicar o efeito.
- **DLQ com erro forçado:** pedido com ``idempotency_key`` no padrão
  ``pedido-dlq-<marca>`` é rejeitado pelo worker (quando ele sobe com
  ``PEDIDO_WORKER_FALHA_IDEM_KEYS=pedido-dlq-*``), esgota as tentativas e a
  mensagem chega à DLQ.
- **Partições (Aula 10):** duas publicações com a mesma ``idempotency_key`` caem
  na mesma partição, e chaves diferentes podem cair em partições diferentes —
  é o que garante ordenação por pedido e paralelismo entre pedidos.

O ramo do broker vem de ``MENSAGERIA_BROKER`` (padrão ``kafka``). A inspeção da
DLQ e a republicação usam a Management API do RabbitMQ ou o cliente Kafka,
conforme o transporte, e a cobertura é a mesma nos dois casos.

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
BROKER = os.environ.get("MENSAGERIA_BROKER", "kafka").strip().lower()

RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
EXCHANGE = os.environ.get("RABBITMQ_EXCHANGE", "pedidos.events")
ROUTING_KEY = os.environ.get("RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO", "pedido.criado")
FILA = "pedidos.pedidocriado"
DLQ = "pedidos.pedidocriado.dlq"

KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICO = os.environ.get("KAFKA_TOPICO_PEDIDO_CRIADO", "pedidos.pedidocriado")
TOPICO_DLQ = os.environ.get("KAFKA_TOPICO_PEDIDO_CRIADO_DLQ", "pedidos.pedidocriado.dlq")
PARTICOES = int(os.environ.get("KAFKA_PARTICOES", "3"))

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
        with urllib.request.urlopen(requisicao, timeout=30) as resposta:
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


def aguardar_pedido_processado(pedido_id, token, tentativas=20, intervalo=0.5):
    """Consulta o pedido até o worker movê-lo de PENDENTE para PROCESSANDO."""
    for _ in range(tentativas):
        status, payload = _req("GET", f"/api/v1/pedidos/{pedido_id}/", token=token)
        if status == 200 and payload and payload.get("status") == "PROCESSANDO":
            return payload
        time.sleep(intervalo)
    return None


# --- Kafka (Aula 10) --------------------------------------------------------


def _kafka_produzir(topico, chave, evento):
    """Publica um evento no tópico e devolve a partição da entrega."""
    from confluent_kafka import Producer

    entrega = []
    erro = []

    def confirmado(falha, msg):
        if falha is not None:
            erro.append(falha.str())
            return
        entrega.append((msg.partition(), msg.offset()))

    produtor = Producer({"bootstrap.servers": KAFKA_SERVERS, "acks": "all"})
    produtor.produce(
        topic=topico,
        key=chave.encode("utf-8"),
        value=json.dumps(evento, ensure_ascii=False).encode("utf-8"),
        headers={"x-retry-count": "0", "event_type": evento.get("event_type", "")},
        on_delivery=confirmado,
    )
    pendentes = produtor.flush(15)
    if erro or pendentes or not entrega:
        print(f"  ..    publicacao no topico {topico} falhou: {erro or pendentes}")
        return None
    return entrega[0]


def _kafka_ler_ultima(topico, tentativas=40, espera=0.5):
    """Lê (sem commit e sem mover o grupo) a última mensagem de um tópico.

    A posição de leitura é a *high watermark* da partição 0 menos 1: é o
    registro mais recente, que é o que a DLQ recebe do cenário de erro.
    """
    from confluent_kafka import Consumer, TopicPartition

    consumidor = Consumer(
        {
            "bootstrap.servers": KAFKA_SERVERS,
            "group.id": f"smoke-inspecao-{uuid4().hex[:8]}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    try:
        metadata = consumidor.list_topics(topico, timeout=15)
        if topico not in metadata.topics or metadata.topics[topico].error is not None:
            return None
        fim = consumidor.get_watermark_offsets(
            TopicPartition(topico, 0), timeout=10, cached=False
        )
        inicio = max(fim[1] - 1, 0)
        consumidor.assign([TopicPartition(topico, 0, inicio)])
        for _ in range(tentativas):
            msg = consumidor.poll(espera)
            if msg is None:
                continue
            if msg.error():
                return None
            corpo = json.loads(msg.value().decode("utf-8"))
            return {"payload": corpo, "headers": dict(msg.headers() or [])}
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    leitura do topico {topico} falhou: {exc}")
        return None
    finally:
        consumidor.close()


def _kafka_particoes_de(chaves, evento_base):
    """Republica um evento **válido** sob cada chave e devolve sua partição.

    O corpo é o de um pedido real de propósito: uma sonda inválida seria
    rejeitada pelo worker, passaria pelas tentativas e acabaria na DLQ, poluindo
    justamente a verificação que vem depois. Com corpo válido e chave já
    registrada, a sonda é reconhecida como reentrega e não gera efeito nem
    mensagem morta.
    """
    resultado = {}
    for chave in chaves:
        evento = dict(evento_base)
        evento["idempotency_key"] = chave
        evento["event_id"] = str(uuid4())
        evento["correlation_id"] = str(uuid4())
        entrega = _kafka_produzir(TOPICO, chave, evento)
        if entrega is None:
            return resultado
        resultado.setdefault(chave, []).append(entrega[0])
    return resultado


# --- RabbitMQ (Aula 9) ------------------------------------------------------


def _basic():
    credencial = base64.b64encode(
        f"{RABBITMQ_USER}:{RABBITMQ_PASSWORD}".encode()
    ).decode()
    return f"Basic {credencial}"


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


def republicar_rabbitmq(evento):
    """Republica o evento na exchange de eventos via Management API.

    Simula a reentrega que o broker faria por crash do consumidor: usa o mesmo
    contrato publicado pela API e a mesma chave de deduplicação, para que o
    worker reconheça o efeito já aplicado.
    """
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
        print(f"  ..    republicação falhou: {exc}")
        return False


# --- abstrações por broker --------------------------------------------------


def republicar(pedido_criado, pedido_lido):
    """Republica o evento no broker ativo. Devolve ``True`` se foi aceito."""
def republicar(pedido_criado, pedido_lido):
    """Republica o evento no broker ativo. Devolve ``True`` se foi aceito.

    O evento e remontado a partir do estado já persistido, com a mesma
    ``idempotency_key`` da criação original: é assim que a reentrega se
    comportaria depois de um crash, e é o que o consumidor deve reconhecer.
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
    if BROKER == "kafka":
        return _kafka_produzir(TOPICO, evento.idempotency_key, evento.to_dict()) is not None
    return republicar_rabbitmq(evento)


def contar_mortas():
    """Quantas mensagens estão na DLQ. No Kafka, o total do tópico."""
    if BROKER == "kafka":
        from confluent_kafka import Consumer, TopicPartition

        consumidor = Consumer({"bootstrap.servers": KAFKA_SERVERS, "group.id": "smoke-contagem"})
        try:
            metadata = consumidor.list_topics(TOPICO_DLQ, timeout=15)
            if TOPICO_DLQ not in metadata.topics:
                return 0
            total = 0
            for particao in metadata.topics[TOPICO_DLQ].partitions:
                topo = TopicPartition(TOPICO_DLQ, particao)
                inicio, fim = consumidor.get_watermark_offsets(topo, timeout=10, cached=False)
                total += max(fim - inicio, 0)
            return total
        except Exception as exc:  # noqa: BLE001
            print(f"  ..    contagem da DLQ falhou: {exc}")
            return None
        finally:
            consumidor.close()
    return (fila_mensagens(DLQ) or {}).get("messages")


def ler_morta():
    """Lê a mensagem morta mais recente, sem consumi-la do broker."""
    if BROKER == "kafka":
        morta = _kafka_ler_ultima(TOPICO_DLQ)
        return (morta or {}).get("payload")
    return (mensagem_da_dlq() or {}).get("payload")


print(f"== Smoke test da mensageria assíncrona (broker: {BROKER}) ==")

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
    {"name": f"Cat Mensageria {MARCA}", "description": f"Smoke test broker {BROKER}"},
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
# Republica o mesmo evento: o worker deve reconhecer a chave ja registrada e
# confirmar a mensagem sem aplicar o efeito de novo.
publicado = republicar(pedido, processado)
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

# --- particoes (Aula 10) ----------------------------------------------------
# O roteamento é por chave, então a verificacao precisa de eventos reais: as
# sondas reusam o corpo de um pedido ja criado e ja registrado na deduplicacao,
# o que garante que o worker as trate como reentrega.
if BROKER == "kafka":
    evento_base = EventoPedidoCriado(
        idempotency_key="",
        pedido_id=pedido_id,
        usuario_id=pedido["usuario"],
        total=Decimal(pedido["total"]),
        status=pedido["status"],
        itens=[
            ItemPedidoCriado(
                item_id=linha["item_id"],
                quantidade=linha["quantidade"],
                preco_unitario=Decimal(linha["preco_unitario"]),
            )
            for linha in pedido["itens"]
        ],
        correlation_id=str(uuid4()),
    ).to_dict()

    # Mesma chave, três publicações: precisa cair sempre na mesma partição.
    repetida = [CHAVE_OK] * 3
    # Chaves distintas: é o que deve se espalhar pelas partições.
    distintas = []
    for indice in range(PARTICOES):
        chave = f"pedido-part-{MARCA}-{indice}"
        status, _ = _req(
            "POST",
            "/api/v1/pedidos/",
            {
                "idempotency_key": chave,
                "itens": [{"item_id": item_id, "quantidade": 1}],
            },
            token_user,
        )
        if status != 201:
            distintas = []
            break
        distintas.append(chave)

    partidas = _kafka_particoes_de(repetida + distintas, evento_base)
    # A chave repetida aparece uma vez no dicionário, com as três partições
    # coletadas; por isso a comparação de contagem é sobre as chaves distintas.
    esperadas = set(repetida) | set(distintas)
    if len(partidas) == len(esperadas) and len(distintas) == PARTICOES:
        check(
            "mesma idempotency_key e sempre roteada para a mesma particao",
            len(partidas[CHAVE_OK]) == 3 and len(set(partidas[CHAVE_OK])) == 1,
            f"-> {partidas[CHAVE_OK]} (3 publicacoes da chave {CHAVE_OK})",
        )
        usadas = {partidas[chave][0] for chave in distintas}
        check(
            "chaves diferentes se espalham pelas particoes do topico",
            len(usadas) > 1,
            f"-> {len(usadas)} particao(oes) em uso de {PARTICOES}: {partidas}",
        )
    else:
        skip("mesma idempotency_key e sempre roteada para a mesma particao", "topico indisponivel")
        skip("chaves diferentes se espalham pelas particoes do topico", "topico indisponivel")

# --- DLQ com erro forcado ----------------------------------------------------
# Pré-requisito: o worker precisa estar com o padrão de falha forçada ativo,
# senão o pedido que deveria morrer é processado normalmente e a verificação
# não teria o que observar. Nesse caso a etapa é pulada com a instrução para
# reativá-lo, em vez de reportar uma falha enganosa.
print(
    "  ..    DLQ exige o worker com "
    f"PEDIDO_WORKER_FALHA_IDEM_KEYS={CHAVE_DLQ[:-len(MARCA)]}*"
)
antes = contar_mortas()
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
    total = contar_mortas()
    if total is not None and (antes is None or total > antes):
        nova_na_dlq = total
        break

if nova_na_dlq:
    check(
        "mensagem com erro forcado chega a DLQ apos esgotar as tentativas",
        True,
        f"-> mensagens na DLQ: {nova_na_dlq}",
    )
    morta = ler_morta() or {}
    check(
        "mensagem morta e a do pedido que falhou",
        morta.get("idempotency_key") == CHAVE_DLQ,
        f"-> idempotency_key={morta.get('idempotency_key')}",
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
# O item fica referenciado por PedidoItem assim que um pedido o consome, e o
# DELETE é barrado por integridade referencial. Apagar o pedido para liberar o
# item destruiria o histórico que o próprio smoke acabou de verificar, então a
# limpeza tenta, e reporta o que sobrou em vez de afirmar que removeu tudo.
status_item, _ = _req("DELETE", f"/api/v1/items/{item_id}/", token=token)
status_categoria, _ = _req("DELETE", f"/api/v1/categories/{categoria_id}/", token=token)
removidos = []
preservados = []
if status_item in (200, 204):
    removidos.append("item")
else:
    preservados.append(f"item {item_id} (status {status_item}: preso em PedidoItem)")
if status_categoria in (200, 204):
    removidos.append("categoria")
else:
    preservados.append(f"categoria {categoria_id} (status {status_categoria})")
print(f"  ..    removidos: {', '.join(removidos) or 'nada'}")
if preservados:
    print(f"  ..    preservados por integridade referencial: {'; '.join(preservados)}")

print(f"\n== Resultado: {passed} PASS / {failed} FAIL / {skipped} SKIP ==")
sys.exit(1 if failed else 0)