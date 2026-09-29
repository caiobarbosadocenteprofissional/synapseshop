# Decisões Técnicas — Aula 8: Cache-aside com Redis

Registro das decisões de implementação da Aula 8, seguindo o formato das aulas
anteriores. Evidências numéricas em [`METRICAS_AULA8.md`](METRICAS_AULA8.md).

---

## 1. Escopo

A spec pede cache-aside em "um endpoint de listagem" e "um endpoint de consulta
mais pesada", com chaves no formato `pedidos:list` e `pedido:{id}`.

**Decisão:** aplicar o padrão ao catálogo já existente (`Item`), e não criar a
entidade `Pedido`.

**Motivo:** a diretriz SpecDD proíbe antecipar funcionalidades de aulas futuras.
`Pedido` não existe no domínio implementado (Aulas 4-7); criá-la apenas para
servir de exemplo de cache violaria a regra de anti-antecipação. A spec usa
`pedidos` apenas como exemplo ilustrativo ("ex.: GET /pedidos").

Consequência assumida: o endpoint de detalhe disponível
(`GET /api/v1/items/{id}/`) é uma busca por chave primária, ou seja, o caso
**menos** favorável ao cache-aside. Isso está medido e reportado em
`METRICAS_AULA8.md` (seções 3.2 e 4) em vez de mascarado.

## 2. Apenas a API Django

**Decisão:** instrumentar somente o backend Django/DRF. O microsserviço
`inventory` (FastAPI) permanece intocado.

**Motivo:** a spec pede "a API" e o cache será reutilizado em endpoints futuros;
duplicar a estratégia em FastAPI agora seria trabalho não solicitado.

## 3. Backend: `django-redis` sobre a API existente

**Decisão:** usar o cache do Django (`django-redis`) em vez de um cliente Redis
próprio nos viewsets.

**Motivos:**

- `cache.set/get/delete_many` já aplicam `KEY_PREFIX` (`:1:`), o que isola o
  ambiente de desenvolvimento dos demais bancos Redis.
- O cache do Django é o **único** ponto de integração: se o Redis cair, basta
  `IGNORE_EXCEPTIONS = True` para a API cair no PostgreSQL, sem `try/except`
  espalhado pelo código de negócio.
- Os dados cacheados são os já serializados pelo DRF (`Response.data`), portanto
  o cache guarda um `ReturnList`/`ReturnDict` pronto para renderização.

**Opção descartada:** `delete_pattern` do django-redis para a invalidação da
listagem. É seguro (usa `SCAN`), porém varre o keyspace inteiro a cada escrita.
A coleção-índice (`itens:list:indice`) é O(nº de chaves) e resolve com um único
`DEL`, medindo o custo como irrelevante para o volume da spec.

## 4. Nomenclatura de chaves

| Chave Redis (após `KEY_PREFIX`) | Conteúdo | TTL |
| :--- | :--- | ---: |
| `synapseshop:1:itens:list:<assinatura>` | página da listagem já paginada | 60 s |
| `synapseshop:1:item:<id>` | item único já serializado | 300 s |
| `itens:list:indice` | *set* com todas as assinaturas de listagem ativas | sem expiração |
| `itens:detalhe:indice` | *set* com todos os `item:<id>` ativos | sem expiração |
| `synapseshop:1:itens:metricas:*` | contadores de `HIT`/`MISS` por endpoint | 3600 s |

Os índices ficam **sem** `KEY_PREFIX` de propósito: são estrutura interna de
invalidação, não dados de negócio, e a instância Redis do Compose é exclusiva
deste projeto. Isso evita a ambiguidade de ter que prefixar manualmente cada
chave lida e escrita pelo cliente Redis cru.

**Assinatura da listagem** (`itens:list:<12 hex>`): SHA-1 de 12 caracteres sobre
a tupla ordenada de pares `(chave, valor)` de **todos** os query params
relevantes, normalizados (listas em ordem, booleanos em minúsculas).
Decisões:

- Ordenar os pares elimina o caso `?a=1&b=2` vs `?b=2&a=1` gerarando chaves
  distintas para a mesma resposta.
- Incluir **todos** os parâmetros relevantes (`search`, `ordering`, `category`,
  `is_active`, `min_price`, `max_price`, `page`, `page_size`) impede vazamento de
  resposta entre filtros diferentes.
