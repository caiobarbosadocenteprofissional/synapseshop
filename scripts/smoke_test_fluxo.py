"""Smoke test do fluxo completo da Aula 11 (criar ➔ pagar ➔ notificar).

Executado contra o ambiente em execução: API em ``http://localhost:8000``,
``pedido-worker`` e ``notificacao-worker`` ativos. Cobre os cenários do DoD:

1. **Saúde** — ``/health`` (liveness) e ``/health/pronto`` (readiness) com as três
   dependências verificadas.
2. **Caminho feliz** — ``POST /api/v1/pedidos/`` publica ``PedidoCriado`` e o
   ``pedido-worker`` move o pedido para ``PROCESSANDO``; ``POST
   /api/v1/pedidos/<id>/pagamento/`` grava o pagamento, move o pedido para ``PAGO``
   e publica ``PagamentoProcessado``; o ``notificacao-worker`` grava a
   ``Notificacao`` e publica ``NotificacaoEnviada``, observável em ``GET
   /api/v1/notificacoes/``.
3. **Cache do pedido** — o detalhe responde ``X-Cache: MISS`` na primeira leitura e
   ``HIT`` na segunda, e a **invalidação** aparece como um novo ``MISS`` com o
   estado novo depois que o pagamento muda o pedido. É a prova de que cache e
   mensageria estão integrados: quem invalida é o processo que grava, e o cache é
   compartilhado.
4. **Idempotência do pagamento** — repetir o pagamento devolve **200** com o mesmo
   registro e **não** cria segunda notificação (unicidade é do banco, não de uma
   condição no código).
5. **Caminho negativo** — pagamento ``RECUSADO`` move o pedido para ``CANCELADO`` e
   **não** gera notificação.
6. **Contrato e autorização** — ``resultado`` inválido recusado com 400, pagamento de
   pedido inexistente e de pedido de outro usuário com 404.
7. **Métricas do cache** — ``GET /api/v1/cache/stats/`` inclui ``pedido:detalhe``.
8. **DLQ do segundo elo (opcional, duas fases)** — a falha forçada do
   ``notificacao-worker`` é escolhida por ``pedido:<id>``, e o id do pagamento só
   existe **depois** que a API o grava. Por isso o cenário tem duas execuções: a
   primeira cria um pedido-sonda e imprime o id; a segunda roda com
   ``PEDIDO_DLQ_ALVO=<id>`` e o worker já subido com
   ``NOTIFICACAO_WORKER_FALHA_IDEM_KEYS=pedido:<id>``, e então o pagamento esgota
   as tentativas, chega à DLQ e **não** gera notificação. Sem a segunda fase, os
   casos são marcados como SKIP.

Determinismo: cada execução usa ``idempotency_key`` com sufixo temporal, e as
esperas são por condição (o estado desejado aparece) e não por tempo fixo.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
BROKER = os.environ.get("MENSAGERIA_BROKER", "kafka").strip().lower()

# Inspeção da DLQ do segundo elo, no broker ativo.
RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
FILA_DLQ = os.environ.get(
    "RABBITMQ_FILA_PAGAMENTO_PROCESSADO_DLQ", "pagamentos.pagamentoprocessado.dlq"
)
KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICO_DLQ = os.environ.get(
    "KAFKA_TOPICO_PAGAMENTO_PROCESSADO_DLQ", "pagamentos.pagamentoprocessado.dlq"
)

ADMIN = {"username": "admin", "password": "admin"}
USER = {"username": "user", "password": "user"}

MARCA = str(int(time.time()))
CHAVE_APROVADO = f"pedido-fluxo-aprovado-{MARCA}"
CHAVE_RECUSADO = f"pedido-fluxo-recusado-{MARCA}"
CHAVE_DLQ = f"pedido-dlq-fluxo-{MARCA}"

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
            cabecalhos_resposta = dict(resposta.headers)
            return (
                resposta.status,
                (json.loads(bruto) if bruto else None),
                cabecalhos_resposta,
            )
    except urllib.error.HTTPError as exc:
        bruto = exc.read()
        try:
            return exc.code, json.loads(bruto), dict(exc.headers)
        except json.JSONDecodeError:
            return exc.code, None, dict(exc.headers)


def _header(cabecalhos, nome):
    """Header sem depender da grafia: HTTP não diferencia maiúsculas."""
    if not cabecalhos:
        return None
    alvo = nome.lower()
    for chave, valor in cabecalhos.items():
        if chave.lower() == alvo:
            return valor
    return None


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


def aguardar_status(pedido_id, token, desejado, tentativas=30, intervalo=0.5):
    """Consulta o pedido até ele alcançar um dos estados desejados.

    Espera por condição, e não por tempo fixo: o worker é assíncrono e o tempo
    total varia com a fila, com o rebalanceamento do grupo e com o clock.
    """
    for _ in range(tentativas):
        status, payload, _ = _req("GET", f"/api/v1/pedidos/{pedido_id}/", token=token)
        if status == 200 and payload and payload.get("status") in desejado:
            return payload
        time.sleep(intervalo)
    return None


def aguardar_notificacao(pedido_id, token, tentativas=30, intervalo=0.5):
    """Aguarda a notificação do pedido aparecer em ``GET /api/v1/notificacoes/``."""
    for _ in range(tentativas):
        status, payload, _ = _req("GET", "/api/v1/notificacoes/?page_size=50", token=token)
        resultados = (payload or {}).get("results") or []
        for linha in resultados:
            if linha.get("pedido") == pedido_id:
                return linha
        time.sleep(intervalo)
    return None


def contar_notificacoes(pedido_id, token):
    status, payload, _ = _req("GET", "/api/v1/notificacoes/?page_size=50", token=token)
    if status != 200:
        return None
    return len([n for n in (payload or {}).get("results") or [] if n.get("pedido") == pedido_id])


def criar_pedido(token, item_id, chave):
    status, payload, _ = _req(
        "POST",
        "/api/v1/pedidos/",
        {"idempotency_key": chave, "itens": [{"item_id": item_id, "quantidade": 2}]},
        token,
    )
    return status, payload


# --- contagem da DLQ do segundo elo -------------------------------------------


def contar_mortas():
    """Quantas mensagens estão na DLQ de ``PagamentoProcessado``."""
    if BROKER == "kafka":
        from confluent_kafka import Consumer, TopicPartition

        consumidor = Consumer({"bootstrap.servers": KAFKA_SERVERS, "group.id": "smoke-fluxo"})
        try:
            metadata = consumidor.list_topics(TOPICO_DLQ, timeout=15)
            if TOPICO_DLQ not in metadata.topics:
                return 0
            total = 0
            for particao in metadata.topics[TOPICO_DLQ].partitions:
                marca = TopicPartition(TOPICO_DLQ, particao)
                inicio, fim = consumidor.get_watermark_offsets(marca, timeout=10, cached=False)
                total += max(fim - inicio, 0)
            return total
        except Exception as exc:  # noqa: BLE001
            print(f"  ..    contagem da DLQ falhou: {exc}")
            return None
        finally:
            consumidor.close()

    import base64

    requisicao = urllib.request.Request(f"{RABBITMQ_API}/api/queues/%2F/{FILA_DLQ}")
    cabecalhos = {
        "Authorization": "Basic "
        + base64.b64encode(f"{RABBITMQ_USER}:{RABBITMQ_PASSWORD}".encode()).decode()
    }
    requisicao.add_header(*list(cabecalhos.items())[0])
    try:
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            return json.loads(resposta.read()).get("messages")
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    contagem da DLQ falhou: {exc}")
        return None


# --- início -------------------------------------------------------------------


print(f"== Smoke test do fluxo da Aula 11 (broker: {BROKER}) ==")

status, payload, _ = _req("GET", "/health")
check("liveness /health (200)", status == 200 and (payload or {}).get("status") == "ok", f"-> {status}")

status, payload, _ = _req("GET", "/health/pronto")
pronto = (payload or {}).get("pronto")
check("readiness /health/pronto (200)", status == 200 and pronto, f"-> {status}")
dependencias = (payload or {}).get("dependencias") or {}
check(
    "readiness verificou postgres, redis e broker",
    all(dependencias.get(nome, {}).get("ok") for nome in ("postgresql", "redis", "broker")),
    f"-> {list(dependencias)}",
)

status, payload, _ = _req("POST", "/api/v1/auth/token/", ADMIN)
check("login admin (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token = (payload or {}).get("access", "")

status, payload, _ = _req("POST", "/api/v1/auth/token/", USER)
check("login user (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token_user = (payload or {}).get("access", "")

# --- dados exclusivos deste teste ---------------------------------------------

status, payload, _ = _req(
    "POST",
    "/api/v1/categories/",
    {"name": f"Cat Fluxo {MARCA}", "description": "Smoke test do fluxo da Aula 11"},
    token,
)
check("criar categoria de teste (201)", status == 201, f"-> {status}")
categoria_id = (payload or {}).get("id")

status, payload, _ = _req(
    "POST",
    "/api/v1/items/",
    {"name": f"Item Fluxo {MARCA}", "price": "89.90", "category": categoria_id},
    token,
)
check("criar item de teste (201)", status == 201, f"-> {status}")
item_id = (payload or {}).get("id")

# --- 1. criação do pedido (produtor de PedidoCriado) --------------------------

status, pedido_aprovado = criar_pedido(token_user, item_id, CHAVE_APROVADO)
check("criar pedido (201)", status == 201, f"-> {status}")
check("pedido criado com evento publicado", (pedido_aprovado or {}).get("evento_publicado") is True)
check(
    "pedido criado com correlation_id",
    bool((pedido_aprovado or {}).get("correlation_id")),
    f"-> {(pedido_aprovado or {}).get('correlation_id')}",
)
check("pedido nasce PENDENTE", (pedido_aprovado or {}).get("status") == "PENDENTE")
pedido_aprovado_id = (pedido_aprovado or {}).get("id")

# --- 2. cache do detalhe do pedido --------------------------------------------
# A primeira leitura vem logo após a criação, antes de qualquer espera: a espera
# por `PROCESSANDO` consulta o mesmo detalhe e portanto aquece o cache, o que
# faria o primeiro `MISS` ser falso.

status, primeira_leitura, cabecalhos = _req(
    "GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user
)
check(
    "detalhe do pedido: MISS na primeira leitura",
    _header(cabecalhos, "X-Cache") == "MISS",
    f"-> {_header(cabecalhos, 'X-Cache')}",
)
check(
    "detalhe do pedido: cache devolve o registro persistido",
    (primeira_leitura or {}).get("id") == pedido_aprovado_id
    and (primeira_leitura or {}).get("total") == (pedido_aprovado or {}).get("total")
    and len((primeira_leitura or {}).get("itens") or []) == 1,
    f"-> status {(primeira_leitura or {}).get('status')}",
)

status, _, cabecalhos = _req("GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user)
check(
    "detalhe do pedido: HIT na segunda leitura",
    _header(cabecalhos, "X-Cache") == "HIT",
    f"-> {_header(cabecalhos, 'X-Cache')}",
)

# --- 3. consumo de PedidoCriado e invalidação pelo pedido-worker --------------

processando = aguardar_status(pedido_aprovado_id, token_user, {"PROCESSANDO"})
check("pedido-worker consumiu PedidoCriado (PROCESSANDO)", processando is not None)

# Assenta a invalidação do worker antes de medir a próxima: sem esta pausa, um
# MISS posterior poderia ser atribuído à invalidação atrasada do PROCESSANDO e o
# teste "provaria" a invalidação do pagamento sem que ela tivesse ocorrido.
time.sleep(2.0)
_req("GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user)
status, _, cabecalhos = _req("GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user)
check(
    "cache do detalhe reconecta em HIT antes do pagamento",
    _header(cabecalhos, "X-Cache") == "HIT",
    f"-> {_header(cabecalhos, 'X-Cache')}",
)

# --- 4. pagamento aprovado ----------------------------------------------------

status, pagamento, _ = _req(
    "POST", f"/api/v1/pedidos/{pedido_aprovado_id}/pagamento/", {}, token_user
)
check("pagamento criado (201)", status == 201, f"-> {status}")
check("pagamento APROVADO", (pagamento or {}).get("status") == "APROVADO")
check("pagamento publicado como evento", (pagamento or {}).get("evento_publicado") is True)
check("pagamento tem referencia de transacao", bool((pagamento or {}).get("referencia")))
pagamento_id = (pagamento or {}).get("id")
valor_pagamento = (pagamento or {}).get("valor")
total_pedido = (pedido_aprovado or {}).get("total")
check("valor do pagamento e o total do pedido", valor_pagamento == total_pedido, f"-> {valor_pagamento} vs {total_pedido}")

# --- 5. invalidação do cache pela gravação do pagamento ------------------------
# Esta leitura vem antes de qualquer outra consulta ao detalhe: entre o pagamento
# e ela não há nada que requente o cache, então o `MISS` só pode ser a chave que
# quem gravou o pagamento apagou. O `PAGO` no corpo confirma que o valor guardado
# antes (PROCESSANDO) não sobreviveu.

status, pedido_pago, cabecalhos = _req(
    "GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user
)
check(
    "cache invalidado pela gravação do pagamento (novo MISS)",
    _header(cabecalhos, "X-Cache") == "MISS",
    f"-> {_header(cabecalhos, 'X-Cache')}",
)
check(
    "detalhe reflete o pagamento (nao veio do cache antigo)",
    (pedido_pago or {}).get("status") == "PAGO"
    and ((pedido_pago or {}).get("pagamento") or {}).get("id") == pagamento_id,
    f"-> {(pedido_pago or {}).get('status')} / {((pedido_pago or {}).get('pagamento') or {}).get('id')}",
)
check("pedido vai a PAGO no mesmo passo do pagamento", (pedido_pago or {}).get("status") == "PAGO")

# --- 6. notificação (consumidor de PagamentoProcessado) -----------------------

notificacao = aguardar_notificacao(pedido_aprovado_id, token_user)
check("notificacao-worker gerou a notificacao", notificacao is not None)
if notificacao:
    check(
        "notificacao ligada ao pagamento",
        notificacao.get("pagamento") == pagamento_id,
        f"-> {notificacao.get('pagamento')}",
    )
    check("notificacao tem assunto e conteudo", bool(notificacao.get("assunto")) and bool(notificacao.get("conteudo")))
    check("notificacao tem destino", bool(notificacao.get("destinatario")), f"-> {notificacao.get('destinatario')}")

# --- 7. o detalhe reflete o que o worker gravou -------------------------------
# A notificação é escrita pelo `notificacao-worker`, em outro processo, e é ela que
# invalida a chave. A leitura abaixo pode ser `MISS` (a chave foi apagada depois do
# `MISS` acima) ou `HIT` (a notificação foi gravada antes daquela leitura e nada
# mais consultou o detalhe); o que não pode acontecer é o corpo vir sem a
# notificação, porque isso seria o cache servindo estado velho depois da escrita.

status, pedido_cache, cabecalhos = _req(
    "GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user
)
check(
    "detalhe reflete a notificacao gravada pelo worker",
    len((pedido_cache or {}).get("notificacoes") or []) == 1,
    f"-> X-Cache {_header(cabecalhos, 'X-Cache')}, "
    f"{len((pedido_cache or {}).get('notificacoes') or [])} notificacao(oes)",
)

status, _, cabecalhos = _req("GET", f"/api/v1/pedidos/{pedido_aprovado_id}/", token=token_user)
check("cache volta a HIT apos o preenchimento", _header(cabecalhos, "X-Cache") == "HIT", f"-> {_header(cabecalhos, 'X-Cache')}")

# --- 8. idempotência do pagamento (um pagamento por pedido) -------------------

antes = contar_notificacoes(pedido_aprovado_id, token_user)
status, repetido, cabecalhos = _req(
    "POST", f"/api/v1/pedidos/{pedido_aprovado_id}/pagamento/", {}, token_user
)
check("repetir pagamento devolve 200", status == 200, f"-> {status}")
check(
    "repetir pagamento devolve o mesmo pagamento",
    (repetido or {}).get("id") == pagamento_id,
    f"-> {(repetido or {}).get('id')} vs {pagamento_id}",
)
check("repetir pagamento nao publica evento novo", (repetido or {}).get("evento_publicado") is False)
time.sleep(1.5)
depois = contar_notificacoes(pedido_aprovado_id, token_user)
check("repetir pagamento nao duplica notificacao", antes == depois, f"-> {antes} vs {depois}")

status, repetido_outro, _ = _req(
    "POST",
    f"/api/v1/pedidos/{pedido_aprovado_id}/pagamento/",
    {"resultado": "RECUSADO"},
    token_user,
)
check(
    "resultado diferente no repetido nao troca o pagamento",
    (repetido_outro or {}).get("status") == "APROVADO",
    f"-> {(repetido_outro or {}).get('status')}",
)

# --- 9. caminho negativo: pagamento recusado ----------------------------------

status, pedido_recusado = criar_pedido(token_user, item_id, CHAVE_RECUSADO)
check("criar pedido para recusa (201)", status == 201, f"-> {status}")
pedido_recusado_id = (pedido_recusado or {}).get("id")

status, _, cabecalhos = _req("GET", f"/api/v1/pedidos/{pedido_recusado_id}/", token=token_user)
check(
    "detalhe do pedido recusado: MISS inicial",
    _header(cabecalhos, "X-Cache") == "MISS",
    f"-> {_header(cabecalhos, 'X-Cache')}",
)
check(
    "pedido-worker consumiu o segundo PedidoCriado",
    aguardar_status(pedido_recusado_id, token_user, {"PROCESSANDO"}) is not None,
)

status, pagamento_recusado, _ = _req(
    "POST",
    f"/api/v1/pedidos/{pedido_recusado_id}/pagamento/",
    {"resultado": "RECUSADO", "forma_pagamento": "pix"},
    token_user,
)
check("pagamento recusado criado (201)", status == 201, f"-> {status}")
check("pagamento RECUSADO", (pagamento_recusado or {}).get("status") == "RECUSADO")
check(
    "forma de pagamento registrada",
    (pagamento_recusado or {}).get("forma_pagamento") == "pix",
)

cancelado = aguardar_status(pedido_recusado_id, token_user, {"CANCELADO"})
check("pedido recusado vai a CANCELADO", cancelado is not None)

time.sleep(2.0)
check(
    "pagamento recusado nao gera notificacao",
    contar_notificacoes(pedido_recusado_id, token_user) == 0,
)

# --- 10. contrato e autorização ------------------------------------------------

status, payload, _ = _req(
    "POST", f"/api/v1/pedidos/{pedido_aprovado_id}/pagamento/", {"resultado": "PIXADO"}, token_user
)
check("resultado invalido recusado (400)", status == 400, f"-> {status}")

status, payload, _ = _req("POST", "/api/v1/pedidos/99999999/pagamento/", {}, token_user)
check("pagamento de pedido inexistente (404)", status == 404, f"-> {status}")

status, payload, _ = _req("POST", f"/api/v1/pedidos/{pedido_aprovado_id}/pagamento/", {}, token)
check(
    "admin alcança o pagamento do pedido de outro usuario",
    status == 200 and (payload or {}).get("id") == pagamento_id,
    f"-> {status} (devolve o pagamento existente, sem evento novo)",
)

status, _, cabecalhos = _req("GET", f"/api/v1/pedidos/{pedido_aprovado_id}/")
check("detalhe sem token (401/403)", status in (401, 403), f"-> {status}")

# --- 11. métricas do cache ----------------------------------------------------

status, payload, _ = _req("GET", "/api/v1/cache/stats/", token=token)
endpoints = (payload or {}).get("endpoints") or {}
check(
    "metricas incluem o detalhe do pedido",
    status == 200 and "pedido:detalhe" in endpoints,
    f"-> {list(endpoints)}",
)
if "pedido:detalhe" in endpoints:
    stat = endpoints["pedido:detalhe"]
    check(
        "hit rate do detalhe do pedido é coerente",
        stat["hits"] >= 2 and stat["misses"] >= 2,
        f"-> hits={stat['hits']} misses={stat['misses']} ttl={stat['ttl_segundos']}s",
    )

# --- 12. DLQ do segundo elo (erro forcado) ------------------------------------
# O id do pagamento — a chave que o worker casa com o padrão — só existe depois
# que a API grava o pagamento, então o cenário é em duas fases: a primeira cria
# um pedido-sonda e imprime o id; a segunda recebe `PEDIDO_DLQ_ALVO=<id>` com o
# worker já subido para derrubar aquele pedido.

alvo_dlq = os.environ.get("PEDIDO_DLQ_ALVO", "").strip()
antes_dlq = contar_mortas()
pedido_dlq_id = int(alvo_dlq) if alvo_dlq.isdigit() else None

if pedido_dlq_id is None:
    status, pedido_dlq = criar_pedido(token_user, item_id, CHAVE_DLQ)
    pedido_dlq_id = (pedido_dlq or {}).get("id")
    if pedido_dlq_id is None:
        print(f"  ..    pedido-sonda nao foi criado (status {status}): cena de DLQ indisponivel")
    else:
        print(f"  ..    pedido-sonda criado para a DLQ: {pedido_dlq_id}")
        print(
            "        para fechar o cenário: suba o worker com "
            f"NOTIFICACAO_WORKER_FALHA_IDEM_KEYS=pedido:{pedido_dlq_id} e reexecute com "
            f"PEDIDO_DLQ_ALVO={pedido_dlq_id}"
        )
else:
    print(f"  ..    alvo de DLQ informado: pedido {pedido_dlq_id}")
    status, pagamento_dlq, _ = _req(
        "POST", f"/api/v1/pedidos/{pedido_dlq_id}/pagamento/", {}, token_user
    )
    check(
        f"pagamento do pedido {pedido_dlq_id} publicado (201)",
        status == 201,
        f"-> {status}",
    )

if antes_dlq is None:
    skip("mensagem morta do segundo elo chega a DLQ", "nao foi possivel ler a DLQ")
elif not pedido_dlq_id:
    skip("mensagem morta do segundo elo chega a DLQ", "o pedido-sonda nao foi criado")
    skip("pagamento com erro forcado nao gera notificacao", "o pedido-sonda nao foi criado")
elif not os.environ.get("NOTIFICACAO_WORKER_FALHA_IDEM_KEYS"):
    skip(
        "mensagem morta do segundo elo chega a DLQ",
        "o worker precisa subir com NOTIFICACAO_WORKER_FALHA_IDEM_KEYS e o teste "
        "com PEDIDO_DLQ_ALVO=<id> (ver as duas fases acima)",
    )
    skip("pagamento com erro forcado nao gera notificacao", "mesma condicao do caso anterior")
else:
    print(
        f"  ..    marcador do cenário de falha: pedido {pedido_dlq_id} "
        f"(chave 'pedido:{pedido_dlq_id}')"
    )
    morreu = False
    for _ in range(40):
        if (contar_mortas() or 0) > antes_dlq:
            morreu = True
            break
        time.sleep(0.5)
    check("mensagem morta do segundo elo chega a DLQ", morreu)
    time.sleep(1.0)
    check(
        "pagamento com erro forcado nao gera notificacao",
        contar_notificacoes(pedido_dlq_id, token_user) == 0,
    )

# --- limpeza ------------------------------------------------------------------
# O item fica referenciado por PedidoItem assim que um pedido o consome, e o
# DELETE é barrado por integridade referencial (`PROTECT`). Apagar o pedido para
# liberar o item destruiria o histórico que o próprio smoke acabou de verificar,
# então a limpeza tenta, e reporta o que sobrou em vez de afirmar que removeu
# tudo. O status que volta é 500 porque o DRF não tem tratador para `ProtectedError`
# — comportamento herdado das aulas anteriores a esta, que a Aula 11 não altera.
status_item = _req("DELETE", f"/api/v1/items/{item_id}/", token=token)[0]
status_categoria = _req("DELETE", f"/api/v1/categories/{categoria_id}/", token=token)[0]
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
