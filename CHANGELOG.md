# Changelog

Todas as alterações relevantes deste projeto são documentadas neste arquivo.

## [Unreleased]

## [2026.10.14] — Aula 14: Assistente de IA (`llm_service`) e endpoint `/api/v1/assist`

### Adicionado

- **`services/llm.py`** — camada de IA com resiliência:
  - **Timeout** por tentativa (`LLM_TIMEOUT_S`, default 5s).
  - **Retry** com backoff exponencial + jitter (*equal jitter*), apenas para erros reentregáveis (`LLMTimeout`, `LLMTaxaLimitada`/429, `LLMIndisponivel`/5xx-rede); `LLMPayloadInvalido`/4xx não é repetido.
  - **Circuit breaker** `closed`/`open`/`half-open` (`LLM_CIRCUITO_LIMITE_FALHAS`, `LLM_CIRCUITO_RESET_SEGUNDOS`).
  - **Redação** de e-mail, CPF, CNPJ, cartão, telefone, segredos e `Bearer` antes do envio e antes do log (só a contagem vai para o log).
  - **Telemetria** em memória: latência, erros por tipo, tokens e custo estimado.
  - **Transporte** via stdlib (`urllib`), sem dependência nova; erro de domínio com `status_http` (503/504/429/502/400).
- **`services/prompts.py`** — templates de prompt (`summarize` e `explain`), normalização da entrada (`str`/lista) e montagem das mensagens.
- **Endpoint `POST /api/v1/assist`** (autenticado): valida `{ mode, logs, temperature, max_tokens }` e devolve `{ answer, meta }`. `max_tokens` limitado no servidor a `LLM_MAX_TOKENS_LIMITE`.
- **Endpoint `GET`/`POST /api/v1/assist/stats/`** (admin): consulta e zera a telemetria, além do estado do circuito.
- **Settings `LLM_*`** em `config/settings.py` e nos defaults do Compose: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `LLM_MAX_TENTATIVAS`, `LLM_BACKOFF_BASE_MS`, `LLM_BACKOFF_MAX_MS`, `LLM_CIRCUITO_LIMITE_FALHAS`, `LLM_CIRCUITO_RESET_SEGUNDOS`, `LLM_MAX_TOKENS_LIMITE`, `LLM_PRECO_PROMPT_USD_MILHAO`, `LLM_PRECO_OUTPUT_USD_MILHAO`. Sem `LLM_API_KEY` o assistente responde 503 (kill-switch).
- **Testes** (64): `tests/unit/test_services_llm.py` (falhas 429/5xx/4xx/timeout/rede, retry, backoff, circuito, telemetria/custo), `tests/unit/test_services_redacao.py` (redação e privacidade) e `tests/integration/test_api_assist.py` (contrato HTTP 401/400/200/429/502/503/504 e métricas admin).
- **Documentação**: seção 16 do `README.md`, `docs/DECISOES_TECNICAS_AULA14.md`, `docs/METRICAS_AULA14.md` e o contrato `openapi.yaml` (paths `/api/v1/assist/` e `/api/v1/assist/stats/`, schemas `AssistRequest`/`AssistResponse`/`AssistMeta`/`AssistStats`).

### Observações

- Nenhuma dependência nova: o transporte HTTP usa a biblioteca padrão.
- Escopo SpecDD: sem cache de respostas nem *guardrails* de saída (registrados como evolução futura).
- Cobertura de `services/llm.py` e `services/prompts.py` em 100%; a suíte completa permanece acima do `fail_under=85`.

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
- **Coleções Postman**: coleção consolidada `docs/postman/SynapseShop.postman_collection.json` e environment `docs/postman/SynapseShop_Local.postman_environment.json`.
- **Testes de documentação**: `tests/integration/test_api_docs.py` cobre Swagger UI, ReDoc, servico do `openapi.yaml`, caso ausente e os headers de contrato.

### Alterado

- `api/views.py`: leitura de `Idempotency-Key`/`X-Trace-Id` em `PedidoCreateView` (sem mudanças de regras de negócio, apenas contrato/documentação).
- `config/urls.py`: inclusão das rotas `/docs/`, `/docs/redoc/`, `/openapi.yaml`.

### Observações

- `openapi.yaml` fica **na raiz** intencionalmente: `.dockerignore` exclui `docs/`, `specs/`, `README.md`, `PROMPTS.md`, portanto o contrato precisa estar fora de `docs/` para ser incluído em `COPY . .` na imagem Docker.
- Nenhuma dependência nova foi adicionada. A documentação usa CDN (Swagger UI/ReDoc), sem `drf-spectacular`.
- O microsserviço de inventário (FastAPI) mantém sua própria documentação em `http://localhost:8100/docs` e não é replicado neste contrato.
- Cobertura: novo teste cobre `api/docs.py` e o fluxo de headers; a suíte continua acima de 85% (comportamento verificado pelo `pytest --cov`).
