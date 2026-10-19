# Guia de Mensageria Assincrona — Kafka (Camada 5)

> Documento movido de `README.md` secao 12 (Aula 15). A visao geral do fluxo
> e os comandos essenciais permanecem no README; o detalhamento esta aqui.

## Kafka ou RabbitMQ

| Critério | Kafka (padrão) | RabbitMQ (alternativo) |
| :--- | :--- | :--- |
| Paralelismo de consumo | por partição do tópico | por consumidor da fila |
| Retenção | nativa, por tópico | limitada a filas duráveis |
| Reentrega com contagem | header `x-retry-count` na republicação | *nack requeue* / DLX nativa |
| Rota de falha | tópico DLQ explícito | *dead-letter exchange* da fila |
| Ordem | por partição (chave = `idempotency_key`) | por fila (*round-robin*) |

O contrato em `events/contracts.py` traz `event_type` e `version`, então a troca
de broker não quebra o formato da mensagem. A decisão e o porquê de cada escolha
estão em [`docs/DECISOES_TECNICAS_AULA10.md`](DECISOES_TECNICAS_AULA10.md).

## Topologia do Kafka

```
   POST /api/v1/pedidos/ ──▶ key: idempotency_key ──▶ ┌───────────────────────┐
                                                   │  pedidos.pedidocriado │
                                                   │  3 partições          │
                                                   │  retenção 7 dias      │
                                                   └───────────┬───────────┘
                                                               │ consumer group
                                                               │ pedido-worker
                                                    ┌───────────┬────────────┐
                                                    │  pedido-worker       │  PENDENTE → PROCESSANDO
                                                    │  commit manual       │  (síncrono, após o efeito)
                                                    └──────────┬───────────┘
                                          falhas esgotadas   │
                                                    ┌───────────┬────────────┐
                                                    │ pedidos.pedidocriado │  ← inspeção
                                                    │        .dlq          │    manual
                                                    │  1 partição          │
                                                    │  retenção 28 dias    │
                                                    └──────────────────────┘
```

| Elemento | Configuração | Observação |
| :--- | :--- | :--- |
| `pedidos.pedidocriado` | 3 partições, retenção `604800000` ms | Eventos de `PedidoCriado`. |
| `pedidos.pedidocriado.dlq` | 1 partição, retenção `2419200000` ms | Mensagens mortas, para inspeção. |
| `pedido-worker` | consumer group | Um consumidor por partição. |
| Chave de partição | `idempotency_key` | Eventos do mesmo pedido ficam na mesma partição, em ordem. |
| Réplicas | `KAFKA_REPLICAS=1` | Broker único no Compose; subir em cluster. |

A topologia é **declarada pela aplicação** (`declarar_topologia()`, via
`AdminClient`), de forma idempotente: producer e consumer chamam a mesma função
na subida, e `TOPIC_ALREADY_EXISTS` é sucesso. Assim não existe passo de setup
manual que alguém esqueça.

## Listeners

O mesmo broker atende duas redes:

| Listener | Endereço | Quem usa |
| :--- | :--- | :--- |
| Compose | `kafka:29092` | Containers (`api`, `pedido-worker`). |
| Host | `localhost:9092` | Scripts rodados na máquina de desenvolvimento. |

Os dois são texto puro, sem TLS — adequado à stack local. Para o host, os
scripts precisam de `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`, porque o default
de `config/settings.py` também é `localhost` e o do Compose é `kafka:29092`.


## Contrato da mensagem `PedidoCriado`

Definido e **validado** em `events/contracts.py`. O envelope JSON:

```json
{
  "event_id": "0f3c...uuid",
  "event_type": "PedidoCriado",
  "version": "1.0",
  "occurred_at": "2026-09-30T23:52:29.117970Z",
  "correlation_id": "b7a1...uuid",
  "idempotency_key": "pedido-2026-0001",
  "dados": {
    "pedido_id": 15,
    "usuario_id": 2,
    "total": "399.80",
    "status": "PENDENTE",
    "itens": [
      {"item_id": 622, "quantidade": 2, "preco_unitario": "199.90"}
    ]
  }
}
```

