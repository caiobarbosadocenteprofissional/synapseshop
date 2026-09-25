# Decisões Técnicas — Aula 7 (Autenticação JWT, Papéis e Throttling)

> Registro formal das decisões técnicas tomadas pela equipe SynapseShop na Aula 7,
> guiadas pelo DoD de `specs/specs_da_aula_7.md` e pela diretriz SpecDD.

---

## 1. Escopo e alvo da camada de acesso seguro

- **Decisão:** o JWT com papéis, throttling e permissões foi implementado na **API
  principal (Django/DRF)** sob `/api/v1/`.
- **Motivo:** o DoD da Aula 7 fala de "endpoints críticos da API" com paginação e
  filtros (mecanismo DRF), proteção de "rotas administrativas" e coleção Postman —
  tudo centrado na API principal. O `inventory` (FastAPI) já havia sinalizado que a
  autenticação "fica na Aula 7", porém o escopo prioritário/verificável é o DRF.
- **Alternativa descartada:** proteger também o `inventory` nesta aula. Isso exigiria
  novas dependências (verificação de token no FastAPI) e ampliaria o escopo do DoD sem
  critério verificável correspondente. Fica como consenso do time para uma evolução
  posterior, sem antecipação aqui (voz ativa já autorizada pela squad na reunião da aula).

## 2. Item 1 da seção 3 da spec ("índices compostos, rollback seguro, repositório transacional")

- **Decisão:** classificado como **artefato da Aula 6** (trecho copiado da spec da Aula 6 —
  já entregue em `DECISOES_TECNICAS_AULA6.md` e `METRICAS_AULA6.md`). A execução da Aula 7
  foi guiada exclusivamente pelo seu DoD.

## 3. Biblioteca e versões

- **Decisão:** `djangorestframework-simplejwt==5.5.*` (v5.5.1 no build), pin no padrão do
  repositório (versão `.*`). Escolhida por ser o padrão de fato para JWT no DRF, sem
  vulns conhecidas na versão pinada (resolve também PYSEC que afetava 5.3/5.4).

## 4. Modelo de usuário com papéis

- **Decisão:** `User` customizado em `repositories` subclasses de
  `django.contrib.auth.models.AbstractUser`, com campo `role` (`admin`|`user`, default
  `user`), e `AUTH_USER_MODEL = "repositories.User"`.
- **Motivo:** o `django.contrib.auth` nunca esteve em `INSTALLED_APPS` nas aulas
  anteriores — não existem tabelas de `auth_user` no banco —, então a troca para um
  modelo customizado não gera conflito de migrações. O `AbstractUser` aproveita o
  gerenciador (`create_user`), hashing de senha e validações padrão.
- **Coerência:** usuários `admin` também são marcados como `is_staff`/`is_superuser`
  no seed; a proteção das rotas, porém, usa o **papel** (`IsAdminRole`), não `is_staff`.

## 5. Fluxos JWT (stateless, Bearer)

- **Decisão:** fluxo **JWT** (sem sessão) — autenticação stateless coerente com a
  arquitetura-alvo de gateway. Rotas: `POST /api/v1/auth/token/` (obtenção) e
  `POST /api/v1/auth/token/refresh/` (renovação).
- **Claim de papel:** o token (access e refresh) carrega a claim `role`; os serializers
  customizados devolvem `role` também na resposta, evitando chamada extra de "quem sou eu".
- **Tempos de vida:** access 60 min e refresh 7 dias (configuráveis via env), algoritmo
  HS256 com a `DJANGO_SECRET_KEY`.

## 6. Throttling (segurança mínima)

- **Decisão:** três escopos de rate limit:
  - `anon` (20/min) e `user` (200/min) globais, aplicados aos endpoints DRF;
  - `login` (5/min) **escopado** apenas nas rotas de token, como proteção contra força
    bruta — executado antes da verificação de credenciais (429 no 6º login consecutivo).
- **Motivo:** combina limite global (estilo da aplicação) com limite fino no ponto mais
  sensível (login), ambos configuráveis via env (`THROTTLE_*`).

## 7. Permissões e proteção das rotas administrativas

- **Decisão:** leitura (`list`/`retrieve`) exige **autenticação** (qualquer papel);
  escrita (`create`/`update`/`partial_update`/`destroy`) exige **papel `admin`** via
  permission customizada `IsAdminRole`.
- **Status codes:** sem token → **401**; usuário autenticado sem papel admin → **403**.
  A rota `/health` permanece pública (monitoramento).

## 8. Paginação e filtros nos endpoints críticos

- **Decisão:** `PageNumberPagination` (default `page_size=10`, ajuste via
  `page_size`) habilitado globalmente na API.
