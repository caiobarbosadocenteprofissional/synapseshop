# Decisões técnicas — Aula 10 (Camada 5: Kafka)

Registro do *porquê* de cada escolha da Camada 5. O *como* está em
`services/messaging_kafka.py`, `docker-compose.yml` e `config/settings.py`. Os
números citados estão em [`METRICAS_AULA10.md`](METRICAS_AULA10.md).

---

## 1. Kafka como padrão, RabbitMQ preservado atrás de uma fachada

**Decisão.** `MENSAGERIA_BROKER` com `kafka` (padrão) ou `rabbitmq`.
`services/messaging.py` é a fachada: `api/views.py` e
`workers/pedido_worker.py` importam de lá e não sabem qual broker está atrás.

**Por quê.** A aula entrega Kafka, mas o projeto já tinha RabbitMQ funcionando e
testado. Reescrever tudo perderia uma implementação boa e a validação que ela
já tinha. Uma fachada de ~20 linhas preserva as duas e mantém o RabbitMQ como
caminho de regressão — foi assim que a Aula 10 se provou sem quebrar a 9:
`23 PASS / 0 FAIL` no smoke com `MENSAGERIA_BROKER=rabbitmq`.

**Trade-off.** A fachada é a única abstração do projeto, e ela existe por um
motivo concreto (dois brokers reais), não por elegantismo. Um broker novo
exigiria tocar a fachada; não há plugins.

## 2. Três partições, réplicas 1

**Decisão.** `KAFKA_PARTICOES=3`, `KAFKA_REPLICAS=1`.

**Por quê.** Três partições porque o paralelismo de consumo em Kafka é limitado
pelas partições: com 3 partições e 3 consumidores, cada um fica com uma; um 4º
consumidor ficaria ocioso. Verificado no grupo:

```
pedido-worker  pedidos.pedidocriado  0  offset 780  lag 0  synapseshop-worker-045a95...
pedido-worker  pedidos.pedidocriado  1  offset 835  lag 0  synapseshop-worker-186300...
pedido-worker  pedidos.pedidocriado  2  offset 785  lag 0  synapseshop-worker-bdc1bb...
```

Réplica 1 porque o Compose roda um único broker KRaft. É um ponto de
antecipação: `KAFKA_REPLICAS` já existe como variável, e subir para 3 num
cluster de 3 brokers não exige tocar código — mas em nó único, réplica 3 só
consumiria disco. Registrar a decisão é mais honesto do que fingir alta
disponibilidade.

**Trade-off.** Single-node = ponto único de falha, e a retenção de 7 dias
guarda os eventos. Em produção, réplicas ≥ 3 e `min.insync.replicas=2`.

## 3. Topologia declarada pela aplicação, idempotentemente

**Decisão.** `declarar_topologia()` usa `AdminClient.create_topics` e trata
`TOPIC_ALREADY_EXISTS` como sucesso. O consumidor chama a mesma função na
inicialização.

**Por quê.** Declarar tópico na mão é passo de setup que alguém esquece, e
falhar no primeiro consumo é a pior hora para descobrir. Declarar pela aplicação
torna o estado convergente: qualquer processo que sobe garante a topologia.

O consumidor também declara, e não só o produtor, porque foi exatamente o bug
que travou o primeiro smoke — o produtor subia, o consumidor subia, e o tópico
não existia porque ninguém tinha declarado.

## 4. Retenção assimétrica: 7 dias no tópico, 28 dias na DLQ

**Decisão.** `KAFKA_RETENTION_MS=604800000` (7 dias) no tópico principal;
`2419200000` (28 dias) na DLQ.

**Por quê.** O tópico principal carrega o tráfego diário: expirá-lo mais cedo
mantém o disco pequeno sem perder nada que importe. A DLQ é outra coisa — é onde
alguém vai olhar depois que algo quebrou, e é justamente quando o contexto de
alguns dias atrás é o que interessa. Encurtar o prazo é perder o incidente. Custo: 28 dias de mensagens mortas, que precisam de uma política de
inspeção separada.

## 5. `idempotency_key` como chave de partição

**Decisão.** A chave do evento é a `idempotency_key` do pedido.

**Por quê.** Duas propriedades de uma vez. O roteamento por chave mantém todos
os eventos de um mesmo pedido na mesma partição, então a ordem dos comandos
dele é preservada; e a reentrega da mesma mensagem cai na mesma partição, o que
torna o reprocessamento previsível. Verificado no smoke: 3 publicações da mesma
chave foram todas para a partição 1.

**Trade-off.** Particionar por `idempotency_key` concentra a carga de pedidos
com chaves parecidas. Como a chave é um UUID, a distribuição é uniforme.

## 6. `enable.auto.commit=False` + commit depois do efeito

**Decisão.** Commit manual e **síncrono**, logo depois de o efeito estar
persistido (`processado_em` gravado e transação confirmada).

**Por quê.** É a garantia que a camada promete: o offset nunca adianta o
estado. Se o worker cai entre gravar o efeito e confirmar o offset, a
mensagem volta e o handler a trata como reentrega — a idempotência cobre. Na
inversão (commit antes do efeito), uma queda perderia o efeito para sempre,
em silêncio.

**Trade-off, e é o trade-off central da aula.** O commit síncrono custa um
round-trip ao broker por mensagem: ~4,3 ms dos 9,94 ms do ciclo, quase metade
do custo. Commit em lote renderia ~2x. Em troca, uma falha perde o trabalho de
até N mensagens, que volta pelo reprocessamento. Escolhemos a garantia: o
trabalho aqui é mostrar o contrato de entrega correto, não bater um número de
throughput. A variável existe para quem quiser medir o outro lado.

