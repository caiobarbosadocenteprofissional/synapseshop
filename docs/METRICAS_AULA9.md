# Métricas — Aula 9: Mensageria Assíncrona

Evidências numéricas da Aula 9. Decisões em
[`DECISOES_TECNICAS_AULA9.md`](DECISOES_TECNICAS_AULA9.md), contrato e operação
em [`../README.md`](../README.md#13-mensageria-assíncrona-com-rabbitmq-aula-9).

Todas as medições vêm de logs estruturados JSON emitidos pela própria
aplicação (`duracao_ms` por evento), coletados nos contêineres do Compose. Não
há geração sintética de carga: o DoD pede tempos de execução, não
*benchmark* de vazão.

---

## 1. Como reproduzir

```bash
# Modo normal: fluxo feliz + idempotência (cenário de DLQ é pulado)
docker compose up -d --build
python scripts/smoke_test_mensageria.py

# Modo com falha forçada: acrescenta as três verificações de DLQ
PEDIDO_WORKER_FALHA_IDEM_KEYS="pedido-dlq-*" docker compose up -d --force-recreate pedido-worker
python scripts/smoke_test_mensageria.py

# Logs brutos
docker compose logs -f api pedido-worker

# Estado das filas
docker compose exec -T rabbitmq rabbitmqctl list_queues name messages
```

**Ambiente da medição:** Docker Desktop (Windows), Python 3.13, Django 5.1,
`pika 1.3`, RabbitMQ 3.13, PostgreSQL 16, Redis 7, em modo desenvolvimento
(`DJANGO_DEBUG=true`), localhost. Volumes únicos por execução — a latência abaixo
é a de ambiente local, não de produção.

---

## 2. Resultado da verificação funcional

| Cenário | Resultado |
| :--- | :--- |
| Normal (sem falha forçada) | **20 PASS / 0 FAIL / 3 SKIP** |
| Com falha forçada (`pedido-dlq-*`) | **23 PASS / 0 FAIL / 0 SKIP** |

Os 3 SKIPs do cenário normal são as verificações de DLQ, puladas com a
instrução de habilitar o modo forçado — o worker saudável não deveria falhar.

### O que foi verificado

| Verificação | Evidência |
| :--- | :--- |
| Publicação do evento pelo produtor | `201` com `evento_publicado: true` |
| Contrato e cálculo do servidor | Total `399.80` a partir do catálogo, sem preço no *body* |
| Preço congelado na linha | `preco_unitario: "199.90"` persistido |
| Consumo com efeito persistido | Pedido `PENDENTE` → `PROCESSANDO` pelo worker |
| Idempotência no produtor | Mesma `idempotency_key` → `200`, mesmo `id` de pedido |
| Idempotência na reentrega | Evento republicado pela Management API → sem novo pedido, estado inalterado |
| Reentrega com recuo | 3 `mensageria.reentrega` com 250 / 500 / 1000 ms |
| Encaminhamento à DLQ | `mensageria.dlq` com `tentativa: 3` |
| Efeito zero na DLQ | Pedido da mensagem morta permanece `PENDENTE` |

---

## 3. Tempos de execução

### 3.1 Publicação e consumo do caminho feliz

Extraído de `docker compose logs api pedido-worker`:

| Evento | `duracao_ms` |
| :--- | ---: |
| `mensageria.publicado` | 3,91 |
| `mensageria.consumido` | 12,40 |
| `worker.pedido.duplicado` (reentrega) | 0,35 |
| `worker.pedido.duplicado` (republicação manual) | 0,36 |

Leitura: a publicação custa ~4 ms e o consumo ~12 ms, dos quais o efeito no
banco é a maior parte. A rejeição de duplicata é ~0,35 ms — três ordens de
 grandeza mais barata que o processamento, porque para no `SELECT` da chave e não
toca no pedido. É esse número que justifica registrar a chave **depois** do
efeito: a checagem precisa ser barata, e mesmo assim não pode ser feita antes.

### 3.2 Espera de reentrega (backoff)

| Tentativa | `espera_ms` | `duracao_ms` da tentativa |
| ---: | ---: | ---: |
| 0 → 1 | 250,0 | 312,46 |
| 1 → 2 | 500,0 | 501,89 |
| 2 → 3 | 1000,0 | 1002,19 |
| 3 → DLQ | — | 1,44 |

O `duracao_ms` acompanha `espera_ms` com folga de ~2 ms (publicação do log e
`ack`), o que confirma que a espera é o custo dominante da reentrega e que o
crescimento é exatamente dobrado a cada tentativa. Tempo total até a DLQ com os
defaults: **~1,76 s**.

### 3.3 Latência ponta a ponta

Do `occurred_at` no evento ao efeito persistido, no cenário feliz: **~16 ms**
(soma das etapas de publicação, consumo e escrita). O pedido fica `PENDENTE`
apenas durante essa janela — que é a medida relevante, porque é o que o cliente
  percebe como "demora".

---

## 4. Ciclo de vida de uma mensagem

| Etapa | Registro |
| :--- | :--- |
| Publicação | `mensageria.publicado` — 1 ocorrência |
| Consumo | `mensageria.consumido` — 1 ocorrência |
| Reentrega do mesmo `event_id` | `worker.pedido.duplicado` — sem efeito, `ack` imediato |
| Falha até esgotar tentativas | `mensageria.reentrega` — `tentativa` 0, 1, 2 |
| Mensagem morta | `mensageria.dlq` — `tentativa: 3` |
| Inspeção | `pedidos.pedidocriado.dlq` — 1 mensagem, `payload` íntegro |

Uma mensagem publicada pode gerar 1, 2 ou 4 entregas ao consumidor, e
**exatamente um** efeito no banco. Esse é o invariante que a idempotência
protege, e é o que o cenário de reentrega do smoke test verifica explicitamente.

---

## 5. Estado das filas após a validação

```
$ docker compose exec -T rabbitmq rabbitmqctl list_queues name messages
```

| Fila | Esperado após purga |
| :--- | ---: |
| `pedidos.pedidocriado` | 0 |
| `pedidos.pedidocriado.dlq` | 0 |

Ambas são purgadas explicitamente ao fim da validação, porque a DLQ acumula
mensagens mortas por definição e os contêineres de desenvolvimento não são
reciclados entre execuções.

---

## 6. Limitações desta medição

Estas limitações são assumidas, não resolvidas nesta aula:

- **Ambiente local, não representativo.** Sem TLS entre API e broker, sem
  cluster, sem filesystem distribuído. Tempos de produção serão outros.
- **Volume de uma requisição por rodada.** O DoD pede tempos de execução, não
  vazão; RPS, *concurrency* e saturação de fila ficam para quando houver
  consumidor em partição (Aulas 10+).
- **Falha induzida, não orgânica.** A DLQ é exercitada por falha forçada
  determinística via `PEDIDO_WORKER_FALHA_IDEM_KEYS`, o que torna o cenário
  reproduzível. Não cobre indisponibilidade real do PostgreSQL ou do broker.
- **Sem testes automatizados de contrato.** Proibidos pela spec desta aula; a
  validação de `event_type`/`version` hoje é exercitada pelo smoke test, não por
  suíte.
- **`duracao_ms` mede a chamada, não a fila.** O tempo entre `publicado` e
  `consumido` inclui espera na fila, mas não é separado do total. Atribuição fina
  de latência por etapa exigiria relógio comum entre processos, que não foi
  introduzido aqui.
