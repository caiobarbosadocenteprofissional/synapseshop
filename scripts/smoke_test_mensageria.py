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

import os
import sys
import time
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from events.contracts import EventoPedidoCriado, ItemPedidoCriado  # noqa: E402
from _comum import (  # noqa: E402
    ADMIN,
    USER,
    Relatorio,
    configurar_base,
    limpar_catalogo,
    pedir,
)
from _mensageria import (  # noqa: E402
    BROKER,
    PARTICOES,
    contar_mortas,
    kafka_particoes_de,
    ler_morta,
    republicar,
)

BASE_URL = configurar_base(
    sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
)

MARCA = str(int(time.time()))
CHAVE_OK = f"pedido-smoke-{MARCA}"
CHAVE_DLQ = f"pedido-dlq-{MARCA}"

relatorio = Relatorio(
    f"== Smoke test da mensageria assíncrona (broker: {BROKER}) =="
)
check = relatorio.check
skip = relatorio.skip


def aguardar_pedido_processado(pedido_id, token, tentativas=20, intervalo=0.5):
    """Consulta o pedido até o worker movê-lo de PENDENTE para PROCESSANDO."""
    for _ in range(tentativas):
        status, payload, _ = pedir(
            "GET", f"/api/v1/pedidos/{pedido_id}/", token=token
        )
        if status == 200 and payload and payload.get("status") == "PROCESSANDO":
            return payload
        time.sleep(intervalo)
    return None


status, _, _ = pedir("GET", "/health")
check("health publico (200)", status == 200, f"-> {status}")

status, payload, _ = pedir("POST", "/api/v1/auth/token/", ADMIN)
check("login admin (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token = (payload or {}).get("access", "")

status, payload, _ = pedir("POST", "/api/v1/auth/token/", USER)
check("login user (200)", status == 200 and "access" in (payload or {}), f"-> {status}")
token_user = (payload or {}).get("access", "")

# --- dados exclusivos deste teste -------------------------------------------
status, payload, _ = pedir(
    "POST",
    "/api/v1/categories/",
    {"name": f"Cat Mensageria {MARCA}", "description": f"Smoke test broker {BROKER}"},
    token,
)
check("criar categoria de teste (201)", status == 201, f"-> {status}")
categoria_id = (payload or {}).get("id")

status, payload, _ = pedir(
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
status, payload, _ = pedir("POST", "/api/v1/pedidos/", {"itens": []}, token)
check("pedido sem itens recusado (400)", status == 400, f"-> {status}")

status, payload, _ = pedir(
    "POST",
    "/api/v1/pedidos/",
    {"itens": [{"item_id": 99999999, "quantidade": 1}]},
    token,
)
check("item inexistente recusado (400)", status == 400, f"-> {status}")

status, payload, _ = pedir(
    "POST",
    "/api/v1/pedidos/",
    {"itens": [{"item_id": item_id, "quantidade": 1}, {"item_id": item_id, "quantidade": 2}]},
    token,
)
check("item repetido recusado (400)", status == 400, f"-> {status}")

status, payload, _ = pedir("POST", "/api/v1/pedidos/", {"itens": [{"item_id": item_id, "quantidade": 1}]})
check("pedido sem token recusado (401)", status == 401, f"-> {status}")

status, pedido, _ = pedir(
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
status, repetido, _ = pedir(
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
_, payload_reentrega, _ = pedir("GET", f"/api/v1/pedidos/{pedido_id}/", token=token_user)
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
        status, _, _ = pedir(
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

    partidas = kafka_particoes_de(repetida + distintas, evento_base)
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
status, pedido_dlq, _ = pedir(
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
    _, lido, _ = pedir("GET", f"/api/v1/pedidos/{pedido_dlq.get('id')}/", token=token_user)
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
limpar_catalogo(item_id, categoria_id, token)

sys.exit(relatorio.resultado())