## 7. Idempotência em duas camadas: registro único + transição de estado

**Decisão.** `idempotencia.registrar()` grava a chave em uma tabela com chave
primária, e o handler **ainda** faz a transição `PENDENTE → PROCESSANDO`.

**Por quê.** O registro único é o que barra o efeito duplicado. A transição de
estado é o que torna a operação segura mesmo sem o registro (por exemplo, se a
chave for expirada pela TTL entre a leitura e a gravação). São defesas
independentes: uma funciona se a outra falhar.

**Trade-off.** Duas escritas onde uma bastaria. Custo de ~5,6 ms por mensagem
(handler completo), e é o que mantém a reentrega um no-op — o smoke confirma
que a segunda entrega devolve o mesmo pedido, sem efeito novo.

## 8. Retry com backoff exponencial e teto, depois DLQ

**Decisão.** 3 tentativas (250 ms → 500 ms → 1000 ms, teto 5000 ms), header
`x-retry-count` incremented a cada reentrega, e depois publicação na
`pedidos.pedidocriado.dlq` com o erro no header `x-ultimo-erro`.

**Por quê.** Retry curto e limitado para erro transitório (banco indisponível,
timeout). O header de contagem sobrevive à reentrega porque a mensagem volta
com os headers que a publicação anterior anexou — é o estado do retry que
atravessa o broker, não memória do processo. Ao esgotar as tentativas, a
mensagem vai para a DLQ em vez de ficar em loop: uma falha permanente
(contrato inválido, item removido) não melhora com a 4ª tentativa, e_insistir
só gasta CPU e esconde o incidente.

A DLQ é um tópico de verdade, não uma fila na API: ela é inspecionável com as
ferramentas padrão do Kafka, e uma mensagem morta não bloqueia quem consome o
tópico principal.

## 9. DLQ com 1 partição, e não 3

**Decisão.** `pedidos.pedidocriado.dlq` com 1 partição.

**Por quê.** Uma partição é suficiente para o volume de falhas (que é o volume
de incidentes), e 1 partição deixa óbvia a ordem em que as mensagens foram
mortas. Se o volume crescer até o consumo ficar lento, criar partições depois é
uma operação normal; ao contrário, não há como diminuir.

## 10. Um worker escalável, sem `container_name`

**Decisão.** `pedido-worker` sem `container_name` no Compose, escalável com
`--scale`.

**Por quê.** `container_name` fixa o nome do container, e o Docker recusa um
segundo container com o mesmo nome. Era a trava que impedia escalar o worker —
e, sem conseguir escalar, a comparação 1 vs 3 consumidores (que é a metade da
medição da aula) não existia.

**Trade-off.** `container_name` dá um DNS estável; sem ele, o nome é
`pedido-worker-1`, `-2`, `-3`. Nenhum componente depende do nome, então nada
mudou.

## 11. Dois listeners no mesmo Kafka

**Decisão.** `PLAINTEXT://kafka:29092` (rede Compose) e
`PLAINTEXT_HOST://0.0.0.0:9092` (host), em `advertised.listeners`
correspondentes.

**Por quê.** O Compose fala com o Kafka pelo nome do serviço; scripts rodados na
máquina do desenvolvedor, como o benchmark, precisam de um endereço alcançável
de fora. Com um listener só, ou o container anuncia um endereço que o host não
resolve, ou o host recebe um `advertised` que o container não resolve.

**Trade-off.** Só texto puro, sem TLS nem autenticação — aceitável para stack
local, e a variável de ambiente já é o ponto de troca quando não for.

## 12. Logs estruturados com `evento` em toda a Camada 5

**Decisão.** Todo passo publica uma linha JSON com `evento` e campos
relevantes: `kafka.topologia.declarada`, `kafka.produtor.publicado` (com
partição e offset), `kafka.consumidor.iniciado`, `worker.pedido.processado`
(com `duracao_ms`), `mensageria.dlq`, `mensageria.reentrega`.

**Por quê.** É o que torna a aula verificável em vez de afirmada. O smoke
confirma comportamento; os logs confirmam *por quê* o comportamento foi o que
foi. Os números das métricas saíram daqui — o custo de 9,94 ms por mensagem e
o commit de 4,3 ms saíram de `duracao_ms`.

## 13. O benchmark é tolerante a 429, e por padrão roda com o throttle de produção

**Decisão.** O harness aguarda a janela do throttle expirar uma vez e segue, em
vez de subir o limite da API por conta própria ou descartar pedidos lentos.

**Por quê.** Um 429 no meio da coleta vira `falhas`, e o viés não é uniforme: o
throttle descarta justamente as respostas mais lentas, que são a cauda dos
percentis. Descartar ou reprocessar seletivamente faria o p95/p99 bonito e
falso. Passos de configuração que o script faz sozinho também envelhecem mal:
`docker compose up <serviço>` recria a API e descarta a variável de ambiente da
sessão — foi assim que o limite de `5000/min` voltou a `200/min` sem erro
visível.

**Trade-off.** Uma execução com 200 pedidos + 200 leituras gasta ~61 s esperando
a janela. Subir `THROTTLE_USER` no mesmo comando que sobe a API elimina a
espera, e o script documenta como.

## Resumo dos custos medidos

| Decisão | Custo | Benefício |
| --- | --- | --- |
| Commit síncrono por mensagem | ~4,3 ms/msg (43% do ciclo) | offset nunca adianta o efeito |
| Registro de idempotência + transição | ~5,6 ms/msg | defesa em duas camadas |
| 3 partições | teto de 3 consumidores | paralelismo sem ponto ocioso |
| Réplica 1 | sem alta disponibilidade | setup local simples |
| DLQ retida 28 dias | disco | contexto do incidente preservado |
