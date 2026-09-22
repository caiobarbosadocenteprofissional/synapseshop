"""Repositório transacional dos itens de estoque (Aula 6).

Camada de persistência sobre o PostgreSQL via SQLAlchemy 2.0. Cada
operação de escrita é concluída com `commit`; se uma regra de integridade
relacional for violada (ex.: `sku` duplicado ou `quantity < 0`), a
transação sofre `rollback` e a exceção `IntegrityError` é repassada — o
que garante que nunca restem escritas parciais no banco.
"""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import InventoryItem


class InventoryRepository:
    """Abstrai o acesso transacional à tabela `inventory_items`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_items(self) -> List[InventoryItem]:
        stmt = select(InventoryItem).order_by(InventoryItem.id)
        return list(self._session.scalars(stmt).all())

    def get_item(self, item_id: int) -> Optional[InventoryItem]:
        return self._session.get(InventoryItem, item_id)

    def get_item_by_sku(self, sku: str) -> Optional[InventoryItem]:
        stmt = select(InventoryItem).where(InventoryItem.sku == sku)
        return self._session.scalars(stmt).first()

    def create_item(self, sku: str, name: str, quantity: int) -> InventoryItem:
        item = InventoryItem(sku=sku, name=name, quantity=quantity)
        self._session.add(item)
        self._commit()
        self._session.refresh(item)
        return item

    def update_item(
        self, item_id: int, **changes: Any
    ) -> Optional[InventoryItem]:
        item = self.get_item(item_id)
        if item is None:
            return None
        for field, value in changes.items():
            setattr(item, field, value)
        self._commit()
        self._session.refresh(item)
        return item

    def delete_item(self, item_id: int) -> bool:
        item = self.get_item(item_id)
        if item is None:
            return False
        self._session.delete(item)
        self._commit()
        return True

    def _commit(self) -> None:
        """Commit atômico: em falha de integridade, reverte a transação."""
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise