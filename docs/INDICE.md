# Índice da documentação

Ponto de entrada para a documentação do SynapseShop. O [README](../README.md)
continua sendo o guia narrativo da entrega; este índice organiza os documentos
por assunto para quem precisa de uma resposta específica.

## Visão geral e arquitetura

| Documento | Para quê |
| --- | --- |
| [README](../README.md) | Visão do produto, arquitetura-alvo, endpoints, exemplos e operação. |
| [GUIA_MENSAGERIA](GUIA_MENSAGERIA.md) | Fluxo pedido ➔ pagamento ➔ notificação, topologia e diagnóstico. |
| [CONVENCOES_API](CONVENCOES_API.md) | Paginação, filtros, erros e cabeçalhos da API. |
| [OPENAPI](OPENAPI.md) | Como o contrato é servido e validado. |
| [openapi.yaml](../openapi.yaml) | Contrato OpenAPI 3.0.3 (fonte de verdade das rotas). |

## Decisões técnicas

| Documento | Assunto |
| --- | --- |
| [DECISOES_TECNICAS_AULA7](DECISOES_TECNICAS_AULA7.md) | JWT, papéis e throttling. |
| [DECISOES_TECNICAS_AULA8](DECISOES_TECNICAS_AULA8.md) | Cache-aside, chaves e invalidação. |
| [DECISOES_TECNICAS_AULA9](DECISOES_TECNICAS_AULA9.md) | RabbitMQ, reentrega e DLQ. |
| [DECISOES_TECNICAS_AULA10](DECISOES_TECNICAS_AULA10.md) | Kafka, partições e offset manual. |
| [DECISOES_TECNICAS_AULA14](DECISOES_TECNICAS_AULA14.md) | Camada de IA, resiliência e privacidade. |

## Medições e checklists

| Documento | Conteúdo |
| --- | --- |
| [METRICAS_AULA8](METRICAS_AULA8.md) | Hit rate, latência e ganho do cache. |
| [METRICAS_AULA10](METRICAS_AULA10.md) | Desempenho da mensageria e do paralelismo. |
| [METRICAS_AULA14](METRICAS_AULA14.md) | Latência, tokens, custo e circuito da IA. |
| [CHECKLIST_INTEGRADOR_EXTERNO](CHECKLIST_INTEGRADOR_EXTERNO.md) | O que validar ao consumir a API. |
| [CHECKLIST_IA_SAFE](CHECKLIST_IA_SAFE.md) | Requisitos de uso seguro do assistente. |
| [BACKLOG_AULA14](BACKLOG_AULA14.md) | Evoluções conscientemente fora do MVP. |

## Operação

| Recurso | Para quê |
| --- | --- |
| [scripts/smoke_test_auth.py](../scripts/smoke_test_auth.py) | Login, papéis e throttling. |
| [scripts/smoke_test_cache.py](../scripts/smoke_test_cache.py) | Ciclo miss/hit, invalidação e métricas. |
| [scripts/smoke_test_mensageria.py](../scripts/smoke_test_mensageria.py) | Reentrega, DLQ e reprocessamento. |
| [scripts/smoke_test_fluxo.py](../scripts/smoke_test_fluxo.py) | Fluxo ponta a ponta pedido ➔ notificação. |
| [scripts/validar_openapi.py](../scripts/validar_openapi.py) | Drift entre contrato e rotas reais. |
| [scripts/bench_cache.py](../scripts/bench_cache.py) | Benchmark antes/depois do cache. |
| [scripts/bench_mensageria.py](../scripts/bench_mensageria.py) | Benchmark do consumo por partições. |

## Coleções e histórico

| Recurso | Conteúdo |
| --- | --- |
| [Postman](postman/SynapseShop.postman_collection.json) | Coleção consolidada (46 requisições) e ambiente local. |
| [docs/historico](historico) | Decisões e métricas das aulas encerradas. |
