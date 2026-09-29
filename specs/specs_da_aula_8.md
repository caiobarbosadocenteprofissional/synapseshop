Spec: Cache-aside com Redis (Aula 8)

1. Objetivo

Otimizar o desempenho da API através da aplicação do padrão cache-aside utilizando Redis para o catálogo e pedidos. O objetivo central compreende a gestão do tempo de vida dos dados em cache (TTL) e a implementação de estratégias robustas para a sua invalidação.

2. Contexto

No estrito cumprimento da diretriz de desenvolvimento incremental e restrição de escopo (SpecDD), o trabalho desta etapa foca-se exclusivamente nos requisitos de otimização e integração do cache. Sob a regra de proibição de antecipação (Anti-Hallucination Rule), a equipa não deve implementar lógicas de filas de mensageria assíncrona com Kafka ou RabbitMQ, ferramentas cujo desenvolvimento se encontra explicitamente reservado para o bloco das aulas 9 a 11.

3. Tarefas e Responsabilidades

Implementação do Cache-aside: Realizar a instrumentação de um endpoint focado em listagem (ex.: GET /pedidos) e de um endpoint de consulta mais pesada (ex.: GET /pedidos/{id}/detalhes) com a aplicação do padrão cache-aside.

Gestão de Chaves e Expiração: Definir chaves de cache claras, como pedidos:list e pedido:{id}. Atribuir-lhes prazos de validade ou TTL, como um tempo inicial sugerido de 60s para a lista e 300s para a consulta de detalhes.

Estratégia de Invalidação: Desenhar e implementar um mecanismo de invalidação de cache associado a eventos do domínio, como garantir que o evento de PedidoAtualizado resulta na invalidação do respetivo pedido:{id} e, caso seja necessário, na invalidação da lista.

Avaliação de Desempenho: Executar e comparar as medições (latência média, p95 e RPS) antes da introdução do cache e depois da sua implementação. Realizar demonstrações em tempo real de todo o ciclo de procura de dados, compreendendo as fases de miss, preenchimento e hit.

Exposição de Métricas: Recolher a métrica de eficácia do cache, ou hit rate (calculado via total_hits/total_lookups), e expor a mesma por endpoint, quer seja num endpoint dedicado a métricas, quer seja através de registos de logs estruturados.

4. Requisitos de Entrega (Definition of Done)

[x] O Redis, operando como sistema de cache-aside, foi incluído na orquestração e configuração arquitetural do projeto.

[x] O padrão cache-aside foi executado com sucesso e encontra-se a funcionar num endpoint de listagem e num de acesso a dados específicos.

[x] O sistema faz uso correto de nomenclatura de chaves, bem como a definição e respeito pelo tempo de vida dos dados (TTL).

[x] Foi implementada uma regra operacional para a invalidação do cache baseada em eventos vinculados ao negócio.

[x] O ficheiro README.md foi devidamente atualizado, documentando as estratégias de invalidação adotadas e registando detalhadamente as melhorias de desempenho obtidas através das medições efetuadas.

[x] A implementação não violou a diretriz de contexto restrito, não apresentando qualquer placeholder ou configuração pertencente a funcionalidades futuras.

5. Evidências de Conclusão

| Requisito | Evidência |
| :--- | :--- |
| Redis na orquestração | `docker-compose.yml` (serviço `redis:7-alpine`, healthcheck, volume `redisdata`), `config/settings.py` (`CACHES` com `django-redis`), `requirements.txt` |
| Cache-aside em listagem e detalhe | `GET /api/v1/items/?page_size=10` (TTL 60s) e `GET /api/v1/items/{id}/` (TTL 300s), com `X-Cache: HIT/MISS/BYPASS` |
| Nomenclatura e TTL | `itens:list:<assinatura>`, `item:<id>`, índices `itens:list:indice` e `itens:detalhe:indice`; expiração de 60s demonstrada em tempo real |
| Invalidação por evento | `services/events.py` + `services/cache_invalidation.py` com `transaction.on_commit`; `ItemAtualizado` invalida `item:<id>` e todas as listas |
| README e desempenho | Seção 11 do README; latência média −29,7% (lista) e −29,1% (detalhe), RPS +42,1% e +41,0% |
| Métricas de hit rate | `GET /api/v1/cache/stats/` (hit rate 0,9756 na lista e 0,9615 no detalhe) e log estruturado `cache.lookup` |
| Escopo restrito | Sem Kafka/RabbitMQ, sem workers e sem IA; nenhuma referência a artefatos das aulas 9-11 |
| Verificação | `scripts/smoke_test_cache.py` 29/29, `scripts/smoke_test_auth.py` 13/13, `manage.py check` sem issues, sem migrações pendentes |

Detalhes em [`docs/DECISOES_TECNICAS_AULA8.md`](../docs/DECISOES_TECNICAS_AULA8.md)
e [`docs/METRICAS_AULA8.md`](../docs/METRICAS_AULA8.md).