- Par desconhecido no query string é ignorado (não invalida o cache), porque o
  serializer do DRF também o ignora.

**Detalhe de implementação:** `redis-py` devolve `bytes` em `SMEMBERS`, e o
cache do Django só aceita `str` (ele compõe a chave com f-string, produzindo
literalmente `b'item:110'`). `_texto()` normaliza antes do `delete_many`; sem
isso a invalidação falha silenciosamente. O mesmo cuidado vale para qualquer
leitura de índice.

## 5. TTL

**Decisão:** 60 s para a listagem, 300 s para o detalhe, conforme sugerido pela
spec, configuráveis por `CACHE_TTL_LISTA` e `CACHE_TTL_DETALHE`.

**Justificativa do assimetria:** a listagem agrega 10 itens e é a que
invalida com mais frequência (qualquer escrita no catálogo), logo janela curta.
O detalhe é a entidade cacheada mais consultada e a mais cara de reconstruir por
sério, logo janela maior. O TTL é uma **rede de segurança**, não o mecanismo
primário de consistência: a invalidação por evento é o mecanismo primário, e o
TTL cobre o caso de evento perdido (bug, processo morto entre a escrita no
banco e a emissão do evento).

As chaves de métricas não têm TTL na escrita, para permitir janelas longas de
observação, mas recebem limite de 1 h para não vazar memória em ambientes de
teste. Zeram-se com `POST /api/v1/cache/stats/`.

## 6. Invalidação por eventos de domínio

**Decisão:** dispatcher in-process (`services/events.py`) com
`transaction.on_commit`, e um registro de handlers em
`services/cache_invalidation.py` importado no `AppConfig.ready()` de `api`.

**Motivos:**

- `on_commit` garante que o cache só é invalidado **depois** do commit no
  PostgreSQL. Sem isso, um rollback deixaria o cache invalidado enquanto o banco
  mantém o dado — invalidação prematura seria um bug de leitura inconsistente.
- Handler com `try/except`: evento de domínio nunca derruba a requisição de
  escrita. Se o handler falhar, o log registra `handler_falhou` e o TTL assume.
- Registro em `ready()` evita import circular entre `api.apps` e `services`.

**Mapeamento evento para chaves:**

| Evento | Invalida |
| :--- | :--- |
| `ItemCriado` | `item:<id>` e todas as `itens:list:*` (a listagem muda) |
| `ItemAtualizado` | `item:<id>` e todas as `itens:list:*` |
| `ItemRemovido` | `item:<id>` e todas as `itens:list:*` |
| `CategoryCriada` | `item:<id>` e `itens:list:*` (filtro por categoria) |
| `CategoryAtualizada` | `item:<id>` e `itens:list:*` |
| `CategoryRemovida` | `item:<id>` e `itens:list:*` (cascata apaga itens) |

`PedidoAtualizado` da spec corresponde a `ItemAtualizado` no domínio
implementado: a semântica exigida (invalidar o registro e, se necessário, a
lista) foi cumprida com os eventos que existem.

**Por que invalidar a listagem inteira, e não só a página afetada?** A
invalidação cirúrgica (só a página 3, só a ordenação X) exigiria conhecer a
relação entre cada chave e o item alterado. Como qualquer escrita altera o
`COUNT` da paginação, a coleção inteira é a opção correta e simples; o custo
(1 `SMEMBERS` mais o `DEL` de algumas chaves) é desprezível neste volume. A
otimização por tag ou padrão fica reservada a quando houver volume que a
justifique.

**Por que sem Kafka/RabbitMQ?** Proibido explicitamente pela spec e pela
diretriz SpecDD (reservado às aulas 9-11). O dispatcher in-process atende ao
escopo; a interface `emitir()` é o ponto de extensão para publicação em broker
quando a arquitetura exigir desacoplamento entre processos.

## 7. Header `X-Cache` e logs

**Decisão:** expor `X-Cache: HIT | MISS | BYPASS` nas respostas e registrar
`cache.lookup` em log estruturado JSON no logger `synapseshop.cache`.

- `HIT` — servido do Redis; `MISS` — consultou o PostgreSQL e preencheu;
  `BYPASS` — cache desativado (`CACHE_ENABLED=false`), resposta direta.