Regras de contrato:

- **Discriminantes** — `event_type` e `version` são validados na recepção; evento
  desconhecido ou de versão incompatível é rejeitado **antes** de qualquer escrita.
- **`idempotency_key`** — chave de negócio do pedido, **obrigatória**, até 64
  caracteres (limite do índice único). É o que garante idempotência ponta a ponta.
- **Monetário como `str`** — `total` e `preco_unitario` viajam como texto; `float`
  no JSON introduz erro de arredondamento.
- **`correlation_id`** — identificador que atravessa produtor e consumidor,
  permitindo correlacionar logs e mensagens.
- **Preço congelado** — o cliente informa apenas `item_id` e `quantidade`; preço
  e total são calculados no servidor a partir do catálogo, para que o evento
  descreva o pedido como foi vendido.

## Idempotência

Duas camadas, com a mesma chave e o mesmo TTL:

| Camada | Onde | Papel |
| :--- | :--- | :--- |
| `EventoProcessado` (PostgreSQL) | `services/idempotencia.py` | Fonte durável; unicidade `(evento, idempotency_key)` resolve corrida entre consumidores. |
| Redis (`evento:processado:<evento>:<chave>`) | mesmo módulo | Caminho rápido, com TTL nativo. |

Pontos-chave da regra:

- **No produtor** — repetir a mesma `idempotency_key` devolve o **mesmo pedido**
  com **200**, sem criar outro e sem publicar outro evento.
- **No consumidor** — a chave é registrada **depois** do processamento
  bem-sucedido, nunca antes: reservar a chave antes descartaria uma reentrega cujo
  processamento falhou, entregando o pedido com efeito zero.
- **TTL** — `IDEMPOTENCIA_TTL_SEGUNDOS` (padrão 24 h). As chaves expiradas são
  removidas na subida do worker para a tabela não crescer sem limite.
- **Efeito idempotente** — a transição `PENDENTE` → `PROCESSANDO` só ocorre se o
  pedido ainda estiver `PENDENTE`, então mesmo uma corrida de reentregas não
  duplica o efeito.

## Reentrega, recuo e DLQ

| Parâmetro | Default | Significado |
| :--- | ---: | :--- |
| `MENSAGERIA_MAX_RETRIES` | `3` | Reentregas **além** da primeira tentativa (4 tentativas no total). |
| `MENSAGERIA_BACKOFF_BASE_MS` | `250` | Base do recuo exponencial. |
| `MENSAGERIA_BACKOFF_MAX_MS` | `5000` | Teto do recuo. |
| `RABBITMQ_PREFETCH` | `1` | Uma mensagem por vez; nada se perde em requeue (só no RabbitMQ). |

A contagem de tentativas atravessa o broker em headers, e não em memória do
processo — é isso que permite a reentrega continuar de onde parou.

1. Sucesso → confirma o offset (`commit` síncrono, **depois** do efeito gravado).
2. Falha com `tentativa < MAX_RETRIES` → republica o mesmo corpo em
   `pedidos.pedidocriado` com `x-retry-count` incrementado, aguarda o recuo
   exponencial (`250 ms → 500 ms → 1000 ms → …`, limitado por `BACKOFF_MAX`) e
   então confirma a original.
3. `tentativa >= MAX_RETRIES` → publica em `pedidos.pedidocriado.dlq` com o erro
   em `x-ultimo-erro` e confirma a original. Não há consumo automático da DLQ: a
   decisão de reprocessar é humana.

No RabbitMQ, os mesmos passos usam `ack` manual, *nack requeue* para a reentrega
e *dead-letter exchange* para a DLQ.

Corpo ilegível (JSON inválido) não tem como ser reprocessado e vai direto para a
DLQ, sem consumir tentativas.

