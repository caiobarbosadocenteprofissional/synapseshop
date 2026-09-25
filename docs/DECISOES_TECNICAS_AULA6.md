# Decisões Técnicas — Aula 6 (Modelagem Relacional, Índices e Migrações)

> Registro formal das decisões técnicas tomadas pela equipe SynapseShop na Aula 6,
> conforme o DoD "O repositório foi atualizado com o registro de todas as decisões
> técnicas tomadas durante a modelagem e testes".

---

## 1. Escopo e alvo da camada de persistência

- **Decisão:** a modelagem relacional (SQLAlchemy 2.0 + Alembic + PostgreSQL) foi
  implementada no microsserviço de inventário (`inventory`, FastAPI).
- **Motivo:** o repositório já sinalizava essa intenção — `inventory/app/storage.py`
  declarava que "a modelagem relacional com o ORM/SQLAlchemy e migrações Alembic é
  escopo exclusivo da Aula 6" e o `README.md` mantinha o estado do inventário em
  memória até a Aula 6.
- **Alternativa descartada:** implementar a camada SQLAlchemy na API principal
  (Django/DRF) ao lado do ORM Django. Isso criaria dois ORMs gerenciando o mesmo
  schema (atrito técnico e duplicação de migrações). A API Django permanece em
  SQLite com migrações nativas (escopo das Aulas 4); sua evolução para PostgreSQL
  será decidida em consenso da squad quando necessário.

> **Revisado na Aula 7.** A squad decidiu a evolução para PostgreSQL: a API principal
> migrou de SQLite para o mesmo PostgreSQL do Compose, agora gerenciado pelo ORM do
> Django (nenhum segundo ORM). Ver `DECISOES_TECNICAS_AULA7.md` §12.

## 2. Entidade base modelada

- **Decisão:** a entidade `InventoryItem` → tabela `inventory_items`.
- **Campos:** `id` (PK serial), `sku` (varchar 50, NOT NULL, único), `name`
  (varchar 100, NOT NULL), `quantity` (int, NOT NULL, default 0), `created_at` e
  `updated_at` (timestamptz, `server_default=now()`).
- **Motivo:** é a entidade transacional central do microsserviço e possui uma
  operação transacional natural (ajuste de estoque com regra de domínio).

## 3. Índices essenciais

- **Decisão:**
  - `ix_inventory_items_sku` — índice **único** em `sku` (lookup por código do
    item; impede duplicidade em nível de banco).
  - `ix_inventory_items_name` — índice em `name` (busca/catálogo por nome).
- **Motivo:** toda consulta de domínio relevante (detalhar por SKU e listar/buscar
  itens) é coberta sem scans sequenciais. Índices adicionais são evitados nesta
  fase para não antecipar padrões de consulta de aulas futuras.

## 4. Regras de integridade relacional

- **Decisão:**
  - `NOT NULL` em `sku`, `name` e `quantity`.
  - `UNIQUE` em `sku` (constraint parte do índice único).
  - `CheckConstraint("quantity >= 0")` nomeada `ck_inventory_items_quantity_non_negative`
    — estoque nunca negativo.
  - `PRIMARY KEY` em `id` (serial).
- **Motivo:** garantir atomicidade e consistência transacional em camada de banco,
  mesmo que a aplicação (serviço) falhe em validar a regra.

## 5. Versionamento de schema (Alembic)

- **Decisão:** scaffolding do Alembic dentro de `inventory/`:
  - `alembic.ini` (config, `script_location = migrations`);
  - `migrations/env.py` (usa `app.db.engine` e `Base.metadata`, URL via env
    `DATABASE_URL`/`POSTGRES_*`);
  - `migrations/versions/0001_create_inventory_items.py`.
- **Versionamento:** a tabela `alembic_version` registra a revisão corrente
  (`0001`). Comandos: `alembic current`, `alembic history`, `alembic upgrade head`,
  `alembic downgrade -1`.
- **Validação:** `alembic check` reportou "No new upgrade operations detected"
  (nenhum drift entre modelos e migrações).

## 6. Rollback seguro de migração (demonstração)

- **Decisão/Validação:** ciclo completo executado no ambiente real:
  1. `alembic downgrade -1` → removeu a tabela `inventory_items`;
  2. `alembic current` → `<base>`;
  3. `alembic upgrade head` → recriou a tabela e os índices;
  4. `alembic current` → `0001 (head)`.
- **Conclusão:** o versionamento permite reverter com segurança qualquer revisão
  aplicada, mantendo o schema sempre rastreável.

## 7. Repositórios transacionais e serviço

- **Decisão (arquitetura em camadas):**
  - `app/repository.py` — `InventoryRepository`: acesso transacional a
    `inventory_items`; toda escrita termina em `commit` e, em `IntegrityError`
    (`sku` duplicado ou `quantity < 0`), executa `rollback` antes de repassar a
    exceção (garantia de não haver escrita parcial).
  - `app/services.py` — `InventoryService`: consome o repositório e concentra as
    regras de domínio (`DuplicateSkuError`, `InsufficientStockError`), validando-as
    antes da persistência.
  - `app/db.py` — `engine`, `SessionLocal`, `Base` e dependency `get_session()`.
- **Motivo:** separa regra de negócio (serviço) de persistência (repositório),
    reutilizando o padrão API/Service/Repository do projeto.

## 8. API exposta de forma transacional

- **Decisão:** rota adicionada `PATCH /inventory/items/{id}/stock`
  (`StockAdjustRequest {delta}`) para materializar a transação do serviço.
- **Status codes:** `201 Created`; `200 OK`; `204 No Content`; `404 Not Found`;
  `409 Conflict` (SKU duplicado / estoque insuficiente); `422 Unprocessable Entity`
  (validação Pydantic).

## 9. Testes transacionais e métricas

- **Decisão:** `scripts/transactional_test.py` (stdlib, executado dentro do
  contêiner) cobre: seed de inserções, consultas, update, rollback por `sku`
  duplicado, rollback por `quantity < 0` (CHECK no banco), ajuste de estoque e
  limpeza — com **coleta de tempos de execução**.
- **Resultado:** ver `docs/METRICAS_AULA6.md`.

## 10. Anti-antecipação (SpecDD)

- **Não implementado nesta aula:** autenticação JWT/roles (Aula 7), cache Redis
  (Aula 8), mensageria RabbitMQ/Kafka (Aulas 9–11), suíte `pytest` (Aula 12),
  serviços de IA (Aulas 14+).
- **Manutenção:** a API Django (Aulas 4) permanece intocada; o `inventory` não
  ganhou autenticação, cache ou filas.