# Métricas da Aula 10 — Camada 5 (mensageria assíncrona)

Todos os números vêm de `scripts/bench_mensageria.py`, que mede o caminho real
da aplicação: `POST /api/v1/pedidos/` publica o evento, o `pedido-worker`
consome e grava o estado. Nada é simulado.

Cada execução grava um JSON em `docs/`, e estes são os quatro relatórios usados
aqui:

| Relatório | Modo | Pergunta que responde |
| --- | --- | --- |
| `resultados_bench_aula10_1consumidor.json` | `api` | Com a taxa de produção real, 1 consumidor acompanha? |
| `resultados_bench_aula10_3consumidores.json` | `api` | O mesmo com 3 consumidores. |
| `resultados_bench_aula10_drenagem_1consumidor.json` | `drenagem` | Qual o teto de consumo de 1 consumidor? |
| `resultados_bench_aula10_drenagem_3consumidores.json` | `drenagem` | Qual o teto com 3? |

## Ambiente

| Item | Valor |
| --- | --- |
| Broker | Kafka (KRaft single-node) `apache/kafka:3.9.1` |
| Tópico | `pedidos.pedidocriado`, 3 partições, retenção 604800000 ms (7 dias) |
| DLQ | `pedidos.pedidocriado.dlq`, 1 partição, retenção 2419200000 ms (28 dias) |
| Group | `pedido-worker` |
| Banco | PostgreSQL 16 (container `postgres`) |
| Cache | Redis 7 (idempotência) |
| API | Django + DRF, `uvicorn`, 1 worker, throttle de leitura |

Host Docker Desktop, Windows, Python 3.12 em `.venv`. Todas as latências de
ponta a ponta saem de `created_at → processado_em`, dois carimbos gravados pelo
backend no mesmo relógio — o que o script perguntou não interfere no número.

## Modo `api`: produção em rajada, worker consumindo

200 pedidos criados em sequência, com 1 ou 3 consumidores já no grupo.

| Métrica | 1 consumidor | 3 consumidores |
| --- | --- | --- |
| Pedidos criados / processados | 200 / 200 | 200 / 200 |
| Falhas de publicação | 0 | 0 |
| Tempo de produção | 17,89 s | 17,93 s |
| **Taxa de produção** | **11,18 req/s** | **11,15 req/s** |
| Latência HTTP p50 / p95 | 88,15 / 95,40 ms | 88,95 / 97,22 ms |
| **Latência ponta a ponta p50** | **64,69 ms** | **64,62 ms** |
| **Latência ponta a ponta p95** | **67,23 ms** | **68,04 ms** |
| Latência ponta a ponta p99 | 68,30 ms | 71,72 ms |
| Latência ponta a ponta máx. | 70,83 ms | 75,92 ms |
| Tempo de drenagem do backlog | 0,068 s | 0,069 s |

**Leitura.** Adicionar consumidores não muda nada no caminho visível ao
usuário, porque o gargalo não é o consumidor. A produção é serial e cada
`POST` custa ~89 ms dentro da API (transação, preço congelado, publicação com
`acks=all`), o que trava a taxa em ~11 req/s. O consumidor sozinho gasta ~10 ms
por mensagem, então ele acompanha a produção com folga e o backlog nunca chega
a acumular: os 200 pedidos já estavam em `PROCESSANDO` quando o script terminou
de lê-los, e a "drenagem" mediu menos de 70 ms.

Ou seja: **1 consumidor já dá conta da taxa de produção desta API.** Escalar o
consumo só se pagaria com um produtor mais rápido que o serial.

## Modo `drenagem`: teto de consumo

O modo `api` não revela o teto de consumo, porque o produtor nunca o alcança.
Aqui o worker fica parado enquanto 1000 pedidos reais são criados (eventos
publicados e aguardando), e então sobe; mede-se quanto tempo o consumer group
leva para zerar o backlog.

| Métrica | 1 consumidor | 3 consumidores |
| --- | --- | --- |
| Backlog inicial | 1000 | 1000 |
| Backlog final | 0 | 0 |
| **Mensagens drenadas** | **1000** | **1000** |
| Tempo de drenagem | 15,08 s | 12,41 s |
| **Taxa de drenagem** | **66,31 msg/s** | **80,56 msg/s** |
| Latência desde a criação p50 | 67,30 s | 60,71 s |
| Latência desde a criação p95 | 108,14 s | 100,00 s |

**Leitura.** 3 consumidores rendem 1,21x, não 3x. A janela medida inclui o
subida do container e o rebalanceamento do grupo, e esses dois custos fixos
(~3 s para o container chegar à partição, mais o rebalance do terceiro membro)
comem quase toda a diferença: a parte de consumo propriamente dita levou ~3,5 s
por consumidor em ambos os casos.