## Estrutura

| Caminho | Responsabilidade |
| :--- | :--- |
| `events/contracts.py` | Contrato `PedidoCriado` (serialização e validação). |
| `services/messaging.py` | Fachada: escolhe o broker a partir de `MENSAGERIA_BROKER`. |
| `services/messaging_kafka.py` | Topologia, produtor, consumidor com offset manual, reentrega e DLQ. |
| `services/messaging_rabbit.py` | Mesmo contrato sobre RabbitMQ (broker alternativo). |
| `services/idempotencia.py` | Chave de deduplicação com TTL (Redis + PostgreSQL). |
| `api/views.py` | `PedidoCreateView` (produtor) e `PedidoDetailView` (observabilidade). |
| `workers/pedido_worker.py` | Consumidor: valida o contrato, deduplica e persiste o estado. |
| `scripts/smoke_test_mensageria.py` | Verificação do fluxo, da idempotência e da DLQ em ambos os brokers. |
| `scripts/bench_mensageria.py` | Latência ponta a ponta, percentis e throughput de consumo. |


## Endpoints

| Método | Rota | Ação | Status |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/pedidos/` | Cria pedido e publica `PedidoCriado` | 201 / 200 / 400 / 401 |
| GET | `/api/v1/pedidos/{id}/` | Detalha pedido (dono ou admin) | 200 / 404 |

A criação do pedido exige autenticação (qualquer papel) — diferentemente do
catálogo, em que escrita é `admin`-only, porque o pedido pertence a quem o cria.

`201` traz `evento_publicado: true`. Se o pedido for commitado mas o broker
recusar o evento, a resposta é `202` com `evento_publicado: false`: o dado está no
banco e a falha fica registrada em log, sem mentir sobre o estado.

## Observabilidade

Logs estruturados JSON com `duracao_ms` em cada etapa:

```json
{"evento": "mensageria.publicado", "idempotency_key": "pedido-smoke-1790812348", "duracao_ms": 3.91}
{"evento": "mensageria.consumido", "idempotency_key": "pedido-smoke-1790812348", "resultado": "ok", "duracao_ms": 12.4}
{"evento": "worker.pedido.duplicado", "pedido_id": 15, "resultado": "duplicado", "duracao_ms": 0.35}
{"evento": "mensageria.reentrega", "tentativa": 0, "proxima_tentativa": 1, "espera_ms": 250.0}
{"evento": "mensageria.dlq", "tentativa": 3, "dlq": "pedidos.pedidocriado.dlq"}
```

## Exemplos rápidos

```bash
# Token e criação do pedido (o evento é publicado no mesmo passo)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" -d '{"username":"user","password":"user"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

curl -X POST http://localhost:8000/api/v1/pedidos/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"pedido-2026-0001","itens":[{"item_id":1,"quantidade":2}]}'

# O worker leva o pedido de PENDENTE para PROCESSANDO
curl http://localhost:8000/api/v1/pedidos/15/ -H "Authorization: Bearer $TOKEN"

# Repetir a chave devolve o mesmo pedido, com 200
curl -i -X POST http://localhost:8000/api/v1/pedidos/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"pedido-2026-0001","itens":[{"item_id":1,"quantidade":2}]}'

# Logs de produtor e consumidor
docker compose logs -f api pedido-worker

# UI de gerenciamento do RabbitMQ (broker alternativo; guest/guest)
# http://localhost:15672

