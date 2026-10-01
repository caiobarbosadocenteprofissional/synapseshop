# Decisões Técnicas — Aula 9: Mensageria Assíncrona

Registro das decisões de implementação da Aula 9, seguindo o formato das aulas
anteriores. Evidências numéricas em [`METRICAS_AULA9.md`](METRICAS_AULA9.md).

---

## 1. Escopo

A spec pede o fluxo produtor/consumidor para o evento inicial `PedidoCriado`, com
idempotência, reentrega com recuo e DLQ.

**Decisão:** entregar o evento inicial completo, sem antecipar pagamento nem
notificação.

**Motivo:** a diretriz SpecDD proíbe antecipar requisitos de aulas futuras. A spec
descreve o objetivo geral do módulo (fluxo de pedido, pagamento e notificação),
mas as tarefas e o DoD delimitam explicitamente a etapa ao evento
`PedidoCriado`. Publicar eventos de `PagamentoRealizado` ou
`NotificacaoEnviada` agora exigiria inventar contratos que a spec não define.

Consequência assumida: o pedido só avança de `PENDENTE` para `PROCESSANDO`.
Os status `PAGO`/`ENVIADO` e a transição de `PROCESSANDO` para eles ficam para as
aulas seguintes, junto com os respectivos eventos.

## 2. Broker: RabbitMQ em vez de Kafka

**Decisão:** RabbitMQ, via `pika`, em modo AMQP.

**Motivo:** o requisito desta etapa é o tratamento de falha **por mensagem** —
reentrega com contagem de tentativas e encaminhamento para fila morta. O AMQP
resolve isso de forma nativa e declarativa: a *dead-letter exchange* é um
atributo da fila, e o cabeçalho `x-death` do broker informa quantas vezes a
mensagem foi mortificada, sem código adicional no produtor. No Kafka, o
equivalente seria reprocessar o log a partir de um offset, o que exige
consumidores auxiliares, gestão de offsets e retenção.

Motivos secundários: a spec pede preservação da ordem de um pedido, e o broker
mantém a ordem por fila; a spec pede métricas de latência, e o `ack` manual
permite medir o tempo entre publicação e efeito persistido.

O contrato em `events/contracts.py` carrega `event_type` e `version`
independentemente do broker, para que a troca não quebre o formato da mensagem.

## 3. Contrato com envelope, não corpo plano

**Decisão:** a mensagem é um envelope com metadados de transporte
(`event_id`, `event_type`, `version`, `occurred_at`, `correlation_id`,
`idempotency_key`) e os dados de negócio em `dados`.

**Motivo:** o consumidor precisa decidir, **antes** de tocar no banco, se a
mensagem é de um evento que ele entende. Sem `event_type`/`version` no envelope,
essa checagem dependeria de adivinhar pelos campos de negócio — o que quebra
silenciosamente quando um campo muda. Com o envelope, a validação é explícita e
uma versão incompatível é rejeitada, não mal interpretada.

Escolhas de tipos:

- **Dinheiro como `str`.** `total` e `preco_unitario` viajam como texto.
  `float` no JSON introduz erro de arredondamento binário, e o preço é
  justamente o campo que não pode tolerar isso.
- **`idempotency_key` com 64 caracteres.** O limite é o do índice único no
  PostgreSQL, para que a restrição de unicidade seja garantida pelo banco e não
  apenas pela aplicação.
- **Preço congelado no evento.** O evento descreve o pedido *como foi vendido*:
  o cliente informa `item_id` e `quantidade`; preço e total vêm do catálogo no
  servidor. Se o preço mudasse entre a publicação e o processamento, o efeito
  persistido ainda corresponde ao valor cobrado.

## 4. Idempotência em duas camadas, registrada depois do efeito

**Decisão:** deduplicação em Redis (caminho rápido, TTL nativo) **e** em tabela
PostgreSQL (fonte durável), com a chave registrada **após** o processamento
bem-sucedido.

**Motivo:** cada camada cobre uma falha da outra. O TTL do Redis é o
mecanismo de expiração da spec, mas o Redis é volátil; a tabela garante a
unicidade mesmo com o cache vazio. E a inserção na tabela, com restrição única
em `(evento, idempotency_key)`, resolve a corrida entre dois consumidores que
chegam com a mesma chave ao mesmo tempo — o `INSERT` de um falha e o consumidor
sabe que já foi processado, sem coordenada.

A ordem importa: registrar a chave **antes** do efeito descartaria uma reentrega
cujo processamento falhou, o que significa entregar pedido com efeito zero. Por
isso o registro vem depois, dentro da mesma transação do efeito.

**TTL de 24 h** (`IDEMPOTENCIA_TTL_SEGUNDOS`). É janela suficiente para cobrir
reentregas e reexecuções do worker, e curta o bastante para que uma chave antiga
não bloqueie um pedido legítimo. Chaves expiradas são removidas na subida do
worker, para a tabela não crescer sem limite — o `expire` do Redis é automático,
o `DELETE` do PostgreSQL não é.

