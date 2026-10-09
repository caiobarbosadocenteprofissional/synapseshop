# SynapseShop â€” Backend de Pedidos com InteligÃªncia Artificial

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![IA](https://img.shields.io/badge/IA-LLM%20%7C%20RAG%20%7C%20NL%20to%20SQL-8A2BE2)

> Projeto desenvolvido no contexto da **SynapseTech** â€” empresa simulada do curso de
> **ProgramaÃ§Ã£o Python AvanÃ§ada com IA** (100 horas Â· 25 aulas).

---

## 1. Sobre o Projeto

O **SynapseShop** Ã© o backend de uma loja online voltado Ã  gestÃ£o de produtos, pedidos,
pagamentos simulados e notificaÃ§Ãµes. Sobre essa base transacional robusta, opera uma camada
inteligente responsÃ¡vel por trÃªs pilares de IA:

1. **Assistente de Suporte (`/assist`)** â€” responde dÃºvidas de clientes sobre pedidos e status
   usando um serviÃ§o de IA resiliente (com *retry* e *circuit breaker*).
2. **Consulta em Linguagem Natural (`/ask_sql`)** â€” converte perguntas em texto corrido
   (ex.: *"quais os produtos mais vendidos este mÃªs?"*) em consultas SQL dinÃ¢micas.
3. **Assistente de DocumentaÃ§Ã£o via RAG (`/ask_docs`)** â€” responde com base no prÃ³prio `README`
   e na documentaÃ§Ã£o tÃ©cnica da API, com citaÃ§Ã£o rigorosa das fontes.

O desenvolvimento segue a metodologia **SpecDD (Specification-Driven Development)**, de forma
incremental, a partir das especificaÃ§Ãµes registradas em [`specs/`](specs/).

---

## 2. Equipe

| Papel | AtribuiÃ§Ãµes |
| :--- | :--- |
| **Tech Lead & Product Owner** | Conduz a formaÃ§Ã£o do time, define o domÃ­nio do projeto e garante o entendimento unificado da arquitetura-alvo. |
| **DevOps / SRE** | Cria e configura o repositÃ³rio no GitHub, garantindo acesso e permissÃ£o de contribuiÃ§Ã£o a todos os membros. |
| **Arquiteto(a)** | Planeja a arquitetura em camadas e a estrutura inicial da documentaÃ§Ã£o. |
| **Desenvolvedor(a)** | Implementa o cÃ³digo do MVP em camadas lÃ³gicas (API, ServiÃ§os e RepositÃ³rios). |
| **Especialista em IA** | Desenha e integra os serviÃ§os de IA (assistente, texto-para-SQL e RAG). |

### Integrantes

1. Alan Correa
2. Amanda Gomes
3. Alvaro Luiz
4. Gustavo Lima
5. Ricardo Reis
6. Hiram Simoes
7. Caio Barbosa

---

## 3. DomÃ­nio da Loja

**EletrÃ´nicos** â€” e-commerce de produtos eletrÃ´nicos (categorias, catÃ¡logo e gestÃ£o de pedidos),
mantendo aderÃªncia total aos requisitos tÃ©cnicos obrigatÃ³rios do MVP.

---

## 4. MVP â€” DescriÃ§Ã£o

Backend containerizado de uma loja de **eletrÃ´nicos** com gestÃ£o de produtos, pedidos, pagamentos
simulados e notificaÃ§Ãµes, exposto por APIs (Django REST Framework + FastAPI) com autenticaÃ§Ã£o JWT
baseada em papÃ©is. O MVP integra, na camada de IA, pelo menos uma das funcionalidades inteligentes
(assistente de suporte, texto-para-SQL ou RAG) e opera com mensageria assÃ­ncrona, cache e testes
automatizados.

**CritÃ©rios de conclusÃ£o (DoD global):**
- Subir o ambiente completo com um Ãºnico comando: `docker-compose up`.
- AutenticaÃ§Ã£o JWT com pelo menos dois papÃ©is de usuÃ¡rio.
- Fluxo ponta a ponta `Pedido âž” Pagamento âž” NotificaÃ§Ã£o` com mensageria, idempotÃªncia e DLQ.
- Testes automatizados dentro da meta da turma e documentaÃ§Ã£o OpenAPI/Swagger.
- Pelo menos uma funcionalidade de IA operacional.
- Pipeline de CI/CD (GitHub Actions) e dashboard analÃ­tico (Streamlit).
- DocumentaÃ§Ã£o completa em Markdown, incluindo o histÃ³rico de prompts em [`PROMPTS.md`](PROMPTS.md).

---

## 5. Arquitetura-Alvo em 6 Camadas

O sistema Ã© projetado em **6 camadas lÃ³gicas**, conteinerizadas via Docker e orquestradas com
Docker Compose:

```mermaid
flowchart TB
    subgraph C1["1. Clientes & Canais de Acesso"]
        A1["Loja Web / Mobile"]
        A2["Painel do Administrador"]
        A3["Canal de Suporte com IA"]
    end

    subgraph C2["2. Gateway de API & AutenticaÃ§Ã£o"]
        B1["Django REST Framework"]
        B2["FastAPI (microsserviÃ§os)"]
        B3["JWT Â· Roles Â· Throttling"]
    end

    subgraph C3["3. ServiÃ§os de NegÃ³cio"]
        D1["Order Service"]
        D2["Payment Service"]
        D3["Inventory Service"]
        D4["Notification Service"]
    end

    subgraph C4["4. Camada de InteligÃªncia Artificial"]
        E1["Assistent / LLM"]
        E2["NL-to-SQL"]
        E3["RAG (docs)"]
    end

    subgraph C5["5. Dados & Mensageria"]
        F1["PostgreSQL"]
        F2["Redis"]
        F3["Kafka (padrÃ£o) / RabbitMQ"]
    end

    subgraph C6["6. Observabilidade, Qualidade & Entrega"]
        G1["Streamlit (Dashboards)"]
        G2["pytest (Testes)"]
        G3["OpenAPI / Swagger"]
        G4["CI/CD â€” GitHub Actions"]
    end

    C1 --> C2 --> C3 --> C4
    C3 --> C5
    C4 --> C5
    C5 --> C6
```

### DescriÃ§Ã£o textual das camadas

1. **Clientes & Canais de Acesso** â€” Loja Web/Mobile, Painel do Administrador e Canal de Suporte com IA.
2. **Gateway de API & AutenticaÃ§Ã£o** â€” DRF para a API principal, FastAPI para microsserviÃ§os; JWT com papÃ©is (roles) e *throttling*.
3. **ServiÃ§os de NegÃ³cio** â€” *Order Service* (criaÃ§Ã£o e eventos), *Payment Service* (pagamento simulado), *Inventory Service* (estoque/produtos) e *Notification Service* (consumidor de eventos).
4. **Camada de IA** â€” Assistente de suporte, consultas NL-to-SQL e RAG, integrados a provedores de LLM externos (OpenAI/DeepSeek).
5. **Dados & Mensageria** â€” PostgreSQL (relacional + migraÃ§Ãµes Alembic), Redis (cache-aside), Kafka (eventos, idempotÃªncia e DLQ) com RabbitMQ como broker alternativo.
6. **Observabilidade, Qualidade & Entrega** â€” Dashboards Streamlit, testes `pytest`, OpenAPI/Swagger e CI/CD com GitHub Actions.

---

## 6. DefiniÃ§Ã£o de Pronto â€” Aula 1 (Kick-off)

- [x] RepositÃ³rio Ãºnico do projeto criado no GitHub.
- [x] Todos os membros do time com permissÃ£o de escrita/push (colaboradores definidos na spec).
- [x] `README.md` na raiz com equipe, papÃ©is, domÃ­nio e arquitetura-alvo em 6 camadas.
- [x] `PROMPTS.md` criado na raiz para registro do histÃ³rico de uso de IA generativa.

---

## 7. Infraestrutura (Aula 3) â€” Docker Compose

O ambiente Ã© orquestrado com Docker Compose e sobe com **um Ãºnico comando**:

```bash
docker-compose up
```

### ServiÃ§os

| ServiÃ§o | Imagem | Porta | Objetivo |
| :--- | :--- | :--- | :--- |
| `api` | `synapseshop:dev` (build local) | `8000` | Executa a aplicaÃ§Ã£o e expÃµe a rota de monitoramento `/health`. |
| `inventory` | `synapseshop-inventory:dev` (build local) | `8100` | MicrosserviÃ§o de estoque em FastAPI (Aulas 5â€“6), com `/docs` e persistÃªncia em PostgreSQL via Alembic. |
| `pedido-worker` | `synapseshop:dev` (build local) | â€” | Consumidor da Camada 5 (Aulas 9â€“10). EscalÃ¡vel com `--scale`. |
| `postgres` | `postgres:16-alpine` | `5432` | Banco de dados relacional do MVP (dados persistidos). |
| `redis` | `redis:7-alpine` | `6379` | Cache-aside do catÃ¡logo, deduplicaÃ§Ã£o e contadores de mÃ©tricas, com polÃ­tica `allkeys-lru` e volume `redisdata`. |
| `kafka` | `apache/kafka:3.9.1` | `9092` / `29092` | Broker de eventos (KRaft single-node, Aula 10). `9092` para o host, `29092` para a rede Compose. |
| `rabbitmq` | `rabbitmq:3-management` | `5672` / `15672` | Broker alternativo (Aula 9), com UI de gerenciamento. |

O serviÃ§o `api` recebe via variÃ¡veis de ambiente as credenciais do banco
(`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`)
e conecta no serviÃ§o `postgres` pelo hostname interno `postgres`, aguardando o
`service_healthy` antes de subir. Dados do banco sÃ£o persistidos no volume `pgdata`.

Desde a **Aula 8** a API tambÃ©m depende do serviÃ§o `redis` (`REDIS_URL`,
`CACHE_ENABLED`, `CACHE_TTL_LISTA`, `CACHE_TTL_DETALHE`), aguardando o
`service_healthy` do Redis. Se o Redis ficar indisponÃ­vel, a API continua
respondendo a partir do PostgreSQL (`IGNORE_EXCEPTIONS=True`) e o header
`X-Cache` passa a reportar `BYPASS`.

Desde a **Aula 9** a API e o `pedido-worker` publicam e consomem eventos. Desde a
**Aula 10** o broker padrÃ£o Ã© o serviÃ§o `kafka` (KRaft, sem ZooKeeper), com
`service_healthy` antes de qualquer consumidor subir. Os dois brokers ficam de pÃ©
no Compose; qual estÃ¡ ativo Ã© a variÃ¡vel `MENSAGERIA_BROKER`.

### Procedimentos

- **Subir o ambiente:** `docker-compose up` (ou `docker-compose up --build -d` em modo *detached*)
- **Derrubar o ambiente:** `docker-compose down` (adicione `-v` para apagar tambÃ©m o volume `pgdata`)
- **Acompanhar os logs:** `docker-compose logs -f`
- **Logs de um serviÃ§o especÃ­fico:** `docker-compose logs -f api` ou `docker-compose logs -f postgres`
- **Verificar a saÃºde da API:** `curl http://localhost:8000/health` â†’ `{"status": "ok"}`
- **Status dos serviÃ§os:** `docker-compose ps`

A imagem utiliza **multistage build** (`builder` gera as dependÃªncias; `runtime` mantÃ©m a
imagem final enxuta), executa com **usuÃ¡rio nÃ£o-root** e gerencia o **cache de dependÃªncias**
copiando o `requirements.txt` antes do cÃ³digo. No start, o contÃªiner aplica as migraÃ§Ãµes
(`python manage.py migrate`), cria os usuÃ¡rios demo para autenticaÃ§Ã£o
(`python manage.py seed_demo_users`, Aula 7) e sobe o servidor de desenvolvimento do Django
na porta `8000`.

---

## 8. API Principal (Aula 4) â€” Django REST Framework

A API principal Ã© construÃ­da com **Django 5.2 LTS** + **Django REST Framework 3.18**, com
operaÃ§Ãµes CRUD completas sob rotas versionadas em `/api/v1/`. Desde a **Aula 7** o banco Ã© o
**PostgreSQL** do Compose (driver `psycopg` 3), o mesmo do microsserviÃ§o `inventory` e com
persistÃªncia no volume `pgdata`. Nas Aulas 4â€“6 a API operava sobre SQLite, escopo agora
superado.

> **A partir da Aula 7,** todos os endpoints de `/api/v1/` exigem autenticaÃ§Ã£o JWT
> (leitura) e os endpoints de escrita exigem o papel `admin` â€” ver a
> [SeÃ§Ã£o 9](#9-autenticaÃ§Ã£o-jwt-papÃ©is-e-throttling-aula-7).

### Estrutura

| Caminho | Camada | Responsabilidade |
| :--- | :--- | :--- |
| `config/` | Projeto | `settings.py`, `urls.py`, `wsgi.py`/`asgi.py`. |
| `repositories/` | Dados | App Django com os models `User` (papÃ©is Aula 7), `Category` e `Item`. |
| `api/` | API | Serializers, ViewSets, roteador e a view `/health`. |
| `services/` | NegÃ³cio | Reservado para regras de domÃ­nio (aulas futuras). |

### Endpoints

| MÃ©todo | Rota | AÃ§Ã£o | Status |
| :--- | :--- | :--- | :--- |
| GET | `/api/v1/categories/` | Lista categorias | 200 / 401 |
| POST | `/api/v1/categories/` | Cria categoria (admin) | 201 / 400 / 401 / 403 |
| GET | `/api/v1/categories/{id}/` | Detalha categoria | 200 / 404 / 401 |
| PUT/PATCH | `/api/v1/categories/{id}/` | Atualiza categoria (admin) | 200 / 400 / 401 / 403 / 404 |
| DELETE | `/api/v1/categories/{id}/` | Remove categoria (admin) | 204 / 401 / 403 / 404 |
| GET | `/api/v1/items/` | Lista itens | 200 / 401 |
| POST | `/api/v1/items/` | Cria item (admin) | 201 / 400 / 401 / 403 |
| GET | `/api/v1/items/{id}/` | Detalha item | 200 / 404 / 401 |
| PUT/PATCH | `/api/v1/items/{id}/` | Atualiza item (admin) | 200 / 400 / 401 / 403 / 404 |
| DELETE | `/api/v1/items/{id}/` | Remove item (admin) | 204 / 401 / 403 / 404 |
| GET | `/health` | Monitoramento | 200 |

O `Item` possui `name`, `description`, `price` (`Decimal`), `category` (FK) e `is_active`;
o `Category` possui `name` (Ãºnico), `description` e `created_at`.

### MigraÃ§Ãµes e execuÃ§Ã£o

```bash
docker-compose up --build          # aplica as migraÃ§Ãµes e sobe a API
docker-compose exec api python manage.py makemigrations   # novas migraÃ§Ãµes
docker-compose exec api python manage.py migrate          # aplicar manualmente
```

### Exemplos rÃ¡pidos

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/v1/categories/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Eletronicos", "description": "Produtos eletronicos"}'

curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Notebook", "price": "4999.90", "category": 1}'
```

A coleÃ§Ã£o de rotas estÃ¡ exportada em
[`docs/postman/SynapseShop_Aula4.postman_collection.json`](docs/postman/SynapseShop_Aula4.postman_collection.json)
para importaÃ§Ã£o no Postman, e o guia de revisÃ£o de cÃ³digo gerado por IA estÃ¡ em
[`docs/CHECKLIST_IA_SAFE.md`](docs/CHECKLIST_IA_SAFE.md).

---

## 9. AutenticaÃ§Ã£o JWT, PapÃ©is e Throttling (Aula 7)

A camada de acesso seguro da API principal usa **JWT stateless** (Bearer) com **dois
papÃ©is** (`admin` e `user`), **throttling** contra forÃ§a bruta e **paginaÃ§Ã£o/filtros**
nos endpoints crÃ­ticos. Tudo configurÃ¡vel via variÃ¡veis de ambiente
(`JWT_*`, `THROTTLE_*`, `SEED_*` â€” ver [SeÃ§Ã£o 14](#14-variÃ¡veis-de-ambiente)).

### UsuÃ¡rios e papÃ©is

O modelo de usuÃ¡rio Ã© customizado (`repositories.User`, sobre `AbstractUser`) e persistido
em **PostgreSQL**, na tabela `repositories_user` do mesmo banco do `inventory`. O
comando `python manage.py seed_demo_users` â€” executado no start do container â€” cria,
de forma idempotente, dois usuÃ¡rios demo a partir das envs `SEED_*`:

| UsuÃ¡rio | Papel | Credenciais default |
| :--- | :--- | :--- |
| `admin` | `admin` (acesso total) | `admin` / `admin` |
| `user` | `user` (somente leitura) | `user` / `user` |

### Fluxos de autenticaÃ§Ã£o

| MÃ©todo | Rota | AÃ§Ã£o | Status |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/auth/token/` | Login â†’ `{access, refresh, role}` | 200 / 401 / 429 |
| POST | `/api/v1/auth/token/refresh/` | Renova o access token | 200 / 401 / 429 |

O token (access e refresh) carrega a claim `role`, permitindo ao cliente controlar a
interface sem chamadas extras. Defaults: access 60 min, refresh 7 dias.

### ProteÃ§Ã£o das rotas administrativas

- **Leitura** (`GET` list/detail) de `/api/v1/categories/` e `/api/v1/items/`: exige
  **autenticaÃ§Ã£o** (qualquer papel) â†’ sem token retorna **401**.
- **Escrita** (`POST`/`PUT`/`PATCH`/`DELETE`): exige o papel **`admin`** â†’ usuÃ¡rio comum
  autenticado retorna **403**.
- `/health` permanece **pÃºblico** (monitoramento).

### Throttling e seguranÃ§a mÃ­nima

| Escopo | Onde se aplica | Default |
| :--- | :--- | :--- |
| `anon` | endpoints DRF sem autenticaÃ§Ã£o | `20/min` |
| `user` | endpoints DRF autenticados | `200/min` |
| `login` | `POST /api/v1/auth/token/*` (anti forÃ§a bruta) | `5/min` |

Exaurida a taxa de `login`, o servidor responde **429 Too Many Requests** antes mesmo de
validar credenciais.

### PaginaÃ§Ã£o e filtros nos endpoints crÃ­ticos

- PaginaÃ§Ã£o por **pÃ¡gina numerada**: `{count, next, previous, results}` com
  `page_size` default de **10** e ajuste via `?page_size=`.
- **Busca** (`?search=`), **ordenaÃ§Ã£o** (`?ordering=`) e filtros por **query param**:
  `is_active`, `category` em `/api/v1/items/`.

### Exemplos rÃ¡pidos

```bash
# Login admin (guarde o access token)
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'

# Rotas protegidas: leitura exige Bearer
curl http://localhost:8000/api/v1/categories/ \
  -H "Authorization: Bearer <access_token>"

# Escrita exige papel admin; usuÃ¡rio comum recebe 403
curl -X POST http://localhost:8000/api/v1/categories/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Eletronicos", "description": "Produtos eletronicos"}'

# PaginaÃ§Ã£o e filtros nos itens
curl "http://localhost:8000/api/v1/items/?search=Notebook&is_active=true&page_size=5" \
  -H "Authorization: Bearer <access_token>"
```

EvidÃªncias e decisÃµes em
[`docs/DECISOES_TECNICAS_AULA7.md`](docs/DECISOES_TECNICAS_AULA7.md) e
[`docs/METRICAS_AULA7.md`](docs/METRICAS_AULA7.md), com a coleÃ§Ã£o Postman em
[`docs/postman/SynapseShop_Aula7.postman_collection.json`](docs/postman/SynapseShop_Aula7.postman_collection.json).

---

## 10. MicrosserviÃ§o de InventÃ¡rio â€” FastAPI (Aulas 5 e 6)

MicrosserviÃ§o complementar de estoque (`inventory`) construÃ­do com **FastAPI**,
conteinerizado separadamente e orquestrado pelo mesmo `docker-compose`. Desde a
**Aula 6** o estado Ã© persistido no **PostgreSQL** com mapeamento via
**SQLAlchemy 2.0** e **migraÃ§Ãµes versionadas com Alembic** (a autenticaÃ§Ã£o JWT
fica na Aula 7 â€” escopo SpecDD preservado).

### Estrutura

| Caminho | Responsabilidade |
| :--- | :--- |
| `inventory/app/main.py` | AplicaÃ§Ã£o FastAPI, `/health` e raiz com informaÃ§Ãµes do serviÃ§o. |
| `inventory/app/schemas.py` | Modelos Pydantic (contratos de entrada, saÃ­da e validaÃ§Ãµes). |
| `inventory/app/db.py` | SQLAlchemy: `engine`, `Base`, `SessionLocal` e dependency `get_session()`. |
| `inventory/app/models.py` | Modelo ORM `InventoryItem` (Ã­ndices essenciais e integridade). |
| `inventory/app/repository.py` | `InventoryRepository` â€” persistÃªncia transacional (commit/rollback). |
| `inventory/app/services.py` | `InventoryService` â€” regras de domÃ­nio sobre o repositÃ³rio. |
| `inventory/app/routes.py` | Rotas do inventÃ¡rio sob `/inventory/items`. |
| `inventory/migrations/` | MigraÃ§Ãµes Alembic (`versions/0001_create_inventory_items.py`). |
| `inventory/scripts/` | Smoke test e teste transacional com coleta de tempos. |
| `inventory/Dockerfile` | Imagem com multistage build e usuÃ¡rio nÃ£o-root (porta `8100`). |

### Endpoints

| MÃ©todo | Rota | AÃ§Ã£o | Status |
| :--- | :--- | :--- | :--- |
| GET | `/health` | Monitoramento | 200 |
| GET | `/inventory/items` | Lista itens de estoque | 200 |
| POST | `/inventory/items` | Cria item de estoque | 201 / 400 / 409 |
| GET | `/inventory/items/{id}/` | Detalha item | 200 / 404 |
| PATCH | `/inventory/items/{id}/` | Atualiza item | 200 / 404 / 409 |
| PATCH | `/inventory/items/{id}/stock` | Ajusta estoque (transaÃ§Ã£o) | 200 / 404 / 409 |
| DELETE | `/inventory/items/{id}/` | Remove item | 204 / 404 |

A **documentaÃ§Ã£o automÃ¡tica (OpenAPI/Swagger)** estÃ¡ disponÃ­vel em
`http://localhost:8100/docs`.

### MigraÃ§Ãµes de schema (Alembic + PostgreSQL)

Aplicadas automaticamente no start do contÃªiner (`alembic upgrade head`).
Manualmente, dentro do contÃªiner:

```bash
docker compose exec inventory alembic current          # revisÃ£o corrente
docker compose exec inventory alembic history          # histÃ³rico de revisÃµes
docker compose exec inventory alembic upgrade head     # aplica pendentes
docker compose exec inventory alembic downgrade -1     # rollback de 1 revisÃ£o
```

O modelo relacional (`inventory_items`) contempla Ã­ndices essenciais
(`sku` Ãºnico e `name`) e integridade relacional (`NOT NULL`, `sku` Ãºnico e
`CheckConstraint quantity >= 0`). Detalhes em
[`docs/DECISOES_TECNICAS_AULA6.md`](docs/DECISOES_TECNICAS_AULA6.md) e mÃ©tricas
em [`docs/METRICAS_AULA6.md`](docs/METRICAS_AULA6.md).

### Exemplos rÃ¡pidos

```bash
curl http://localhost:8100/health
curl http://localhost:8100/docs

curl -X POST http://localhost:8100/inventory/items \
  -H "Content-Type: application/json" \
  -d '{"sku": "NB-001", "name": "Notebook 16GB", "quantity": 10}'

curl http://localhost:8100/inventory/items
curl http://localhost:8100/inventory/items/1

# Ajuste transacional de estoque
curl -X PATCH http://localhost:8100/inventory/items/1/stock \
  -H "Content-Type: application/json" \
  -d '{"delta": -2}'
```

O padrÃ£o de prompts de IA da squad estÃ¡ definido em
[`PROMPTS-TEMPLATE.md`](PROMPTS-TEMPLATE.md), com registro no
[`PROMPTS.md`](PROMPTS.md).

---

## 11. Cache-aside com Redis (Aula 8)

O catÃ¡logo passou a ser servido por **cache-aside com Redis** (`django-redis`),
com TTL, invalidaÃ§Ã£o por eventos de domÃ­nio, header `X-Cache` e mÃ©tricas de hit
rate. O microsserviÃ§o `inventory` permanece intocado.

### Estrutura

| Caminho | Responsabilidade |
| :--- | :--- |
| `services/cache.py` | Cache-aside, assinatura de chaves, TTL, Ã­ndices de invalidaÃ§Ã£o, mÃ©tricas e logs. |
| `services/events.py` | Dispatcher in-process de eventos de domÃ­nio (`emitir`/`registrar`). |
| `services/cache_invalidation.py` | LigaÃ§Ã£o evento do domÃ­nio â†’ chaves de cache a invalidar. |
| `api/views.py` | Cache nos endpoints de itens e `CacheStatsView`. |
| `api/apps.py` | `ready()` registra os handlers de invalidaÃ§Ã£o. |
| `repositories/management/commands/seed_demo_catalog.py` | CatÃ¡logo de 5 categorias e 300 itens para mediÃ§Ã£o. |
| `scripts/bench_cache.py` | Benchmark de latÃªncia (mÃ©dia, p50, p95) e RPS. |
| `scripts/smoke_test_cache.py` | VerificaÃ§Ã£o de miss/hit, TTL, invalidaÃ§Ã£o e mÃ©tricas. |

### Chaves e TTL

| Chave Redis (apÃ³s `KEY_PREFIX`) | ConteÃºdo | TTL |
| :--- | :--- | ---: |
| `synapseshop:1:itens:list:<assinatura>` | pÃ¡gina da listagem jÃ¡ paginada | 60 s |
| `synapseshop:1:item:<id>` | item Ãºnico jÃ¡ serializado | 300 s |
| `itens:list:indice` / `itens:detalhe:indice` | *sets* de chaves ativas, para invalidaÃ§Ã£o | â€” |

A listagem Ã© cacheada por **assinatura**: SHA-1 de 12 caracteres dos query params
relevantes (`search`, `ordering`, `category`, `is_active`, `min_price`,
`max_price`, `page`, `page_size`) ordenados e normalizados, para que filtros
diferentes nunca compartilhem a mesma chave.

### EstratÃ©gia de invalidaÃ§Ã£o

A invalidaÃ§Ã£o Ã© orientada a **eventos de domÃ­nio**, nÃ£o a tempo. Cada escrita
emite um evento **apÃ³s o commit** no PostgreSQL (`transaction.on_commit`), e o
handler apaga as chaves afetadas:

| Evento | Invalida |
| :--- | :--- |
| `ItemCriado` / `ItemAtualizado` / `ItemRemovido` | `item:<id>` e todas as `itens:list:*` |
| `CategoryCriada` / `CategoryAtualizada` / `CategoryRemovida` | `item:<id>` e todas as `itens:list:*` |

Pontos-chave da estratÃ©gia:

- **`on_commit`:** sem ele, um rollback invalidaria o cache com o dado ainda no
  banco, produzindo uma leitura inconsistente.
- **Ãndice em *set*:** as chaves de listagem sÃ£o registradas em
  `itens:list:indice`, entÃ£o a invalidaÃ§Ã£o faz 1 `SMEMBERS` + `DEL` do conjunto,
  sem `SCAN` nem `KEYS` sobre o keyspace.
- **Falha isolada:** handler com `try/except` â€” evento de domÃ­nio nunca derruba
  a requisiÃ§Ã£o de escrita. Se o handler falhar, o log registra `handler_falhou`
  e o TTL assume como rede de seguranÃ§a.
- **Sem broker:** dispatcher in-process, conforme a restriÃ§Ã£o SpecDD (Kafka e
  RabbitMQ sÃ£o das aulas 9-11). `emitir()` Ã© o ponto de extensÃ£o futuro.

### Endpoints de mÃ©tricas

| MÃ©todo | Rota | AÃ§Ã£o | Acesso |
| :--- | :--- | :--- | :--- |
| GET | `/api/v1/cache/stats/` | Hit rate por endpoint e global | admin |
| POST | `/api/v1/cache/stats/` | Zera os contadores | admin |

```json
{
  "cache_habilitado": true,
  "endpoints": {
    "itens:list":  {"hits": 40, "misses": 1, "total_lookups": 41, "hit_rate": 0.9756, "ttl_segundos": 60},
    "item:detalhe": {"hits": 25, "misses": 1, "total_lookups": 26, "hit_rate": 0.9615, "ttl_segundos": 300}
  },
  "total_hits": 65, "total_misses": 2, "total_lookups": 67, "hit_rate": 0.9701
}
```

### Observabilidade

Header `X-Cache` em toda resposta de item: `HIT`, `MISS` ou `BYPASS` (cache
desativado). Logs estruturados JSON:

```json
{"evento": "cache.lookup", "endpoint": "itens:list", "chave": "itens:list:c846376af757", "resultado": "MISS", "ttl": 60, "origem": "postgresql"}
{"evento": "dominio.emitido", "nome": "ItemAtualizado", "payload": {"item_id": 110}}
```

### Desempenho medido

CatÃ¡logo de 300 itens, par A/B na **mesma imagem** alternando apenas
`CACHE_ENABLED`, 150 requisiÃ§Ãµes com concorrÃªncia 1:

| Endpoint | MÃ©dia sem cache | MÃ©dia com cache | VariaÃ§Ã£o | RPS sem | RPS com | VariaÃ§Ã£o |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Listagem `?page_size=10` | 22,01 ms | **15,48 ms** | **âˆ’29,7 %** | 45,32 | **64,42** | **+42,1 %** |
| Detalhe `/api/v1/items/310/` | 24,08 ms | **17,07 ms** | **âˆ’29,1 %** | 41,44 | **58,43** | **+41,0 %** |

Ciclo de vida observado em tempo real: `MISS` â†’ `HIT` â†’ (60 s) `MISS` por
expiraÃ§Ã£o de TTL, e `HIT` â†’ `MISS` logo apÃ³s um `PATCH`, por evento de domÃ­nio.
A decomposiÃ§Ã£o do custo por requisiÃ§Ã£o e as ressalvas de variÃ¢ncia estÃ£o em
[`docs/METRICAS_AULA8.md`](docs/METRICAS_AULA8.md); as decisÃµes e alternativas
consideradas em [`docs/DECISOES_TECNICAS_AULA8.md`](docs/DECISOES_TECNICAS_AULA8.md).

### Exemplos rÃ¡pidos

```bash
# Popula o catÃ¡logo de mediÃ§Ã£o (idempotente)
docker compose exec -T api python manage.py seed_demo_catalog

# Ciclo miss -> hit na listagem (X-Cache na resposta)
curl -i "http://localhost:8000/api/v1/items/?page_size=10" -H "Authorization: Bearer <access_token>"
curl -i "http://localhost:8000/api/v1/items/?page_size=10" -H "Authorization: Bearer <access_token>"

# InvalidaÃ§Ã£o: o PATCH invalida item:<id> e todas as listas
curl -X PATCH "http://localhost:8000/api/v1/items/110/" \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"name":"Item alterado"}'
curl -i "http://localhost:8000/api/v1/items/110/" -H "Authorization: Bearer <access_token>"

# MÃ©tricas de hit rate (admin)
curl -X POST "http://localhost:8000/api/v1/cache/stats/" -H "Authorization: Bearer <access_token>"
curl "http://localhost:8000/api/v1/cache/stats/" -H "Authorization: Bearer <access_token>"

# Chaves e TTL no Redis
docker compose exec -T redis redis-cli -n 1 --scan --pattern 'synapseshop:1:*'
docker compose exec -T redis redis-cli -n 1 SMEMBERS "itens:list:indice"
docker compose exec -T redis redis-cli -n 1 TTL "synapseshop:1:item:110"

# Benchmark (antes/despues, o --path vai no caminho da listagem ou do detalhe)
python scripts/bench_cache.py --path "/api/v1/items/?page_size=10" --requests 150 --concurrency 1

# Kill-switch: desliga o cache sem mexer no cÃ³digo (X-Cache passa a BYPASS)
# CACHE_ENABLED=false docker compose up -d --force-recreate api

# VerificaÃ§Ã£o funcional
python scripts/smoke_test_cache.py
```

### OperaÃ§Ã£o

| Comandos | Efeito |
| :--- | :--- |
| `docker compose exec -T redis redis-cli -n 1 FLUSHALL` | Limpa cache e contadores |
| `docker compose exec -T redis redis-cli -n 1 INFO memory` | MemÃ³ria usada pelo Redis |
| `docker compose logs -f api` | Logs estruturados `cache.lookup` e `dominio.emitido` |

Quando `CACHE_ENABLED=false`, o backend passa a `LocMemCache` e o header
`X-Cache` responde `BYPASS` â€” a API segue funcionando, sem cache.

> **Nota:** com o cache no Redis, os contadores do throttling do DRF (Aula 7)
> passaram a viver no Redis. Ganho de consistÃªncia entre workers, com a
> consequÃªncia de que o estado sobrevive a reinÃ­cios atÃ© expirar a janela.

---

## 12. Mensageria AssÃ­ncrona â€” Kafka (Camada 5)

O fluxo de pedidos Ã© assÃ­ncrono: a API grava o pedido e publica o evento
`PedidoCriado` num broker; um *worker* dedicado consome a fila, processa a
mensagem e persiste o estado no repositÃ³rio. Reentregas sÃ£o tratadas por
**idempotÃªncia**, recuo exponencial e, em Ãºltimo caso, **Dead Letter Queue**.

O broker padrÃ£o Ã© o **Kafka** (Aula 10). O **RabbitMQ** da Aula 9 continua
funcionando atrÃ¡s da mesma fachada â€” a escolha de broker Ã© uma variÃ¡vel de
ambiente, e ambos passam no mesmo smoke test.

### Kafka ou RabbitMQ

| CritÃ©rio | Kafka (padrÃ£o) | RabbitMQ (alternativo) |
| :--- | :--- | :--- |
| Paralelismo de consumo | por partiÃ§Ã£o do tÃ³pico | por consumidor da fila |
| RetenÃ§Ã£o | nativa, por tÃ³pico | limitada a filas durÃ¡veis |
| Reentrega com contagem | header `x-retry-count` na republicaÃ§Ã£o | *nack requeue* / DLX nativa |
| Rota de falha | tÃ³pico DLQ explÃ­cito | *dead-letter exchange* da fila |
| Ordem | por partiÃ§Ã£o (chave = `idempotency_key`) | por fila (*round-robin*) |

O contrato em `events/contracts.py` traz `event_type` e `version`, entÃ£o a troca
de broker nÃ£o quebra o formato da mensagem. A decisÃ£o e o porquÃª de cada escolha
estÃ£o em [`docs/DECISOES_TECNICAS_AULA10.md`](docs/DECISOES_TECNICAS_AULA10.md).

### Topologia do Kafka

```
   POST /api/v1/pedidos/ â”€â”€â–¶-key: idempotency_keyâ”€â–¶â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                                   â”‚  pedidos.pedidocriado â”‚
                                                   â”‚  3 partiÃ§Ãµes          â”‚
                                                   â”‚  retenÃ§Ã£o 7 dias      â”‚
                                                   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                                               â”‚ consumer group
                                                               â”‚ pedido-worker
                                                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                                    â”‚  pedido-worker       â”‚  PENDENTE â†’ PROCESSANDO
                                                    â”‚  commit manual       â”‚  (sÃ­ncrono, apÃ³s o efeito)
                                                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                          falhas esgotadas   â”‚
                                                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                                    â”‚ pedidos.pedidocriado â”‚  â† inspeÃ§Ã£o
                                                    â”‚        .dlq          â”‚    manual
                                                    â”‚  1 partiÃ§Ã£o          â”‚
                                                    â”‚  retenÃ§Ã£o 28 dias    â”‚
                                                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

| Elemento | ConfiguraÃ§Ã£o | ObservaÃ§Ã£o |
| :--- | :--- | :--- |
| `pedidos.pedidocriado` | 3 partiÃ§Ãµes, retenÃ§Ã£o `604800000` ms | Eventos de `PedidoCriado`. |
| `pedidos.pedidocriado.dlq` | 1 partiÃ§Ã£o, retenÃ§Ã£o `2419200000` ms | Mensagens mortas, para inspeÃ§Ã£o. |
| `pedido-worker` | consumer group | Um consumidor por partiÃ§Ã£o. |
| Chave de partiÃ§Ã£o | `idempotency_key` | Eventos do mesmo pedido ficam na mesma partiÃ§Ã£o, em ordem. |
| RÃ©plicas | `KAFKA_REPLICAS=1` | Broker Ãºnico no Compose; subir em cluster. |

A topologia Ã© **declarada pela aplicaÃ§Ã£o** (`declarar_topologia()`, via
`AdminClient`), de forma idempotente: producer e consumer chamam a mesma funÃ§Ã£o
na subida, e `TOPIC_ALREADY_EXISTS` Ã© sucesso. Assim nÃ£o existe passo de setup
manual que alguÃ©m esqueÃ§a.

### Listeners

O mesmo broker atende duas redes:

| Listener | EndereÃ§o | Quem usa |
| :--- | :--- | :--- |
| Compose | `kafka:29092` | Containers (`api`, `pedido-worker`). |
| Host | `localhost:9092` | Scripts rodados na mÃ¡quina de desenvolvimento. |

Os dois sÃ£o texto puro, sem TLS â€” adequado Ã  stack local. Para o host, os
scripts precisam de `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`, porque o default
de `config/settings.py` tambÃ©m Ã© `localhost` e o do Compose Ã© `kafka:29092`.


### Contrato da mensagem `PedidoCriado`

Definido e **validado** em `events/contracts.py`. O envelope JSON:

```json
{
  "event_id": "0f3c...uuid",
  "event_type": "PedidoCriado",
  "version": "1.0",
  "occurred_at": "2026-09-30T23:52:29.117970Z",
  "correlation_id": "b7a1...uuid",
  "idempotency_key": "pedido-2026-0001",
  "dados": {
    "pedido_id": 15,
    "usuario_id": 2,
    "total": "399.80",
    "status": "PENDENTE",
    "itens": [
      {"item_id": 622, "quantidade": 2, "preco_unitario": "199.90"}
    ]
  }
}
```

Regras de contrato:

- **Discriminantes** â€” `event_type` e `version` sÃ£o validados na recepÃ§Ã£o; evento
  desconhecido ou de versÃ£o incompatÃ­vel Ã© rejeitado **antes** de qualquer escrita.
- **`idempotency_key`** â€” chave de negÃ³cio do pedido, **obrigatÃ³ria**, atÃ© 64
  caracteres (limite do Ã­ndice Ãºnico). Ã‰ o que garante idempotÃªncia ponta a ponta.
- **MonetÃ¡rio como `str`** â€” `total` e `preco_unitario` viajam como texto; `float`
  no JSON introduz erro de arredondamento.
- **`correlation_id`** â€” identificador que atravessa produtor e consumidor,
  permitindo correlacionar logs e mensagens.
- **PreÃ§o congelado** â€” o cliente informa apenas `item_id` e `quantidade`; preÃ§o
  e total sÃ£o calculados no servidor a partir do catÃ¡logo, para que o evento
  descreva o pedido como foi vendido.

### IdempotÃªncia

Duas camadas, com a mesma chave e o mesmo TTL:

| Camada | Onde | Papel |
| :--- | :--- | :--- |
| `EventoProcessado` (PostgreSQL) | `services/idempotencia.py` | Fonte durÃ¡vel; unicidade `(evento, idempotency_key)` resolve corrida entre consumidores. |
| Redis (`evento:processado:<evento>:<chave>`) | mesmo mÃ³dulo | Caminho rÃ¡pido, com TTL nativo. |

Pontos-chave da regra:

- **No produtor** â€” repetir a mesma `idempotency_key` devolve o **mesmo pedido**
  com **200**, sem criar outro e sem publicar outro evento.
- **No consumidor** â€” a chave Ã© registrada **depois** do processamento
  bem-sucedido, nunca antes: reservar a chave antes descartaria uma reentrega cujo
  processamento falhou, entregando o pedido com efeito zero.
- **TTL** â€” `IDEMPOTENCIA_TTL_SEGUNDOS` (padrÃ£o 24 h). As chaves expiradas sÃ£o
  removidas na subida do worker para a tabela nÃ£o crescer sem limite.
- **Efeito idempotente** â€” a transiÃ§Ã£o `PENDENTE` â†’ `PROCESSANDO` sÃ³ ocorre se o
  pedido ainda estiver `PENDENTE`, entÃ£o mesmo uma corrida de reentregas nÃ£o
  duplica o efeito.

### Reentrega, recuo e DLQ

| ParÃ¢metro | Default | Significado |
| :--- | ---: | :--- |
| `MENSAGERIA_MAX_RETRIES` | `3` | Reentregas **alÃ©m** da primeira tentativa (4 tentativas no total). |
| `MENSAGERIA_BACKOFF_BASE_MS` | `250` | Base do recuo exponencial. |
| `MENSAGERIA_BACKOFF_MAX_MS` | `5000` | Teto do recuo. |
| `RABBITMQ_PREFETCH` | `1` | Uma mensagem por vez; nada se perde em requeue (sÃ³ no RabbitMQ). |

A contagem de tentativas atravessa o broker em headers, e nÃ£o em memÃ³ria do
processo â€” Ã© isso que permite a reentrega continuar de onde parou.

1. Sucesso â†’ confirma o offset (`commit` sÃ­ncrono, **depois** do efeito gravado).
2. Falha com `tentativa < MAX_RETRIES` â†’ republica o mesmo corpo em
   `pedidos.pedidocriado` com `x-retry-count` incrementado, aguarda o recuo
   exponencial (`250 ms â†’ 500 ms â†’ 1000 ms â†’ â€¦`, limitado por `BACKOFF_MAX`) e
   entÃ£o confirma a original.
3. `tentativa >= MAX_RETRIES` â†’ publica em `pedidos.pedidocriado.dlq` com o erro
   em `x-ultimo-erro` e confirma a original. NÃ£o hÃ¡ consumo automÃ¡tico da DLQ: a
   decisÃ£o de reprocessar Ã© humana.

No RabbitMQ, os mesmos passos usam `ack` manual, *nack requeue* para a reentrega
e *dead-letter exchange* para a DLQ.

Corpo ilegÃ­vel (JSON invÃ¡lido) nÃ£o tem como ser reprocessado e vai direto para a
DLQ, sem consumir tentativas.

### Estrutura

| Caminho | Responsabilidade |
| :--- | :--- |
| `events/contracts.py` | Contrato `PedidoCriado` (serializaÃ§Ã£o e validaÃ§Ã£o). |
| `services/messaging.py` | Fachada: escolhe o broker a partir de `MENSAGERIA_BROKER`. |
| `services/messaging_kafka.py` | Topologia, produtor, consumidor com offset manual, reentrega e DLQ. |
| `services/messaging_rabbit.py` | Mesmo contrato sobre RabbitMQ (broker alternativo). |
| `services/idempotencia.py` | Chave de deduplicaÃ§Ã£o com TTL (Redis + PostgreSQL). |
| `api/views.py` | `PedidoCreateView` (produtor) e `PedidoDetailView` (observabilidade). |
| `workers/pedido_worker.py` | Consumidor: valida o contrato, deduplica e persiste o estado. |
| `scripts/smoke_test_mensageria.py` | VerificaÃ§Ã£o do fluxo, da idempotÃªncia e da DLQ em ambos os brokers. |
| `scripts/bench_mensageria.py` | LatÃªncia ponta a ponta, percentis e throughput de consumo. |


### Endpoints

| MÃ©todo | Rota | AÃ§Ã£o | Status |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/pedidos/` | Cria pedido e publica `PedidoCriado` | 201 / 200 / 400 / 401 |
| GET | `/api/v1/pedidos/{id}/` | Detalha pedido (dono ou admin) | 200 / 404 |

A criaÃ§Ã£o do pedido exige autenticaÃ§Ã£o (qualquer papel) â€” diferentemente do
catÃ¡logo, em que escrita Ã© `admin`-only, porque o pedido pertence a quem o cria.

`201` traz `evento_publicado: true`. Se o pedido for commitado mas o broker
recusar o evento, a resposta Ã© `202` com `evento_publicado: false`: o dado estÃ¡ no
banco e a falha fica registrada em log, sem mentir sobre o estado.

### Observabilidade

Logs estruturados JSON com `duracao_ms` em cada etapa:

```json
{"evento": "mensageria.publicado", "idempotency_key": "pedido-smoke-1790812348", "duracao_ms": 3.91}
{"evento": "mensageria.consumido", "idempotency_key": "pedido-smoke-1790812348", "resultado": "ok", "duracao_ms": 12.4}
{"evento": "worker.pedido.duplicado", "pedido_id": 15, "resultado": "duplicado", "duracao_ms": 0.35}
{"evento": "mensageria.reentrega", "tentativa": 0, "proxima_tentativa": 1, "espera_ms": 250.0}
{"evento": "mensageria.dlq", "tentativa": 3, "dlq": "pedidos.pedidocriado.dlq"}
```

### Exemplos rÃ¡pidos

```bash
# Token e criaÃ§Ã£o do pedido (o evento Ã© publicado no mesmo passo)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" -d '{"username":"user","password":"user"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

curl -X POST http://localhost:8000/api/v1/pedidos/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"pedido-2026-0001","itens":[{"item_id":1,"quantidade":2}]}'

# O worker leva o pedido de PENDENTE para PROCESSANDO
curl http://localhost:8000/api/v1/pedidos/15/ -H "Authorization: Bearer $TOKEN"

# Repetir a chave devolve o mesmo pedido, com 200
curl -i -X POST http://localhost:8000/api/v1/pedidos/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"pedido-2026-0001","itens":[{"item_id":1,"quantidade":2}]}'

# Logs de produtor e consumidor
docker compose logs -f api pedido-worker

# UI de gerenciamento do RabbitMQ (broker alternativo; guest/guest)
# http://localhost:15672

# Estado dos tÃ³picos do Kafka
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:29092 --list
docker compose exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:29092 --describe --group pedido-worker
```

### OperaÃ§Ã£o

| Comando | Efeito |
| :--- | :--- |
| `PEDIDO_WORKER_FALHA_IDEM_KEYS="pedido-dlq-*" docker compose up -d --force-recreate pedido-worker` | Worker rejeita pedidos cujo padrÃ£o casa â€” simula erro para validar reentrega/DLQ |
| `MENSAGERIA_BROKER=rabbitmq docker compose up -d --force-recreate api pedido-worker` | Alterna para o broker da Aula 9 |
| `MENSAGERIA_BROKER=kafka docker compose up -d --force-recreate api pedido-worker` | Volta ao Kafka |
| `docker compose up -d --scale pedido-worker=3 pedido-worker` | Escala o consumo (1 consumidor por partiÃ§Ã£o) |
| `docker compose exec -T kafka ... --delete --topic pedidos.pedidocriado.dlq` | Remove a DLQ depois da inspeÃ§Ã£o |
| `docker compose exec -T rabbitmq rabbitmqctl purge_queue pedidos.pedidocriado.dlq` | Limpa a DLQ do RabbitMQ |
| `docker compose exec -T rabbitmq rabbitmqctl list_queues name messages` | Estado das filas do RabbitMQ |
| `docker compose logs -f pedido-worker` | Logs do consumidor |
| `MESSAGERIA_ENABLED=false docker compose up -d --force-recreate api` | Kill-switch: grava o pedido sem publicar (202) |

Com `MESSAGERIA_ENABLED=false` a API segue funcionando: o pedido Ã© persistido e
a resposta Ã© `202` com `evento_publicado: false`, o que isola o custo da
sincronia ponta a ponta em mediÃ§Ãµes.

### VerificaÃ§Ã£o funcional

O smoke test Ã© o mesmo nos dois brokers â€” ele detecta o broker ativo por
`MENSAGERIA_BROKER` e adapta as verificaÃ§Ãµes de partiÃ§Ã£o/DLQ.

```bash
# Fluxo feliz + idempotÃªncia (o cenÃ¡rio de DLQ Ã© pulado sem o modo forÃ§ado)
python scripts/smoke_test_mensageria.py

# Com o cenÃ¡rio de DLQ ativo
PEDIDO_WORKER_FALHA_IDEM_KEYS="pedido-dlq-*" docker compose up -d --force-recreate pedido-worker
python scripts/smoke_test_mensageria.py
```

Resultado da validaÃ§Ã£o:

| Broker | Resultado | VerificaÃ§Ãµes extras |
| :--- | :--- | :--- |
| Kafka | **25 PASS / 0 FAIL** | Mesma chave sempre na mesma partiÃ§Ã£o; chaves diferentes se espalham pelas 3 partiÃ§Ãµes |
| RabbitMQ | **23 PASS / 0 FAIL** | â€” |

Ambos cobrem publicaÃ§Ã£o, contrato, consumo com persistÃªncia do estado,
idempotÃªncia no produtor, idempotÃªncia na reentrega (o teste republica o mesmo
evento) e chegada Ã  DLQ com o pedido ainda em `PENDENTE`.

### Desempenho medido

Medido com `scripts/bench_mensageria.py` sobre o caminho real. NÃºmeros,
ambiente e limites desta mediÃ§Ã£o em
[`docs/METRICAS_AULA10.md`](docs/METRICAS_AULA10.md).

| CenÃ¡rio | 1 consumidor | 3 consumidores |
| :--- | :--- | :--- |
| ProduÃ§Ã£o em rajada (200 pedidos) | 11,18 req/s | 11,15 req/s |
| LatÃªncia ponta a ponta p50 / p95 | 64,69 / 67,23 ms | 64,62 / 68,04 ms |
| LatÃªncia ponta a ponta p99 | 68,30 ms | 71,72 ms |
| Backlog de 1000 msgs drenado | 66,31 msg/s | 80,56 msg/s |

O gargalo da produÃ§Ã£o Ã© a API (cada `POST` custa ~89 ms, com publicaÃ§Ã£o
sÃ­ncrona e `acks=all`), nÃ£o o consumidor: um worker jÃ¡ acompanha a taxa de 11
req/s. Escalar o consumo sÃ³ se pagaria com um produtor mais rÃ¡pido que o serial.

```bash
# LatÃªncia ponta a ponta com o worker no ar
python scripts/bench_mensageria.py --modo api --pedidos 200 --rotulo "kafka-1-consumidor"

# Teto de consumo: enche o backlog com o worker parado, depois mede a queda
docker compose stop pedido-worker
python scripts/bench_mensageria.py --modo drenagem --fase preencher --pedidos 1000
python scripts/bench_mensageria.py --modo drenagem --fase medir --espera 300
```

> **Nota:** o harness Ã© tolerante ao throttle da API (200/min): aguarda a janela
> expirar uma vez e segue, em vez de descartar da amostra os pedidos lentos, que
> sÃ£o justamente a cauda dos percentis.


---

## 13. Testes Automatizados (Aula 12)

SuÃ­te `pytest` organizada em `tests/unit` (ramos felizes e de erro, parametrizados)
e `tests/integration` (ciclo de vida completo dos recursos na API), com cobertura
global mÃ­nima de **85%** (.coveragerc). A execuÃ§Ã£o atual mede **99,91%** do cÃ³digo
aplicacional de `services`, `events`, `api`, `config` e `repositories`.

### ExecuÃ§Ã£o

```bash
python -m pytest                       # suÃ­te completa (unit + integration)
python -m pytest tests/unit            # somente unitÃ¡rios
python -m pytest tests/integration     # somente integraÃ§Ã£o
pytest --cov --cov-report=term-missing # relatÃ³rio detalhado linha a linha
```

O `pytest.ini` jÃ¡ define `DJANGO_SETTINGS_MODULE=config.settings_test`
(`config/settings_test.py`): SQLite em memÃ³ria, `LocMemCache` (`CACHE_ENABLED=True`),
`MESSAGERIA_ENABLED=False`, hashers MD5 e throttle elevado â€” a suÃ­te evita
dependÃªncias externas (PostgreSQL, Redis, broker). No container, a mesma suÃ­te
roda com `docker-compose exec api pytest --cov`.

### O que a suÃ­te prova

| Camada | Cobertura |
| :--- | :--- |
| `events/contracts.py` Â· `events/topology.py` | Contratos: serializaÃ§Ã£o, validaÃ§Ã£o e topologia â€” 100%. |
| `services/cache.py` Â· `services/cache_invalidation.py` | Cache-aside com `FakeRedis`, TTL, invalidaÃ§Ã£o por eventos, mÃ©tricas e falhas do Redis â€” 100%. |
| `services/events.py` Â· `services/idempotencia.py` | Dispatcher in-process e deduplicaÃ§Ã£o com falha de Redis caindo no PostgreSQL. |
| `services/pagamento.py` Â· `services/notificacao.py` | Pedido âž” Pagamento âž” NotificaÃ§Ã£o: idempotÃªncia, corridas e publicaÃ§Ã£o â€” 100%. |
| `services/health.py` Â· `services/publicacao.py` Â· `services/messaging.py` | Healthchecks (PostgreSQL/Redis/broker) e fachada de transporte (kafka/rabbitmq/rejeiÃ§Ã£o). |
| `api/*` | Serializers (validaÃ§Ãµes), permissÃµes, filtros, paginaÃ§Ã£o, auth JWT e cache stats â€” 99â€“100%. |
| `repositories/models.py` Â· seeds | Models e comandos `seed_demo_users` / `seed_demo_catalog` â€” 100%. |

As barras e o estado realista aparecem com `--cov term-missing`; a meta de
85% Ã© imposta por `[report] fail_under` no `.coveragerc`.

### Escopo da mediÃ§Ã£o

A cobertura mede o cÃ³digo de aplicaÃ§Ã£o. Ficam de fora, de propÃ³sito
(documentado em `.coveragerc`): migraÃ§Ãµes, `__init__`, `config/settings*.py`,
pontas WSGI/ASGI e os **transportes de broker**
(`services/messaging_kafka.py`, `services/messaging_rabbit.py`), que exigem um
broker real no ar e por isso sÃ£o exercitados pelo smoke test do Compose (Aula 10).

---

## 14. VariÃ¡veis de ambiente

A configuraÃ§Ã£o dos serviÃ§os Ã© feita por variÃ¡veis de ambiente. O `docker-compose.yml`
interpola essas variÃ¡veis (`${VAR}`) a partir do arquivo `.env` da raiz do projeto e injeta
os valores nos contÃªineres. Para comeÃ§ar:

```bash
cp .env.example .env
```

O `.env` **nÃ£o Ã© versionado** (ver `.gitignore`/`.dockerignore`); o `.env.example` Ã© o
modelo versionado com todas as variÃ¡veis. Todos os valores tÃªm default em `:-` no compose,
entÃ£o o ambiente tambÃ©m sobe sem `.env` (com os valores de dev).

| VariÃ¡vel | Default | Consumida por |
| :--- | :--- | :--- |
| `DJANGO_SECRET_KEY` | `dev-insecure-synapseshop-change-me` | `api` (`config/settings.py`) |
| `DJANGO_DEBUG` | `true` | `api` (`config/settings.py`) |
| `JWT_ACCESS_TOKEN_MINUTES` | `60` | `api` (`config/settings.py` â€” lifetime do access JWT) |
| `JWT_REFRESH_TOKEN_DAYS` | `7` | `api` (`config/settings.py` â€” lifetime do refresh JWT) |
| `THROTTLE_ANON` | `20/min` | `api` (`config/settings.py` â€” throttling de nÃ£o autenticados) |
| `THROTTLE_USER` | `200/min` | `api` (`config/settings.py` â€” throttling de autenticados) |
| `THROTTLE_LOGIN` | `5/min` | `api` (`config/settings.py` â€” throttling do login/token) |
| `REDIS_URL` | `redis://redis:6379/1` (Compose) Â· `redis://localhost:6379/1` (cÃ³digo) | `api` (`config/settings.py` â€” cache e throttling) |
| `CACHE_ENABLED` | `true` | `api` (`config/settings.py` â€” kill-switch do cache-aside) |
| `CACHE_TTL_LISTA` | `60` | `api` (`config/settings.py` â€” TTL da listagem em segundos) |
| `CACHE_TTL_DETALHE` | `300` | `api` (`config/settings.py` â€” TTL do detalhe em segundos) |
| `CACHE_TTL_PEDIDO` | `60` | `api`, `pedido-worker`, `notificacao-worker` (`config/settings.py` â€” TTL do detalhe do pedido, Aula 11) |
| `RABBITMQ_HOST` | `rabbitmq` (Compose) Â· `localhost` (cÃ³digo) | `api`, `pedido-worker`, `notificacao-worker` |
| `RABBITMQ_PORT` | `5672` | `api`, `pedido-worker` |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | `guest` / `guest` | `api`, `pedido-worker` |
| `RABBITMQ_VHOST` | `/` | `api`, `pedido-worker` |
| `MENSAGERIA_BROKER` | `kafka` | `api`, `pedido-worker`, `notificacao-worker` â€” broker ativo (`kafka` ou `rabbitmq`) |
| `MENSAGERIA_ENABLED` | `true` | `api` (`config/settings.py` â€” kill-switch da publicaÃ§Ã£o) |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` (cÃ³digo) Â· `kafka:29092` (Compose) | `api`, `pedido-worker`, scripts |
| `KAFKA_TOPICO_PEDIDO_CRIADO` | `pedidos.pedidocriado` | `api`, `pedido-worker` |
| `KAFKA_TOPICO_PEDIDO_CRIADO_DLQ` | `pedidos.pedidocriado.dlq` | `api`, `pedido-worker` |
| `KAFKA_TOPICO_PAGAMENTO_PROCESSADO` | `pagamentos.pagamentoprocessado` | `api`, `notificacao-worker` (Aula 11) |
| `KAFKA_TOPICO_PAGAMENTO_PROCESSADO_DLQ` | `pagamentos.pagamentoprocessado.dlq` | `api`, `notificacao-worker` (Aula 11) |
| `KAFKA_TOPICO_NOTIFICACAO_ENVIADA` | `notificacoes.notificacaoenviada` | `api`, `notificacao-worker` (Aula 11) |
| `KAFKA_TOPICO_NOTIFICACAO_ENVIADA_DLQ` | `notificacoes.notificacaoenviada.dlq` | `api`, `notificacao-worker` (Aula 11) |
| `KAFKA_GRUPO_NOTIFICACAO` | `notificacao-worker` | `notificacao-worker` (Aula 11) |
| `KAFKA_PARTICOES` | `3` | `api`, `pedido-worker`, `notificacao-worker` (paralelismo de consumo) |
| `KAFKA_REPLICAS` | `1` | `api`, `pedido-worker` (1 = broker Ãºnico) |
| `KAFKA_RETENTION_MS` | `604800000` (7 dias) | `api`, `pedido-worker` |
| `KAFKA_CLEANUP_POLICY` | `delete` | `api`, `pedido-worker` |
| `KAFKA_GRUPO_CONSUMIDORES` | `pedido-worker` | `pedido-worker` |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | `pedido-worker` |
| `KAFKA_PRODUCER_ACKS` | `all` | `api`, `pedido-worker` |
| `KAFKA_PRODUCER_LINGER_MS` | `5` | `api`, `pedido-worker` |
| `KAFKA_POLL_TIMEOUT_S` | `1.0` | `pedido-worker` |
| `KAFKA_SESSION_TIMEOUT_MS` | `10000` | `pedido-worker` |
| `KAFKA_MAX_POLL_INTERVAL_MS` | `300000` | `pedido-worker` |
| `IDEMPOTENCIA_TTL_SEGUNDOS` | `86400` | `api`, `pedido-worker` (janela de deduplicaÃ§Ã£o) |
| `MENSAGERIA_MAX_RETRIES` | `3` | `pedido-worker` (reentregas alÃ©m da 1Âª tentativa) |
| `MENSAGERIA_BACKOFF_BASE_MS` | `250` | `pedido-worker` (base do recuo exponencial) |
| `MENSAGERIA_BACKOFF_MAX_MS` | `5000` | `pedido-worker` (teto do recuo) |
| `RABBITMQ_PREFETCH` | `1` | `pedido-worker` (mensagens em voo por consumidor) |
| `RABBITMQ_FILA_PAGAMENTO_PROCESSADO` / `RABBITMQ_FILA_PAGAMENTO_PROCESSADO_DLQ` | `pagamentos.pagamentoprocessado` / `pagamentos.pagamentoprocessado.dlq` | `api`, `notificacao-worker` (Aula 11) |
| `RABBITMQ_FILA_NOTIFICACAO_ENVIADA` / `RABBITMQ_FILA_NOTIFICACAO_ENVIADA_DLQ` | `notificacoes.notificacaoenviada` / `notificacoes.notificacaoenviada.dlq` | `api`, `notificacao-worker` (Aula 11) |
| `RABBITMQ_ROUTING_KEY_PAGAMENTO_PROCESSADO` | `pagamento.processado` | `api`, `notificacao-worker` (Aula 11) |
| `RABBITMQ_ROUTING_KEY_NOTIFICACAO_ENVIADA` | `notificacao.enviada` | `api`, `notificacao-worker` (Aula 11) |
| `PEDIDO_WORKER_FALHA_IDEM_KEYS` | (vazio) | `pedido-worker` (padrÃµes `fnmatch` de `idempotency_key` para simular erro) |
| `NOTIFICACAO_WORKER_FALHA_IDEM_KEYS` | (vazio) | `notificacao-worker` (padrÃµes `fnmatch` para simular erro â€” aceita `pedido:<id>` ou `pagamento:<id>`) |
| `LOG_LEVEL_SYNAPSESHOP` | `INFO` | `api`, `pedido-worker` (nÃ­vel dos logs estruturados) |
| `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` / `SEED_ADMIN_EMAIL` | `admin` / `admin` / `admin@synapseshop.local` | `api` (`seed_demo_users`) |
| `SEED_USER_USERNAME` / `SEED_USER_PASSWORD` / `SEED_USER_EMAIL` | `user` / `user` / `user@synapseshop.local` | `api` (`seed_demo_users`) |
| `POSTGRES_DB` | `synapseshop` | `postgres`, `api`, `inventory` |
| `POSTGRES_USER` | `synapseshop` | `postgres`, `api`, `inventory` |
| `POSTGRES_PASSWORD` | `synapseshop` | `postgres`, `api`, `inventory` |
| `POSTGRES_HOST` | `postgres` (Compose) Â· `localhost` (cÃ³digo) | `api`, `inventory` |
| `POSTGRES_PORT` | `5432` | `api`, `inventory` |
| `DATABASE_URL` | (vazio) | `inventory` (prioridade sobre `POSTGRES_*`) |

> **Fora do Docker:** os serviÃ§os mantÃªm defaults de cÃ³digo (`config/settings.py` e
> `inventory/app/db.py` apontam para `localhost:5432/synapseshop`; `config/settings.py` usa a
> secret de dev), ou exporte as variÃ¡veis manualmente no seu shell. Para rodar a API Django
> fora do Compose Ã© preciso um PostgreSQL acessÃ­vel em `localhost:5432` â€” a instalaÃ§Ã£o do
> driver Ã© `pip install -r requirements.txt` (inclui `psycopg[binary]`). NÃ£o hÃ¡ dependÃªncia
> de `python-dotenv` â€” o `.env` Ã© de responsabilidade do Docker Compose.

---

## 15. DocumentaÃ§Ã£o & EspecificaÃ§Ãµes

| Arquivo | DescriÃ§Ã£o |
| :--- | :--- |
| [`README.md`](README.md) | VisÃ£o geral do projeto, equipe, domÃ­nio, MVP e arquitetura. |
| [`PROMPTS.md`](PROMPTS.md) | HistÃ³rico do uso de IA generativa (prompts utilizados pela equipe). |
| [`specs/specs_da_aula_1.md`](specs/specs_da_aula_1.md) | Kick-off, formaÃ§Ã£o do time e criaÃ§Ã£o do repositÃ³rio. |
| [`specs/specs_da_aula_2.md`](specs/specs_da_aula_2.md) | Esqueleto do projeto em camadas e conteinerizaÃ§Ã£o (Docker). |
| [`specs/specs_da_aula_3.md`](specs/specs_da_aula_3.md) | Docker essencial: multistage build, cache e Compose (API + banco). |
| [`specs/specs_da_aula_4.md`](specs/specs_da_aula_4.md) | CRUD da API principal com Django REST Framework. |
| [`specs/specs_da_aula_5.md`](specs/specs_da_aula_5.md) | MicrosserviÃ§o de inventÃ¡rio em FastAPI. |
| [`specs/specs_da_aula_6.md`](specs/specs_da_aula_6.md) | Modelagem relacional, Ã­ndices e migraÃ§Ãµes (Alembic). |
| [`specs/specs_da_aula_7.md`](specs/specs_da_aula_7.md) | AutenticaÃ§Ã£o JWT com papÃ©is e throttling. |
| [`docs/DECISOES_TECNICAS_AULA6.md`](docs/DECISOES_TECNICAS_AULA6.md) | DecisÃµes tÃ©cnicas da Aula 6. |
| [`docs/METRICAS_AULA6.md`](docs/METRICAS_AULA6.md) | Tempos de execuÃ§Ã£o das transaÃ§Ãµes (Aula 6). |
| [`docs/DECISOES_TECNICAS_AULA7.md`](docs/DECISOES_TECNICAS_AULA7.md) | DecisÃµes tÃ©cnicas da Aula 7. |
| [`docs/METRICAS_AULA7.md`](docs/METRICAS_AULA7.md) | EvidÃªncias de autenticaÃ§Ã£o/throttling/acesso (Aula 7). |
| [`specs/specs_da_aula_8.md`](specs/specs_da_aula_8.md) | Cache-aside com Redis, TTL e invalidaÃ§Ã£o por eventos. |
| [`docs/DECISOES_TECNICAS_AULA8.md`](docs/DECISOES_TECNICAS_AULA8.md) | DecisÃµes tÃ©cnicas de chaves, TTL e invalidaÃ§Ã£o (Aula 8). |
| [`docs/METRICAS_AULA8.md`](docs/METRICAS_AULA8.md) | LatÃªncia, RPS, hit rate e ciclo de vida do cache (Aula 8). |
| [`specs/specs_da_aula_9.md`](specs/specs_da_aula_9.md) | Mensageria assÃ­ncrona e filas com RabbitMQ. |
| [`docs/DECISOES_TECNICAS_AULA9.md`](docs/DECISOES_TECNICAS_AULA9.md) | DecisÃµes de broker, contrato, idempotÃªncia e polÃ­tica de falha (Aula 9). |
| [`docs/METRICAS_AULA9.md`](docs/METRICAS_AULA9.md) | Tempos de execuÃ§Ã£o, tentativas e evidÃªncias da DLQ (Aula 9). |
| [`specs/specs_da_aula_10.md`](specs/specs_da_aula_10.md) | Kafka na Camada 5: partiÃ§Ãµes, offsets manuais, reentrega, DLQ e mÃ©tricas. |
| [`docs/DECISOES_TECNICAS_AULA10.md`](docs/DECISOES_TECNICAS_AULA10.md) | DecisÃµes de topologia, partiÃ§Ãµes, commit, idempotÃªncia e DLQ (Aula 10). |
| [`docs/METRICAS_AULA10.md`](docs/METRICAS_AULA10.md) | LatÃªncia ponta a ponta, throughput de consumo e efeito do paralelismo (Aula 10). |
| [`specs/specs_da_aula_11.md`](specs/specs_da_aula_11.md) | Pedido â†’ Pagamento â†’ NotificaÃ§Ã£o com eventos, cache do pedido e healthchecks. |
| [`docs/DECISOES_TECNICAS_AULA11.md`](docs/DECISOES_TECNICAS_AULA11.md) | DecisÃµes da Aula 11: contratos, topologia, cache, DLQ e fluxo completo. |
| [`docs/METRICAS_AULA11.md`](docs/METRICAS_AULA11.md) | EvidÃªncias do fluxo completo, cache, idempotÃªncia e DLQ (Aula 11). |
| [`specs/specs_da_aula_12.md`](specs/specs_da_aula_12.md) | SuÃ­te de testes: unitÃ¡rios parametrizados, integraÃ§Ã£o do ciclo de vida e meta de cobertura. |
| [`pytest.ini`](pytest.ini) Â· [`.coveragerc`](.coveragerc) Â· [`config/settings_test.py`](config/settings_test.py) | Infraestrutura da suÃ­te de testes (settings, fakes e escopo de cobertura). |
| [`.env.example`](.env.example) | Modelo versionado das variÃ¡veis de ambiente. |
| [`PROMPTS-TEMPLATE.md`](PROMPTS-TEMPLATE.md) | Template padrÃ£o de prompts de IA da squad. |
| [`docs/CHECKLIST_IA_SAFE.md`](docs/CHECKLIST_IA_SAFE.md) | Checklist de revisÃ£o de cÃ³digo gerado por IA. |
| [`docs/postman/SynapseShop_Aula4.postman_collection.json`](docs/postman/SynapseShop_Aula4.postman_collection.json) | ColeÃ§Ã£o Postman das rotas da Aula 4. |
| [`docs/postman/SynapseShop_Aula7.postman_collection.json`](docs/postman/SynapseShop_Aula7.postman_collection.json) | ColeÃ§Ã£o Postman da Aula 7 (login, sucesso, erro e acesso negado). |
| [`specs/PROJECT_OVERVIEW.MD`](specs/PROJECT_OVERVIEW.MD) | VisÃ£o geral do SynapseShop e trilha de entregas (25 aulas). |

## 14. Documentação da API (Aula 13)

- **Contrato OpenAPI**: [openapi.yaml](openapi.yaml) na raiz (OpenAPI 3.0.3).
- **Interfaces interativas**: /docs/ (Swagger UI) e /docs/redoc/ (ReDoc), servidas via CDN sem drf-spectacular.
- **Specs e diretrizes**: [specs/specs_da_aula_13.md](specs/specs_da_aula_13.md), [specs/00_diretriz_incremental_specdd.md](specs/00_diretriz_incremental_specdd.md).
- **Documentação técnica**: [docs/CONVENCOES_API.md](docs/CONVENCOES_API.md), [docs/CHECKLIST_INTEGRADOR_EXTERNO.md](docs/CHECKLIST_INTEGRADOR_EXTERNO.md), [docs/OPENAPI.md](docs/OPENAPI.md), [CHANGELOG.md](CHANGELOG.md).
- **Postman**: [docs/postman/SynapseShop_Aula13.postman_collection.json](docs/postman/SynapseShop_Aula13.postman_collection.json), [docs/postman/SynapseShop_Aula7.postman_collection.json](docs/postman/SynapseShop_Aula7.postman_collection.json), environment [docs/postman/SynapseShop_Local.postman_environment.json](docs/postman/SynapseShop_Local.postman_environment.json).

**Headers de contrato**: Authorization: Bearer <token>, Idempotency-Key (alternativa a idempotency_key no corpo), X-Trace-Id (propagado como correlation_id e ecoado).

**Erros**: padrão RFC 7807 (pplication/problem+json) com esquema Problem. Paginação page/page_size, filtros search/is_active/category, ordenação ordering.