- `origem` no log distingue `postgresql` de `redis`, tornando o ciclo auditável.
- `LOGGING` foi adicionado a `config/settings.py` nesta aula: sem ele o
  `logger.info()` do namespace `synapseshop` não tinha handler e o log era
  descartado silenciosamente (Django só configura o logger `django`).

**Risco considerado:** omitir o `X-Cache` em produção, por revelar o estado
interno do cache. Mantido aqui porque é requisito didático da spec e porque
nenhum dado sensível é exposto — em produção, remover ou condicionar a `DEBUG`.

## 8. Kill-switch `CACHE_ENABLED`

**Decisão:** variável de ambiente booleana, com `LocMemCache` como backend
neutro quando `false`.

**Motivo:** permite comparar antes e depois na mesma imagem (ver
`METRICAS_AULA8.md` seção 3) e degradar com segurança se o Redis ficar instável
em produção, sem novo deploy de código. `BYPASS` no header torna o estado
observável no lado do cliente.

`IGNORE_EXCEPTIONS = True` no `django-redis` garante que uma falha de conexão
no Redis vire um `get` vazio (fallback ao banco) em vez de `500`.

## 9. Efeito colateral: throttling do DRF passou a usar o Redis

**Decisão:** aceitar o efeito colateral e documentá-lo.

**Motivo:** o throttling do DRF usa o cache `default` do Django. Ao apontar esse
cache para o Redis, os contadores de `AnonRateThrottle`, `UserRateThrottle` e
`ScopedRateThrottle` passaram a viver no Redis. **Ganho:** throttling correto
com múltiplos workers (antes cada processo tinha sua própria contagem, e o
limite efetivo era N vezes maior que o configurado). **Custo:** o estado
sobrevive a reinícios do contêiner até a janela expirar (60 s), o que fez um
teste de autenticação falhar logo após uma troca de configuração — é preciso
aguardar a janela ou limpar as chaves `throttle_*`.

Não foi criado um segundo cache só para o throttling: a complexidade não se
justifica no escopo da spec, e o comportamento resultante é o desejado.

## 10. Métricas

**Decisão:** contadores incrementais no próprio Redis, expostos em
`GET /api/v1/cache/stats/` e zerados por `POST` na mesma rota, restritos a
`admin`.

**Motivos:**

- Contadores no Redis são incrementais (`INCR`), sem `SET` — o caminho crítico
  (uma escrita por requisição) fica barato.
- Métricas no mesmo backend do cache evitam uma segunda tecnologia (Prometheus,
  StatsD) que a spec não pediu.
- `hit_rate = total_hits / total_lookups` por endpoint e global, conforme a
  spec.
- Separar em `GET` e `POST` na mesma rota segue a convenção REST da API e evita
  `/cache/stats/reset/`, que parece um recurso de escrita em um resource de
  métricas.

O método de escrita (invalidação) **não** altera os contadores: eles medem
eficiência de leitura (hits sobre lookups), não taxa de invalidação.

## 11. Escopo do commit

Não foram criados, nem como placeholder, artefatos das aulas 9-11 (Kafka,
RabbitMQ, workers, IA). Nenhuma referência a eles aparece em código ou
configuração. Os únicos artefatos adicionados são os de suporte à própria aula:
`services/`, `seed_demo_catalog.py`, `scripts/bench_cache.py` e
`scripts/smoke_test_cache.py`.

---

## Resumo

| Tema | Decisão |
| :--- | :--- |
| Entidade cacheada | `Item` (catálogo existente); `Pedido` fora de escopo |
| Backend | `django-redis` como cache `default` do Django |
| Chave de listagem | `itens:list:<assinatura SHA-1 dos query params>` |
| Chave de detalhe | `item:<id>` |
| TTL | 60 s (lista) e 300 s (detalhe), configuráveis |
| Invalidação | eventos de domínio in-process + `transaction.on_commit` |
| Invalidação de lista | coleção-índice `itens:list:indice` (sem `SCAN`) |
| Métricas | contadores no Redis, `GET`/`POST /api/v1/cache/stats/` (admin) |
| Observabilidade | header `X-Cache` + log JSON `cache.lookup` |
| Kill-switch | `CACHE_ENABLED` com `LocMemCache` neutro quando `false` |
| Falha do Redis | `IGNORE_EXCEPTIONS=True` com fallback ao PostgreSQL |