- **Filtros coerentes:** `SearchFilter` + `OrderingFilter` (namespace no DRF) em
  `categories` (`name`, `description`) e `items` (`name`, `description`), mais filtros
  por **query param** em `items` (`is_active`, `category`) via override de
  `get_queryset`.
- **Alternativa descartada:** `django-filter` — nova dependência não necessária para o
  escopo; os filtros pedidos são cobertos pelos recursos nativos do DRF.

## 9. Seed de usuários demo

- **Decisão:** comando idempotente `python manage.py seed_demo_users` criando `admin`
  (papel admin) e `user` (papel user) com credenciais de dev via env `SEED_*`. Executado
  no start do container (após `migrate`), garantindo que a coleção Postman funcione de
  imediato. No ambiente real as credenciais seriam trocadas pelas variáveis.

## 10. Coleção Postman

- **Decisão:** nova coleção `docs/postman/SynapseShop_Aula7.postman_collection.json`
  com cenários ordenados: Health; Auth (login admin/user ok, erro 401, refresh);
  Acesso Negado (401 sem token, 403 user); Admin (CRUD admin 201/200/204); Paginação e
  Filtros; Throttling (429 após exaurir `login`). Tokens são salvos em variáveis da
  coleção via scripts de teste.

## 11. Infraestrutura e migrações

- **Migrações:** adicionado `django.contrib.auth` (migrações nativas de
  grupos/permissões) e `repositories/migrations/0002_user.py` criado com
  `makemigrations repositories` e aplicado com `migrate` (validado localmente e no
  contêiner). `AUTH_USER_MODEL` definido **antes** da primeira execução de migração.
- **Variáveis de ambiente:** `.env.example` ganhou `JWT_*`, `THROTTLE_*` e `SEED_*`,
  injetadas no serviço `api` do Compose com default `:-`.

## 12. Persistência: PostgreSQL na API principal

- **Decisão:** a API principal (Django/DRF) passou de SQLite para o **PostgreSQL** do
  Compose (`postgres:16-alpine`, volume `pgdata`), o mesmo banco do microsserviço
  `inventory`. O bloco `DATABASES` de `config/settings.py` lê as cinco variáveis
  `POSTGRES_*` (default de código `localhost`, sobrescrito para `postgres` pelo Compose),
  espelhando o contrato já usado em `inventory/app/db.py`.
- **Motivo:** a Camada 5 da arquitetura-alvo (`specs/PROJECT_OVERVIEW.MD`) define
  PostgreSQL como a camada de dados do MVP, e o Compose já provisionava o serviço
  `postgres` com healthcheck, `depends_on: service_healthy` e as credenciais já injetadas
  no serviço `api` — ou seja, a topologia existia e a API apenas não a consumia. O
  efeito prático era grave na camada de autenticação: `User`, `role` e a resolução do
  token em `JWTAuthentication` liam um `db.sqlite3` descartável dentro do contêiner,
  sem volume, sem healthcheck e perdido a cada rebuild, enquanto a Camada 5 do diagrama
  aparecia como PostgreSQL.
- **Driver:** `psycopg[binary]==3.3.*` (psycopg 3), mesmo pin de
  `inventory/requirements.txt`. A variante `binary` usa wheels pré-compiladas, compatível
  com o multistage build que roda `pip wheel` antes do `pip install --no-index`.
- **Migrações:** nenhuma nova migração. `0001_initial` e `0002_user` são agnósticos de
  backend e aplicam no PostgreSQL sem edição; as tabelas Django entram ao lado de
  `inventory_items` no volume `pgdata`, sem conflito de schema.
- **Alternativa descartada:** manter SQLite na API principal e adicionar apenas a
  autenticação. Mantém duas bases de dados para o mesmo domínio (usuários de um lado,
  itens de estoque do outro) e contraria a Camada 5 da arquitetura-alvo.
- **Sem `DATABASE_URL`:** o Compose já interpola as `POSTGRES_*`; adicionar um parser de
  URL para a API introduziria dependência (`dj-database-url`) sem ganho real. O
  `inventory` mantém seu `DATABASE_URL` porque o Alembic exige uma URL.
- **Nota de ambiente:** fora do Docker, `config/settings.py` resolve `localhost:5432`, o
  que exige um PostgreSQL local — behavior coerente com `inventory/app/db.py`.

## 13. Anti-antecipação (SpecDD)

- **Não implementado nesta aula:** cache-aside com Redis (Aula 8), mensageria
  RabbitMQ/Kafka (Aulas 9–11), suíte `pytest` (Aula 12), serviços de IA (Aulas 14+),
  e *nenhuma* autenticação no microsserviço `inventory`.
- **Registro de IA:** todo uso de IA nesta aula está registrado no `PROMPTS.md`,
  conforme o `PROMPTS-TEMPLATE.md`.