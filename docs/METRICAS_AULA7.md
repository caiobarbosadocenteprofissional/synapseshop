# Métricas — Aula 7 (Autenticação JWT, Throttling e Acesso)

> Evidência funcional da camada de acesso seguro implementada na Aula 7.
> Smoke test reproduzível em [`scripts/smoke_test_auth.py`](../scripts/smoke_test_auth.py).

---

## 1. Ambiente de validação

- **Execução:** contêiner Docker `synapseshop:dev` (porta `8000`), com `migrate`,
  `seed_demo_users` e `runserver` no start.
- **Persistência:** a API principal roda sobre o PostgreSQL do Compose
  (`postgres:16-alpine`, porta `5432`, volume `pgdata`), o mesmo banco do `inventory`.
  Verificado com `psql` na seção 6.
- **Ferramenta:** script `scripts/smoke_test_auth.py` (stdlib, `urllib`), seguindo o
  padrão dos smoke tests do projeto.
- **Taxas configuradas (defaults de dev):** `anon=20/min`, `user=200/min`,
  `login=5/min`; access JWT = 60 min, refresh = 7 dias.

## 2. Resultado do smoke test

**13/13 PASS** — em 1 único loop sobre a API conteinerizada:

| # | Cenário | Resultado esperado | Observação |
| :-- | :--- | :--- | :--- |
| 1 | `GET /health` (público) | 200 | permanece livre de auth |
| 2 | login `admin` | 200 | access + refresh + `role=admin` |
| 3 | login `user` | 200 | `role=user` |
| 4 | login senha errada | 401 | sem token emitido |
| 5 | refresh token | 200 | novo access + `role=admin` |
| 6 | `GET /api/v1/categories/` sem token | 401 | acesso negado |
| 7 | `GET /api/v1/categories/` com admin | 200 | envelope `count/results` |
| 8 | `POST /api/v1/categories/` admin | 201 | rota administrativa ok |
| 9 | `POST /api/v1/categories/` user | 403 | não-admin bloqueado |
| 10 | `POST /api/v1/items/` admin | 201 | idem rota administrativa |
| 11 | `GET /api/v1/items/?category=&is_active=&search=&ordering=` | 200 | filtros aplicados |
| 12 | `DELETE /api/v1/categories/{id}/` admin | 204 | rota administrativa ok |
| 13 | 6º login no intervalo de 1 min | 429 | throttle `login` |

## 3. Throttling observado

- Com `THROTTLE_LOGIN=5/min`, o **6º** POST em `/api/v1/auth/token/` no mesmo minuto
  retornou `429 Too Many Requests` (código de erro padrão do DRF). A checagem acontece
  antes da validação de credenciais — ponto de mitigação contra força bruta.
- O throttle global `anon`/`user` não interfere nas rotas de token, pois estas usam o
  `ScopedRateThrottle` com escopo `login`.

## 4. Paginação e filtros observados

- `GET /api/v1/categories/` devolve o envelope `{count, next, previous, results}` com
  `page_size` default = 10 e `page_size` como nome da query param (ex.: `?page_size=5`).
- `GET /api/v1/items/?search=Notebook&is_active=true&category={id}&ordering=price`
  aplicou busca textual, filtros de ativo/categoria e ordenação em uma única resposta 200.

## 5. Cobertura dos cenários Postman

A coleção [`SynapseShop_Aula7.postman_collection.json`](postman/SynapseShop_Aula7.postman_collection.json)
cobre os cenários 1–13 com asserts de status e body, incluindo os casos de erro (401),
acesso negado (403) e throttling (429) exigidos pelo DoD.

## 6. Persistência em PostgreSQL (verificação da Camada 5)

A autenticação deixou de resolver `User`, `role` e o token de um `db.sqlite3` local
(dentro do contêiner, sem volume) e passou a usar o PostgreSQL compartilhado.

**Tabelas no banco `synapseshop`** (`psql -c "\dt"`) — Django e `inventory` no mesmo banco:

```
 Schema |                Name                | Type  |    Owner
--------+------------------------------------+-------+------------
 public | alembic_version                    | table | synapseshop
 public | auth_group                         | table | synapseshop
 public | auth_group_permissions             | table | synapseshop
 public | auth_permission                    | table | synapseshop
 public | django_content_type                | table | synapseshop
 public | django_migrations                  | table | synapseshop
 public | inventory_items                    | table | synapseshop
 public | repositories_category              | table | synapseshop
 public | repositories_item                  | table | synapseshop
 public | repositories_user                  | table | synapseshop
 public | repositories_user_groups           | table | synapseshop
 public | repositories_user_user_permissions | table | synapseshop
(12 rows)
```

**Usuários seedados pelo `seed_demo_users`** (`select ... from repositories_user`):

```
 id | username | role  | is_superuser | is_active
----+----------+-------+--------------+-----------
  1 | admin    | admin | t            | t
  2 | user     | user  | f            | t
```

**Ausência de SQLite no contêiner** (`docker compose exec api ls -la /app | grep -i sqlite`):
`NENHUM arquivo SQLite`.

**Driver instalado no build** — wheel pré-compilada, compatível com o multistage build
(`pip install --no-index`):

```
Processing /wheels/psycopg-3.3.6-py3-none-any.whl
Processing /wheels/psycopg_binary-3.3.6-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
Successfully installed ... psycopg-3.3.6 psycopg-binary-3.3.6 ...
```

**Nenhuma migração nova foi necessária** — `repositories.0001_initial` e
`repositories.0002_user` aplicaram no PostgreSQL sem edição.

**Reconfirmação da camada de acesso sobre o novo banco:** `GET /api/v1/categories/` sem
token → **401**; login `admin` → **200** com `role=admin`; mesma rota com `Bearer` →
**200**.