O custo fixo é o que separa as duas escalas de drain:

| Backlog | 1 consumidor | 3 consumidores | Ganho |
| --- | --- | --- | --- |
| 400–500 msgs | 29,75 msg/s | 38,35 msg/s | 1,29x |
| 1000 msgs | 66,31 msg/s | 80,56 msg/s | 1,21x |

Com pouca mensagem, subir 3 containers custa mais do que entrega. Backlog
grande é onde o paralelismo paga.

## Onde o tempo de cada mensagem vai

Extraído dos logs estruturados do próprio worker (`duracao_ms`), média da
rodada de 1000 mensagens:

| Camada | 1 consumidor | 3 consumidores |
| --- | --- | --- |
| Handler (`worker.pedido.processado`) | 5,63 ms | 5,62 ms |
| Ciclo completo do consumidor (poll → commit → log) | 9,94 ms | 9,92 ms |

Duas leituras importam aqui:

1. **O commit síncrono do offset custa ~4,3 ms, quase metade do ciclo.** É uma
   ida e volta ao broker por mensagem. É o preço da garantia "o efeito está
   gravado antes de o offset avançar" — trocando por commit em lote
   (`commit(message=...)` a cada N, ou `enable.auto.commit=false` com commit
   assíncrono) renderia ~2x, ao custo de reprocessar mensagens após uma falha.
   Para este trabalho a garantia vale mais que o número.
2. **O custo por mensagem não piora com 3 consumidores** (9,94 ms → 9,92 ms).
  Ou seja, os 3 workers não estão se contendendo no banco nem no cache. O
   limite de escalonamento está em ter mais partições (hoje são 3, e são 3
   consumidores: acima disso sobra worker ocioso) e no round-trip de commit por
   consumidor.

## Limites conhecidos desta medição

- **A janela de drenagem inclui a subida do container e o rebalanceamento do
  grupo.** Daí o ganho modesto de 3 consumidores; o número de consumo em
  regime (~100 msg/s por consumidor, dos 9,94 ms por mensagem) é o das logs do
  worker.
- **Warm-up importa.** A primeira medição com 3 consumidores logo após o
  `--scale` deu p99 de 152 ms; a repetição com o grupo já acomodado deu 71,7 ms.
  A cauda era o grupo ainda assentando, não o caminho de 3 consumidores. O
  relatório oficial é o da repetição.
- **O throttle da API é proteção de produto, não da Camada 5.** Com
  `200/min`, uma rajada de 200 pedidos mais 200 leituras de estado estoura o
  limite. O harness aguarda a janela expirar uma vez e segue, para não
  descartar da amostra justamente os pedidos lentos. Subir
  `THROTTLE_USER=5000/min` elimina a espera, mas precisa ser feito no mesmo
  comando que sobe a API: `docker compose up <serviço>` recria a API e descarta
  a variável de ambiente da sessão.
- **Backlog pequeno é ruído.** A primeira tentativa (343 e 500 mensagens) produziu
  números piores que o caso real porque o custo fixo de subida dominava a
  janela. Só a rodada de 1000 mensagens é comparável.
- **Latência desde a criação inclui a espera no backlog** (até ~115 s com 1000
  mensagens pendentes). É a latência que um pedido viveria se a fila já tivesse
  1000 de profundidade, não a latência de um pedido em operação normal.

## Reproduzindo

```powershell
# Modo api: worker no ar
docker compose up -d pedido-worker
$env:BENCH_RESULTADO = 'docs/resultados_bench_aula10_1consumidor.json'
python scripts/bench_mensageria.py --modo api --pedidos 200 --rotulo "kafka-1-consumidor"

docker compose up -d --scale pedido-worker=3 pedido-worker
$env:BENCH_RESULTADO = 'docs/resultados_bench_aula10_3consumidores.json'
python scripts/bench_mensageria.py --modo api --pedidos 200 --rotulo "kafka-3-consumidores"

# Modo drenagem: duas fases, worker parado só durante o enchimento
docker compose stop pedido-worker
$env:BENCH_RESULTADO = 'docs/resultados_bench_aula10_drenagem_1consumidor.json'
python scripts/bench_mensageria.py --modo drenagem --fase preencher --pedidos 1000
# em outra janela, subir o worker e medir a queda do backlog:
python scripts/bench_mensageria.py --modo drenagem --fase medir --espera 300
```

Do host, os scripts precisam de `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`
(listener externo) e das credenciais do Postgres; de dentro da rede Compose, o
bootstrap é `kafka:29092`.
