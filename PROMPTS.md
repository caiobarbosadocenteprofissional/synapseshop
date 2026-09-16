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

<!-- Adicione aqui as entradas do histórico conforme o template da seção 2. -->

---

## 4. Nota

As respostas geradas por IA devem sempre ser revisadas e validadas por um integrante do time antes
de integrar ao código, seguindo as boas práticas do projeto.