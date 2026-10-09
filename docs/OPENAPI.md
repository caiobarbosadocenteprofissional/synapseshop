# Documentação OpenAPI (Aula 13)

## Visão geral

A documentação interativa da API principal (Django REST Framework) foi materializada em:

- **Contrato**: [`openapi.yaml`](../openapi.yaml) — OpenAPI 3.0.3, na **raiz** do repositório (essencial porque `.dockerignore` exclui `docs/` da imagem Docker; assim o arquivo é copiado por `COPY . .`).
- **Swagger UI**: [`/docs/`](http://localhost:8000/docs/) — carrega o contrato via CDN (unpkg, `swagger-ui-dist@5.17.14`).
- **ReDoc**: [`/docs/redoc/`](http://localhost:8000/docs/redoc/) — carrega o contrato via CDN (`redoc@2.1.5`).
- **Serviço direto**: [`/openapi.yaml`](http://localhost:8000/openapi.yaml) — devolve o arquivo bruto com `Content-Type: application/yaml`.

As rotas acima foram adicionadas em [`config/urls.py`](../config/urls.py) e implementadas em [`api/docs.py`](../api/docs.py).

## Escopo coberto

O contrato cobre todos os endpoints reais, com seus status codes, headers e schemas:

- `/health` (liveness)
- `/health/pronto` (readiness; inclui 503)
- `/api/v1/auth/token/` e `/api/v1/auth/token/refresh/` (JWT + claim `role`)
- `/api/v1/categories/` (CRUD) — proteção admin em escrita
- `/api/v1/items/` (CRUD) — inclui filtros `is_active`, `category`, cache-aside (`X-Cache` em list/retrieve)
- `/api/v1/cache/stats/` (GET/POST) — restrito a admin
- `/api/v1/pedidos/` (POST) — **Idempotency-Key** (header) e **idempotency_key** (body); **X-Trace-Id** (header), ecoado em resposta; responde 201/200/202 conforme cenário; `evento_publicado`
- `/api/v1/pedidos/{id}/` (GET) — acesso dono ou admin, `X-Cache`
- `/api/v1/pedidos/{id}/pagamento/` (POST) — simulação; idempotente (retorna 200 sem novo evento)
- `/api/v1/notificacoes/` (GET) — do usuário autenticado

## Padrões adotados

- **Segurança**: `bearerAuth` (HTTP Bearer JWT)
- **Paginação**: `page` (base 1), `page_size` (default 10, max 100), envelope `count/next/previous/results`
- **Ordenação**: `ordering` com prefixo `-`; referência a `sort=campo:asc|desc` na descrição
- **Erros**: esquema `Problem` inspirado na **RFC 7807** (`application/problem+json`)
- **Headers**: `Idempotency-Key`, `X-Trace-Id`, `X-Cache` documentados explicitamente
- **Tipos monetários**: valores `price`, `total`, `preco_unitario`, `valor` serializados como `string` com `pattern: ^\d+(\.\d{1,2})?$` (evita perda de precisão com Decimal)
- **Enums reais**: refletem exatamente os choices do modelo (status de pedido, status de pagamento, formas, canais, broker selecionado, etc.)

## Validação e testes

- Teste de integração: [`tests/integration/test_api_docs.py`](../tests/integration/test_api_docs.py) garante a disponibilização das rotas e a presença do `openapi.yaml` na raiz.
- Lint OpenAPI: previsto com [`@redocly/cli`](https://redocly.com/docs/cli/) (`npx @redocly/cli lint openapi.yaml`) ou [Spectral](https://stoplight.io/open-source/spectral). Nenhuma dependência foi adicionada — roda via `npx` (requer rede no momento da execução).
- O contrato não usa `drf-spectacular`; as interfaces são HTML estático com scripts CDN, conforme especificado na Aula 13.

## Referências

- [`specs/specs_da_aula_13.md`](../specs/specs_da_aula_13.md) — escopo da aula
- [`specs/00_diretriz_incremental_specdd.md`](../specs/00_diretriz_incremental_specdd.md) — regra incremental
- [`CHANGELOG.md`](../CHANGELOG.md) — registro da entrega da Aula 13
- Coleções Postman: [`docs/postman/SynapseShop_Aula13.postman_collection.json`](postman/SynapseShop_Aula13.postman_collection.json), [`docs/postman/SynapseShop_Aula7.postman_collection.json`](postman/SynapseShop_Aula7.postman_collection.json) e environment [`docs/postman/SynapseShop_Local.postman_environment.json`](postman/SynapseShop_Local.postman_environment.json)