## 5. Produtor publica depois do commit

**Decisão:** o pedido é gravado e commitado primeiro; só então o evento é
publicado. Se o commit falhar, nada é publicado. Se o broker recusar, a API
responde `202` com `evento_publicado: false`.

**Motivo:** publicar dentro da transação ainda não comitada faria o consumidor
ver um pedido inexistente (a mensagem chegaria antes do commit). Publicar antes
do commit e perder a confirmação deixaria um pedido sem evento. A ordem
commit → publish elimina a janela, ao custo de uma janela inversa (commit
ok, publish falhou), que é **melhor**: o pedido existe e pode ser reconciliado;
o inverso seria um evento órfão sem pedido.

O `202` com `evento_publicado: false` é a consequência honesta dessa escolha: a
API não mente sobre o que conseguiu fazer. A alternativa — devolver erro depois
de gravar — faria o cliente repetir e receber `409`, com o pedido já criado.

## 6. Consumidor: `ack` manual, `prefetch=1`, efeito idempotente

**Decisão:** `auto_ack=False` e um laço interno que bombeia eventos do socket
com *timeout*, sem reabrir a conexão entre mensagens.

**Motivo:** `auto_ack=True` perderia a mensagem se o processo morresse entre o
receive e a persistência. Com `ack` manual, a mensagem só é confirmada depois do
efeito, e o broker a devolve se o worker cair.

`prefetch=1` entrega uma mensagem por vez. Com o valor padrão, um worker poderia
acumular mensagens em memória local e perder todas elas numa queda; o custo é
através de mensagens, que só importa a partir do particionamento, escopo das
aulas seguintes.

O laço interno existe por um motivo que apareceu na validação: a primeira versão
reconectava a cada iteração do laço externo, o que derrubava a conexão no meio
do processamento de uma mensagem e fazia a transação ser refeita indefinidamente.
Reconectar só quando a conexão realmente cai mantém a mensagem em processamento
intacta. O **reconhecimento de publicação** (`confirm_delivery`) é usado no
produtor para o mesmo motivo pelo outro lado: uma publicação sem confirmação pode
ser perdida em silêncio, e `mandatory=True` cobre o caso da mensagem ser
descartada por não haver rota.

## 7. Reentrega com recuo exponencial e DLQ

**Decisão:** o consumidor republica a mensagem com `x-retry-count`
incrementado, aguarda o recuo e então confirma a original. Ao esgotar
`MENSAGERIA_MAX_RETRIES` (padrão 3), faz `nack` sem *requeue* e o broker
encaminha para `pedidos.pedidocriado.dlq` pela *dead-letter exchange*.

**Motivos:**

- **Republicar e não usar `nack requeue`:** o *requeue* do RabbitMQ devolve a
  mensagem ao **início** da fila, sem atraso e sem contador. Isso causa
  repetição imediata, transforma uma falha persistente em laço apertado, e
  impede contar tentativas. Republicar com cabeçalho de contagem dá controle do
  backoff e torna a tentativa observável em log.
- **Recuo exponencial** (`250 ms → 500 ms → 1000 ms`, limitado por
  `MENSAGERIA_BACKOFF_MAX_MS`): uma falha por dependência caída precisa de tempo
  para se recuperar, e reentregar imediatamente desperdiça tentativas.
- **Confirmar a original só depois da republicação:** se a republicação falhar,
  a original é reenfileirada em vez de perdida. Sem isso, uma falha de conexão
  durante a reentrega descartaria a mensagem sem qualquer rastro.
- **DLQ sem consumidor automático:** a decisão de reprocessar mensagem morta é
  humana. Um consumidor automático produziria laço infinito de falhas sem
  intervenção. Por isso o cenário é validado com falha forçada por padrão de
  chave, e não com uma falha de infraestrutura.
- **Corpo ilegível vai direto à DLQ:** JSON inválido não tem como ser
  reprocessado com sucesso, então consumir tentativas seria atraso puro.

## 8. Verificação por smoke test, sem testes globais

**Decisão:** validar por `scripts/smoke_test_mensageria.py`, que exercita a API,
o broker e o worker reais, em vez de criar suíte de testes automatizados.

**Motivo:** a spec da Aula 9 **proíbe** explicitamente antecipar testes
automatizados globais e pipeline de CI/CD. Um smoke test sobre a stack em
execução é a evidência exigida pelo DoD ("tempos de execução recolhidos",
"análise baseada em logs", "DLQ validado por simulação"), sem criar a
estrutura de testes que a spec adia.

**Limite assumido:** o smoke test não substitui testes automatizados de unidade e
integração. Cobertura de contrato e de políticas de recuo ainda depende de
testes que virão na aula de testes; o que existe hoje é verificação funcional
documentada e reproduzível.