# Estado dos tópicos do Kafka
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:29092 --list
docker compose exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:29092 --describe --group pedido-worker
```

## Operação

| Comando | Efeito |
| :--- | :--- |
| `PEDIDO_WORKER_FALHA_IDEM_KEYS="pedido-dlq-*" docker compose up -d --force-recreate pedido-worker` | Worker rejeita pedidos cujo padrão casa — simula erro para validar reentrega/DLQ |
| `MENSAGERIA_BROKER=rabbitmq docker compose up -d --force-recreate api pedido-worker` | Alterna para o broker da Aula 9 |
| `MENSAGERIA_BROKER=kafka docker compose up -d --force-recreate api pedido-worker` | Volta ao Kafka |
| `docker compose up -d --scale pedido-worker=3 pedido-worker` | Escala o consumo (1 consumidor por partição) |
| `docker compose exec -T kafka ... --delete --topic pedidos.pedidocriado.dlq` | Remove a DLQ depois da inspeção |
| `docker compose exec -T rabbitmq rabbitmqctl purge_queue pedidos.pedidocriado.dlq` | Limpa a DLQ do RabbitMQ |
| `docker compose exec -T rabbitmq rabbitmqctl list_queues name messages` | Estado das filas do RabbitMQ |
| `docker compose logs -f pedido-worker` | Logs do consumidor |
| `MESSAGERIA_ENABLED=false docker compose up -d --force-recreate api` | Kill-switch: grava o pedido sem publicar (202) |

Com `MESSAGERIA_ENABLED=false` a API segue funcionando: o pedido é persistido e
a resposta é `202` com `evento_publicado: false`, o que isola o custo da
sincronia ponta a ponta em medições.

## Verificação funcional

O smoke test é o mesmo nos dois brokers — ele detecta o broker ativo por
`MENSAGERIA_BROKER` e adapta as verificações de partição/DLQ.

```bash
# Fluxo feliz + idempotência (o cenário de DLQ é pulado sem o modo forçado)
python scripts/smoke_test_mensageria.py

# Com o cenário de DLQ ativo
PEDIDO_WORKER_FALHA_IDEM_KEYS="pedido-dlq-*" docker compose up -d --force-recreate pedido-worker
python scripts/smoke_test_mensageria.py
```

Resultado da validação:

| Broker | Resultado | Verificações extras |
| :--- | :--- | :--- |
| Kafka | **25 PASS / 0 FAIL** | Mesma chave sempre na mesma partição; chaves diferentes se espalham pelas 3 partições |
| RabbitMQ | **23 PASS / 0 FAIL** | — |

Ambos cobrem publicação, contrato, consumo com persistência do estado,
idempotência no produtor, idempotência na reentrega (o teste republica o mesmo
evento) e chegada à DLQ com o pedido ainda em `PENDENTE`.

## Desempenho medido

Medido com `scripts/bench_mensageria.py` sobre o caminho real. Números,
ambiente e limites desta medição em
[`docs/METRICAS_AULA10.md`](METRICAS_AULA10.md).

| Cenário | 1 consumidor | 3 consumidores |
| :--- | :--- | :--- |
| Produção em rajada (200 pedidos) | 11,18 req/s | 11,15 req/s |
| Latência ponta a ponta p50 / p95 | 64,69 / 67,23 ms | 64,62 / 68,04 ms |
| Latência ponta a ponta p99 | 68,30 ms | 71,72 ms |
| Backlog de 1000 msgs drenado | 66,31 msg/s | 80,56 msg/s |

O gargalo da produção é a API (cada `POST` custa ~89 ms, com publicação
síncrona e `acks=all`), não o consumidor: um worker já acompanha a taxa de 11
req/s. Escalar o consumo só se pagaria com um produtor mais rápido que o serial.

```bash
# Latência ponta a ponta com o worker no ar
python scripts/bench_mensageria.py --modo api --pedidos 200 --rotulo "kafka-1-consumidor"

# Teto de consumo: enche o backlog com o worker parado, depois mede a queda
docker compose stop pedido-worker
python scripts/bench_mensageria.py --modo drenagem --fase preencher --pedidos 1000
python scripts/bench_mensageria.py --modo drenagem --fase medir --espera 300
```

> **Nota:** o harness é tolerante ao throttle da API (200/min): aguarda a janela
> expirar uma vez e segue, em vez de descartar da amostra os pedidos lentos, que
> são justamente a cauda dos percentis.

