# Checklist do Integrador Externo

Este checklist ajuda a validar a integração com a SynapseShop API antes de ir para produção/homologação.

## Pré-requisitos

- [ ] A API está acessível: `http://localhost:8000` (local) ou o host fornecido.
- [ ] Usuários demo existem: `python manage.py seed_demo_users` executado (ambiente local com Compose).
- [ ] Pode obter token JWT em `POST /api/v1/auth/token/` com `admin` ou `user`.

## Autenticação e segurança

- [ ] Envia `Authorization: Bearer <access_token>` em todas as rotas protegidas.
- [ ] Usa `POST /api/v1/auth/token/refresh/` para renovar o `access_token` antes da expiração.
- [ ] Respeita os códigos `401`/`403` (falta de autenticação / falta de permissão).
- [ ] Respeita `429` Too Many Requests (throttling).

## Documentação e contrato

- [ ] Consulta `/docs/` (Swagger UI), `/docs/redoc/` (ReDoc) e `/openapi.yaml` para ver o contrato vigente.
- [ ] Valida requisições/respostas contra o `openapi.yaml` (ex.: Redocly CLI, Spectral ou `openapi-validator`).
- [ ] Verifica schemas, exemplos e status codes esperados.

## Fluxo de negócio

- [ ] Lista categorias/itens com paginação (`page`, `page_size`), filtros (`search`, `is_active`, `category`) e ordenação (`ordering`).
- [ ] Cria pedido via `POST /api/v1/pedidos/`. **Recomenda** enviar `Idempotency-Key` e/ou `idempotency_key` no corpo.
- [ ] Se enviar `X-Trace-Id` na criação, espera que ele retorne no header da resposta 201 e esteja no `correlation_id`.
- [ ] Ao repetir a mesma `Idempotency-Key`, espera `200` e o mesmo pedido (sem duplicação).
- [ ] Consulta o pedido via `GET /api/v1/pedidos/{id}/` e observa `X-Cache` (`HIT`/`MISS`/`BYPASS`).
- [ ] Realiza pagamento via `POST /api/v1/pedidos/{id}/pagamento/` com `resultado`/`forma_pagamento`. Repetição deve retornar `200` (idempotente).
- [ ] Lista notificações em `GET /api/v1/notificacoes/` para verificar o efeito do `notificacao-worker`.

## Health e cache

- [ ] Verifica `GET /health` (liveness) — deve retornar 200 `{"status":"ok"}`.
- [ ] Verifica `GET /health/pronto` (readiness) — 200 quando todas as dependências ok, 503 caso contrário.
- [ ] Se tiver papel `admin`, consulta/zera `GET/POST /api/v1/cache/stats/`.

## Observações operacionais

- [ ] O contrato OpenAPI está na **raiz** do repositório para ser incluído na imagem Docker (pois `.dockerignore` exclui `docs/`).
- [ ] Interfaces de docs são servidas via CDN (Swagger UI/ReDoc), sem drf-spectacular.
- [ ] Inventário (FastAPI) tem documentação própria em `:8100/docs` e `:8100/redoc` (não incluída neste contrato).
