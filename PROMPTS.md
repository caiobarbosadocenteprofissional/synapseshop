# PROMPTS.md — Histórico de Uso de IA Generativa

> Registro obrigatório do uso de ferramentas de IA generativa durante o desenvolvimento do
> **SynapseShop** (SynapseTech). Mantenha este arquivo atualizado sempre que a IA for utilizada.

---

## 1. Como registrar

Para cada uso de IA generativa, adicione uma entrada na seção [Histórico de Prompts](#3-histórico-de-prompts),
preenchendo:

- **Data** — dia do uso (AAAA-MM-DD).
- **Autor(a)** — integrante que utilizou.
- **Ferramenta** — ferramenta/modelo usado (ex.: OpenAI, DeepSeek, opencode, etc.).
- **Contexto** — objetivo do uso (ex.: geração de código, revisão, documentação, testes).
- **Prompt utilizado** — texto integral do prompt enviado.
- **Resultado / Ajustes** — resumo do resultado e ajustes realizados a partir da resposta.

---

## 2. Template de entrada

```markdown
### Data — [Autor(a)] — [Ferramenta]
- **Contexto:** 
- **Prompt:** 
- **Resultado / Ajustes:** 
```

---

## 3. Histórico de Prompts

### 2026-09-16 — Equipe SynapseShop — opencode
- **Contexto:** Aula 3 — geração do `Dockerfile` com *multistage build* e cache eficiente de dependências.
- **Prompt:** "Seguindo as skills, a diretriz_incremental e o specs_da_aula_3, execute o item de DoD: o `Dockerfile` implementa a arquitetura de multistage build e gerencia o cache eficiente de dependências."
- **Resultado / Ajustes:** Criado `requirements.txt` (sem dependências, apenas comentário — escopo SpecDD), reescrito o `Dockerfile` em dois estágios (`builder` gera wheels via `pip wheel`; `runtime` enxuto instala off-line com `--no-index --find-links` e remove os wheels) e adicionado `.dockerignore`. O `COPY requirements.txt` é feito antes do código para preservar o cache; usuário não-root (`useradd` + `USER appuser`). Build validado com `docker-compose up --build` e camadas conferidas com `docker history`.

### 2026-09-16 — Equipe SynapseShop — opencode
- **Contexto:** Aula 3 — rota `/health` para monitoramento/validação da aplicação conteinerizada.
- **Prompt:** "Atualize o spec da aula 3 com o que for feito (implementar e expor a rota /health sem antecipar frameworks)."
- **Resultado / Ajustes:** Criado `api/health.py` usando apenas a stdlib (`http.server`) — sem antecipar Django REST Framework/FastAPI — expondo `GET /health` → `{"status": "ok"}`. O `CMD` do `Dockerfile` passou a executar esse servidor (porta 8000).

### 2026-09-16 — Equipe SynapseShop — opencode
- **Contexto:** Aula 3 — orquestração no `docker-compose.yml` integrando API e Banco de Dados com variáveis essenciais.
- **Prompt:** "Integre a API e o Banco de Dados no docker-compose.yml com injeção de variáveis de ambiente mínimas."
- **Resultado / Ajustes:** Serviço `api` (build da imagem, porta 8000, `depends_on` do banco com `service_healthy`) e serviço `postgres` (`postgres:16-alpine`, porta 5432, volume `pgdata`, `healthcheck` com `pg_isready`). As variáveis `POSTGRES_*` são injetadas no contêiner da API. Ambiente completo sobe com `docker-compose up`.

### 2026-09-17 — Equipe SynapseShop — opencode
- **Contexto:** Aula 4 — planejamento e estruturação do projeto Django/DRF em camadas.
- **Prompt:** "Faça o planejamento de execução das specs_da_aula_4. Siga a diretriz incremental_specdd e as skills que foram definidas."
- **Resultado / Ajustes:** Plano incremental definido com decisões de estrutura: projeto `config/` e apps Django por camada (`repositories/` = models; `api/` = serializers/viewsets/rotas), banco SQLite, coleção Postman e `/health` portado para Django. Adicionado `Django==5.2.*` e `djangorestframework==3.18.0` ao `requirements.txt`, criados `manage.py` e `config/settings.py` (INSTALLED_APPS enxuto, envs com defaults de dev). Intervenção manual: descartados `admin`, `auth` e qualquer biblioteca de JWT/Redis/FastAPI/mensageria para respeitar o escopo da aula.

### 2026-09-17 — Equipe SynapseShop — opencode
- **Contexto:** Aula 4 — models `Category`/`Item`, serializers, viewsets e roteamento `/api/v1/`.
- **Prompt:** "Modele as entidades base (Category e Item) com o ORM do Django, crie ModelSerializers com validações e exponha ModelViewSets sob /api/v1/ via DefaultRouter."
- **Resultado / Ajustes:** `repositories/models.py` com `Category` (name único) e `Item` (`price` Decimal com `MinValueValidator(0)`, FK `category` com `CASCADE`/`related_name`, `is_active`, timestamps). `api/serializers.py` com validações customizadas (`validate_name`, `validate_price`) retornando 400; `category_name` somente-leitura. ViewSets em `api/views.py`, roteador em `api/urls.py` (`/api/v1/categories/` e `/api/v1/items/`) e view `health` (`JsonResponse`). Migração `0001_initial` gerada com `makemigrations` e validada com `python manage.py check`. Intervenção manual: omitidos campos de estoque (Aula 5) para não antecipar escopo.

### 2026-09-17 — Equipe SynapseShop — opencode
- **Contexto:** Aula 4 — checklist "IA-safe", coleção Postman e documentação.
- **Prompt:** "Elabore o checklist IA-safe no repositório, exporte as rotas em uma coleção Postman e atualize README e PROMPTS.md."
- **Resultado / Ajustes:** Criado `docs/CHECKLIST_IA_SAFE.md` (escopo, imports, tipos, validações, status HTTP, segurança). Coleção exportada em `docs/postman/SynapseShop_Aula4.postman_collection.json` (13 requisições com asserts de 200/201/204/400/404). README recebeu a seção "API Principal (Aula 4)". Ajustados `Dockerfile` (CMD detecta e aplica migrações + `runserver`), `docker-compose.yml` (`start_period` no healthcheck) e `.dockerignore` (`docs/`, `db.sqlite3`). Intervenção manual: removido `api/health.py` (servidor stdlib) para evitar código morto.

### 2026-09-18 — Equipe SynapseShop — opencode
- **Contexto:** Aula 5 — planejamento do microsserviço de inventário (porta 8100) e definição do escopo.
- **Prompt:** "Seguindo as specs e as skills definidas execute a specs_da_aula_5."
- **Resultado / Ajustes:** Plano incremental definido com decisões de estrutura: novo diretório `inventory/` com app FastAPI próprio (multistage no Dockerfile, porta 8100), estado em memória, `PROMPTS-TEMPLATE.md` na raiz e integração via `docker-compose.yml`. Consulta da versão mais recente do FastAPI (0.141.1) e uvicorn (0.53.0) para o pin no padrão do repo (`fastapi==0.141.*`, `uvicorn[standard]==0.53.*`).

### 2026-09-18 — Equipe SynapseShop — opencode
- **Contexto:** Aula 5 — geração do scaffold do microsserviço inventory com modelos Pydantic, tipagem estática e rotas mínimas.
- **Prompt:** "Crie o scaffold do microsserviço de estoque em FastAPI com modelos Pydantic, dependency de armazenamento em memória e endpoints estruturados com response_model/status codes padrão, sem antecipar banco de dados (Aula 6) nem autenticação (Aula 7)."
- **Resultado / Ajustes:** Criados `inventory/requirements.txt`, `app/schemas.py` (`HealthResponse`, `MessageResponse`, `InventoryItem`, `Create`/`Update` com `min_length`/`ge`), `app/storage.py` (`InventoryStore` em memória + `get_store()`), `app/routes.py` (CRUD sob `/inventory/items` com 200/201/204/404) e `app/main.py` (`GET /`, `GET /health`, título OpenAPI). `Dockerfile` em multistage com usuário não-root e `CMD uvicorn app.main:app --port 8100`; `inventory/.dockerignore` enxuto. Intervenção manual: ajustados campos de `InventoryItemUpdate` (todos opcionais via `exclude_unset`), protegido `.dockerignore` para não excluir `requirements.txt` do build e adicionadas respostas 404 explícitas no OpenAPI.

### 2026-09-18 — Equipe SynapseShop — opencode
- **Contexto:** Aula 5 — integração do inventory ao orquestrador, criação do `PROMPTS-TEMPLATE.md` e validação da documentação automática.
- **Prompt:** "Integre o serviço de inventário ao docker-compose.yml com healthcheck próprio, crie o PROMPTS-TEMPLATE.md padronizando prompts da squad e valide o /docs do FastAPI."
- **Resultado / Ajustes:** Serviço `inventory` adicionado ao `docker-compose.yml` (build `./inventory`, `synapseshop-inventory:dev`, porta `8100:8100`, `healthcheck` via `urllib` em `/health`). Criado `PROMPTS-TEMPLATE.md` com estrutura obrigatória (contexto, objetivo, restrições SpecDD, entrada, saída esperada, critérios de aceite) e exemplo preenchido da Aula 5. README atualizado (tabela de serviços, seção "Microsserviço de Inventário (Aula 5)" e tabela de documentação). Ambiente validado com `docker-compose up --build -d`, endpoints testados em `localhost:8100` e Swagger acessível em `/docs`.

<!-- Adicione aqui as entradas do histórico conforme o template da seção 2. -->

---

## 4. Nota

As respostas geradas por IA devem sempre ser revisadas e validadas por um integrante do time antes
de integrar ao código, seguindo as boas práticas do projeto.