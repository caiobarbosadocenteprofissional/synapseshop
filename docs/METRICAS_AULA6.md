# Métricas de Execução — Aula 6 (Testes Transacionais)

> Tempos de execução coletados no ambiente real (`docker-compose`) executando
> `inventory/scripts/transactional_test.py` dentro do contêiner do inventário.

---

## 1. Tempos de execução das transações (seed com 10 itens)

| Operação | Registros | Tempo (s) |
| :--- | ---: | ---: |
| Seed de itens (INSERT) | 10 | 0.039846 |
| Consulta lista completa (SELECT) | 10 | 0.001281 |
| Consulta por SKU (índice único) | 1 | 0.001593 |
| Atualização (UPDATE) | 1 | 0.004557 |
| Rollback por sku duplicado | 1 | 0.001258 |
| Rollback por quantity < 0 (CHECK) | 1 | 0.002213 |
| Ajuste de estoque (transação) | 1 | 0.002764 |
| Ajuste insuficiente (regra de domínio) | 1 | 0.000024 |
| Limpeza (DELETE) | 10 | 0.043104 |
| **TOTAL** | — | **0.096640** |

### Resultados dos testes transacionais

- [x] Seed de itens (INSERT transacional).
- [x] Consulta lista completa.
- [x] Consulta por SKU (índice único).
- [x] Update transacional (quantidade = 99).
- [x] Rollback por sku duplicado (sem escrita parcial).
- [x] Rollback por quantity < 0 (CHECK no banco).
- [x] Ajuste de estoque positivo (transação).
- [x] Ajuste insuficiente aborta antes de gravar.
- [x] Limpeza dos dados de teste.

**RESULTADO: PASS** (repetível — segunda execução também PASS).

## 2. Versionamento de schema (evidência)

- `alembic current` → `0001 (head)`
- `alembic history` → `<base> -> 0001 (head), create inventory_items`
- `alembic check` → `No new upgrade operations detected.` (sem drift modelo↔banco)

### Criar executado (psql `\d inventory_items`)

```
Column   |           Type           | Nullable | Default
id       | integer                  | not null | nextval('inventory_items_id_seq')
sku      | character varying(50)    | not null |
name     | character varying(100)   | not null |
quantity | integer                  | not null | 0
created_at | timestamp with time zone | not null | now()
updated_at | timestamp with time zone | not null | now()

Indexes:
    "inventory_items_pkey" PRIMARY KEY, btree (id)
    "ix_inventory_items_name" btree (name)
    "ix_inventory_items_sku" UNIQUE, btree (sku)
Check constraints:
    "ck_inventory_items_quantity_non_negative" CHECK (quantity >= 0)

alembic_version.version_num = 0001
```

## 3. Rollback seguro de migração (demonstração executada)

1. `alembic downgrade -1` → `Running downgrade 0001 -> , create inventory_items`
2. `alembic current` → `<base>`
3. `alembic upgrade head` → `Running upgrade  -> 0001, create inventory_items`
4. `alembic current` → `0001 (head)`

> O ciclo demonstra que qualquer revisão pode ser revertida e reaplicada com
> segurança, mantendo o schema versionado e rastreável.

## 4. Smoke test de contratos HTTP (Aula 5, adaptado na Aula 6)

`inventory/scripts/smoke_test.py` → **12/12 PASS** (health, /docs, openapi, list,
create, get, patch, 404, 422, ajuste de estoque, estoque insuficiente 409, delete).