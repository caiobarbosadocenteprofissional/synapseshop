"""Serviço de negócio do inventário (Aula 6).

Consome o repositório transacional e concentra as regras de domínio:
unicidade do `sku` e a impossibilidade de estoque negativo. As regras
validadas aqui complementam a integridade garantida pelo banco
(índice único e `CheckConstraint`).
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import InventoryItem
from app.repository import InventoryRepository
from app.schemas import InventoryItemCreate, InventoryItemUpdate


class DuplicateSkuError(ValueError):
    """Regra de domínio: o `sku` deve ser único."""


class InsufficientStockError(ValueError):
    """Regra de domínio: o estoque não pode ficar negativo."""


class InventoryService:
    """Orquestra operações transacionais usando o repositório."""

    def __init__(self, session: Session) -> None:
        self._repository = InventoryRepository(session)

    def list_items(self) -> List[InventoryItem]:
        return self._repository.list_items()

    def get_item(self, item_id: int) -> Optional[InventoryItem]:
        return self._repository.get_item(item_id)

    def create_item(self, payload: InventoryItemCreate) -> InventoryItem:
        if self._repository.get_item_by_sku(payload.sku) is not None:
            raise DuplicateSkuError(f"SKU já cadastrado: {payload.sku}")
        return self._repository.create_item(
            sku=payload.sku, name=payload.name, quantity=payload.quantity
        )

    def update_item(
        self, item_id: int, payload: InventoryItemUpdate
    ) -> Optional[InventoryItem]:
        changes = payload.model_dump(exclude_unset=True)
        if "sku" in changes:
            existing = self._repository.get_item_by_sku(changes["sku"])
            if existing is not None and existing.id != item_id:
                raise DuplicateSkuError(f"SKU já cadastrado: {changes['sku']}")
        return self._repository.update_item(item_id, **changes)

    def adjust_stock(self, item_id: int, delta: int) -> Optional[InventoryItem]:
        """Transação de ajuste de estoque com regra de domínio.

        `delta` positivo representa uma entrada e negativo uma saída.
        A regra `quantity >= 0` é verificada antes da persistência; em
        falha, nada é gravado (a transação é abortada).
        """
        item = self._repository.get_item(item_id)
        if item is None:
            return None
        new_quantity = item.quantity + delta
        if new_quantity < 0:
            raise InsufficientStockError(
                f"Estoque insuficiente: {item.quantity} + ({delta}) < 0"
            )
        return self._repository.update_item(
            item_id, quantity=new_quantity
        )

    def delete_item(self, item_id: int) -> bool:
        return self._repository.delete_item(item_id)