"""Teste transacional e coleta de tempos de execução (Aula 6).

Valida o funcionamento da persistência relacional do inventário
(SQLAlchemy + PostgreSQL) e coleta os tempos de execução das operações:

1. Seed de itens (INSERT dentro de transações);
2. Consultas (lista completa e lookup por SKU via índice único);
3. Atualização (UPDATE dentro de transação);
4. Rollback por unicidade violada (`sku` duplicado — índice único);
5. Rollback por integridade violada (`quantity < 0` — CHECK constraint);
6. Transação de ajuste de estoque (serviço) e regra de domínio respeitada;
7. Limpeza dos dados de teste.

Uso (dentro do contêiner, com as variáveis POSTGRES_* definidas):

    python scripts/transactional_test.py [--items 10]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Tuple

# Garante que o pacote `app` seja localizável independentemente do CWD:
# permite executar o script de dentro do contêiner ou localmente.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func as safunc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import InventoryItem
from app.repository import InventoryRepository
from app.schemas import InventoryItemCreate, InventoryItemUpdate
from app.services import InsufficientStockError, InventoryService

TIMINGS: List[Tuple[str, int, float, str]] = []


def _timed(label: str, rows: int, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    TIMINGS.append((label, rows, elapsed, "PASS"))
    return result


def _count(session: Session) -> int:
    return session.execute(
        safunc.count(InventoryItem.id).select()
    ).scalar_one()


def _seed(session: Session, repo: InventoryRepository, prefix: str, n: int) -> List[InventoryItem]:
    items: List[InventoryItem] = []

    def do_seed() -> List[int]:
        for i in range(n):
            item = repo.create_item(
                sku=f"{prefix}-{i:04d}",
                name=f"Item transacional {i:04d}",
                quantity=10 + i,
            )
            items.append(item)
        return items

    _timed("seed_create", n, do_seed)
    return items


def main(items: int) -> int:
    session = SessionLocal()
    repo = InventoryRepository(session)
    service = InventoryService(session)
    prefix = f"TST{int(time.time())}"
    failures: List[str] = []

    def check(name: str, ok: bool) -> None:
        results.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(name)

    results: List[str] = []
    seed_ids: List[int] = []
    initial_count = _count(session)

    try:
        # 1. Seed
        created = _seed(session, repo, prefix, items)
        seed_ids = [item.id for item in created]
        check(
            "seed de itens (INSERT transacional)",
            _count(session) == initial_count + items and len(created) == items,
        )

        # 2. Consulta: listagem completa
        listed: List[InventoryItem] = _timed(
            "list_all", items, lambda: repo.list_items()
        )
        check("consulta lista completa", len(listed) == items)

        # 3. Consulta por SKU (índice único)
        target = created[items // 2]

        def lookup() -> InventoryItem:
            found = repo.get_item_by_sku(target.sku)
            assert found is not None
            return found

        looked = _timed("lookup_by_sku", 1, lookup)
        check("consulta por SKU (índice único)", looked.id == target.id)

        # 4. Atualização transacional de quantidade
        def do_update() -> InventoryItem:
            updated = repo.update_item(target.id, quantity=99)
            assert updated is not None
            return updated

        updated = _timed("update_item", 1, do_update)
        check("update transacional (quantidade=99)", updated.quantity == 99)

        # 5. Rollback: sku duplicado viola índice único
        before = _count(session)

        def duplicate_sku() -> None:
            try:
                repo.create_item(sku=target.sku, name="Duplicado", quantity=1)
                raise AssertionError("esperado IntegrityError por SKU duplicado")
            except IntegrityError:
                pass

        _timed("rollback_duplicate_sku", 1, duplicate_sku)
        check(
            "rollback por sku duplicado (sem escrita parcial)",
            _count(session) == before,
        )

        # 6. Rollback: quantity < 0 viola CHECK constraint
        before = _count(session)

        def negative_quantity() -> None:
            try:
                repo.update_item(target.id, quantity=-5)
                raise AssertionError("esperado IntegrityError por quantity < 0")
            except IntegrityError:
                pass

        _timed("rollback_negative_quantity", 1, negative_quantity)
        check(
            "rollback por quantity<0 (CHECK no banco)",
            _count(session) == before
            and repo.get_item(target.id).quantity == 99,
        )

        # 7. Transação de ajuste de estoque pelo serviço
        def adjust_ok() -> InventoryItem:
            item = service.adjust_stock(target.id, -90)
            assert item is not None
            return item

        adj = _timed("adjust_stock_ok", 1, adjust_ok)
        check("ajuste de estoque positivo (transação)", adj.quantity == 9)

        def adjust_fail() -> None:
            try:
                service.adjust_stock(target.id, -100)
                raise AssertionError("esperado InsufficientStockError")
            except InsufficientStockError:
                pass

        _timed("adjust_stock_insufficient", 1, adjust_fail)
        check(
            "ajuste insuficiente aborta antes de gravar",
            repo.get_item(target.id).quantity == 9,
        )
    finally:
        # 8. Limpeza
        def cleanup() -> int:
            removed = 0
            for item_id in seed_ids:
                removed += 1 if repo.delete_item(item_id) else 0
            return removed

        removed = _timed("cleanup_delete", len(seed_ids), cleanup)
        check("limpeza dos dados de teste", removed == len(seed_ids))
        session.close()

    # Relatório
    time_label = {
        "seed_create": "Seed de itens (INSERT)",
        "list_all": "Consulta lista completa (SELECT)",
        "lookup_by_sku": "Consulta por SKU (índice)",
        "update_item": "Atualização (UPDATE)",
        "rollback_duplicate_sku": "Rollback por sku duplicado",
        "rollback_negative_quantity": "Rollback por quantity<0",
        "adjust_stock_ok": "Ajuste de estoque (transação)",
        "adjust_stock_insufficient": "Ajuste insuficiente (regra)",
        "cleanup_delete": "Limpeza (DELETE)",
    }
    report = ["\n=== Tempos de execução (Aula 6) ==="]
    report.append(f"{'Operação':<38} {'Registros':>9} {'Tempo (s)':>10}")
    for label, rows, elapsed, status in TIMINGS:
        report.append(
            f"{time_label.get(label, label):<38} {rows:>9} {elapsed:>10.6f}"
        )
    report.append(
        f"{'TOTAL':<38} {'':>9} {sum(e for _, _, e, _ in TIMINGS):>10.6f}"
    )
    report.append("")
    report.extend(results)
    status = "PASS" if not failures else f"FAIL ({len(failures)})"
    report.append(f"\nRESULTADO: {status}")
    print("\n".join(report))
    return 0 if not failures else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste transacional e coleta de tempos do inventário (Aula 6)."
    )
    parser.add_argument("--items", type=int, default=10, help="Qtd. de itens no seed.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main(parse_args().items))