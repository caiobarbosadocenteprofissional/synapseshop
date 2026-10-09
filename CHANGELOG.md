# Changelog

Todas as alterações relevantes deste projeto são documentadas neste arquivo.

## [Unreleased]

## [2026.10.09] — Aula 13: Documentação da API com OpenAPI/Swagger e Postman/Insomnia

### Adicionado

- **OpenAPI 3.0.3**: `openapi.yaml` na raiz do repositório, cobrindo todos os endpoints reais da API (health, auth JWT, categorias, itens com cache, cache/stats, pedidos com idempotência, pagamento, notificações). Inclui:
  - Esquema `Problem` inspirado em RFC 7807 (`application/problem+json`)
  - Cabeçalhos `Authorization`, `Idempotency-Key`, `X-Trace-Id`, `X-Cache`
  - Paginação `page`/`page_size`, filtros `search`, `is_active`, `category`, ordenação `ordering`
  - Exemplos de request/response e status codes 2xx/4xx/5xx
- **Interfaces de documentação**: `api/docs.py` com Swagger UI (`/docs/`) e ReDoc (`/docs/redoc/`) servidos via CDN (unpkg), além de `/openapi.yaml`. Rotas registradas em `config/urls.py`.
- **Suporte a headers no fluxo de pedidos**: `PedidoCreateView` aceita `Idempotency-Key` (além do campo `idempotency_key` no corpo), usa `X-Trace-Id` como `correlation_id` quando informado e o ecoa na resposta 201.
- **Documentação markdown**: `docs/CONVENCOES_API.md`, `docs/CHECKLIST_INTEGRADOR_EXTERNO.md`, `docs/OPENAPI.md`.
- **Coleções Postman**: `docs/postman/SynapseShop_Aula13.postman_collection.json` e environment `docs/postman/SynapseShop_Local.postman_environment.json` (mantida também `SynapseShop_Aula7.postman_collection.json`).
- **Testes de documentação**: `tests/integration/test_api_docs.py` cobre Swagger UI, ReDoc, servico do `openapi.yaml`, caso ausente e os headers de contrato.

### Alterado

- `api/views.py`: leitura de `Idempotency-Key`/`X-Trace-Id` em `PedidoCreateView` (sem mudanças de regras de negócio, apenas contrato/documentação).
- `config/urls.py`: inclusão das rotas `/docs/`, `/docs/redoc/`, `/openapi.yaml`.

### Observações

- `openapi.yaml` fica **na raiz** intencionalmente: `.dockerignore` exclui `docs/`, `specs/`, `README.md`, `PROMPTS.md`, portanto o contrato precisa estar fora de `docs/` para ser incluído em `COPY . .` na imagem Docker.
- Nenhuma dependência nova foi adicionada. A documentação usa CDN (Swagger UI/ReDoc), sem `drf-spectacular`.
- O microsserviço de inventário (FastAPI) mantém sua própria documentação em `http://localhost:8100/docs` e não é replicado neste contrato.
- Cobertura: novo teste cobre `api/docs.py` e o fluxo de headers; a suíte continua acima de 85% (comportamento verificado pelo `pytest --cov`).
