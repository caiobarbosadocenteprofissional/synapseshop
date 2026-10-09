# Convenções da API (SynapseShop)

Este documento resume as convenções que os consumidores da API devem seguir. Todas são refletidas no [`openapi.yaml`](../openapi.yaml) da raiz.

## Base

- **API principal**: `http://localhost:8000` (rodando via Docker Compose)
- **Prefixo**: `/api/v1/`
- **Formato**: JSON em todas as requisições e respostas
- **Autenticação**: Bearer JWT (`Authorization: Bearer <access_token>`)
- **Papel (`role`)**: `admin` (operações administrativas, ex.: criar/editar categoria/item) ou `user` (operações não-administrativas)

## Paginação

A paginação padrão é por número de página, compatível com DRF:

| Parâmetro | Tipo | Padrão | Observação |
|---|---|---|---|
| `page` | `integer` | `1` | Número da página (base 1). |
| `page_size` | `integer` | `10` | Máximo `100`. |

Envelopes padronizados (`PageNumberPagination`):

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [...]
}
```

A equipe documenta também a alternativa `limit`/`nextCursor` para referências futuras (ver `docs/README_AULA13.md` e OpenAPI).

## Ordenação e Filtros

| Parâmetro | Recurso | Aplicação |
|---|---|---|
| `ordering` | categorias, itens | Campo a ordenar; prefixo `-` para decrescente (ex.: `-created_at`). Equivale a `sort=campo:asc\|desc`. |
| `search` | categorias, itens | Busca textual em campos indexados. |
| `is_active` | itens | Filtro booleano (`true`/`false`, `1`/`0`, `yes`/`no`). |
| `category` | itens | Filtra por ID da categoria (`?category=1`). |

## Erros (RFC 7807)

Os erros seguem o padrão `application/problem+json` (inspirado em RFC 7807). Os códigos mais usados:

| Código | Uso |
|---|---|
| `400` | Requisição inválida (validação de campos). |
| `401` | Não autenticado ou credenciais inválidas. |
| `403` | Autenticado, mas sem permissão para a ação (requer `admin`). |
| `404` | Recurso não encontrado. |
| `409` | Conflito (ex.: condição de unicidade não atendida). |
| `429` | Throttling (limite de requisições excedido). |
| `503` | `GET /health/pronto`: alguma dependência não responde. |

O contrato descreve o esquema `Problem` com os campos `type`, `title`, `status`, `detail`, `instance`, `errors`. O backend responde ao menos com `detail` nos casos mais comuns, preservando compatibilidade.

## Cabeçalhos de contrato

| Cabeçalho | Uso | Obrigatório |
|---|---|---|
| `Authorization` | `Bearer <access_token>` | Sim (para rotas protegidas). |
| `Idempotency-Key` | Chave de idempotência para `POST /api/v1/pedidos/`. Pode ser enviado também no corpo (`idempotency_key`). Repetir a chave devolve o mesmo pedido (201 ou 200) sem duplicar efeitos. | Não obrigatório, mas **fortemente recomendado** para chamadas de criação. |
| `X-Trace-Id` | Identificador de correlação. Quando enviado na criação do pedido, vira `correlation_id` e é ecoado na resposta. Propaga-se no fluxo pedido ➔ pagamento ➔ notificação. | Opcional. |

## Cache

As leituras que usam cache-aside retornam `X-Cache` com um dos valores:

- `HIT`: retornado do Redis.
- `MISS`: lido do PostgreSQL e armazenado.
- `BYPASS`: cache desativado (`CACHE_ENABLED=false`) ou não aplicável.

## Pagamentos e Notificações

- `POST /api/v1/pedidos/{id}/pagamento/` simula o desfecho do adquirente (`resultado` = `APROVADO`/`RECUSADO`, `forma_pagamento` em [`cartao_credito`, `cartao_debito`, `pix`, `boleto`]). Repetir a chamada devolve **200** com o pagamento existente e **não publica evento novo**.
- `GET /api/v1/notificacoes/` lista as notificações gravadas pelo `notificacao-worker` a partir do evento `PagamentoProcessado`. Os resultados são mais recentes primeiro.

## Observabilidade (health)

- `GET /health`: **liveness** — responde enquanto o processo está no ar. Não consulta dependências.
- `GET /health/pronto`: **readiness** — verifica PostgreSQL, Redis e broker. Retorna `503` quando alguma dependência está fora do ar.

## Documentação interativa

- `GET /docs/` — Swagger UI
- `GET /docs/redoc/` — ReDoc
- `GET /openapi.yaml` — Contrato na raiz (usado pelas interfaces e por validadores)
- `http://localhost:8100/docs` e `http://localhost:8100/redoc` — Microsserviço de inventário (FastAPI), fora deste contrato
