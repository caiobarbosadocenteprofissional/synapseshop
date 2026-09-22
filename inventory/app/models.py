"""Modelos ORM (SQLAlchemy 2.0) da camada relacional do inventário (Aula 6).

Modelagem relacional da entidade `inventory_items`:

- **Índices essenciais:** índice único em `sku` (lookup do item por código)
  e índice em `name` (busca/catálogo por nome).
- **Regras de integridade:** `sku`/`name`/`quantity` NOT NULL, `sku` único
  e `CheckConstraint` garantindo `quantity >= 0` (estoque nunca negativo).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0",
            name="ck_inventory_items_quantity_non_negative",
        ),
        Index("ix_inventory_items_sku", "sku", unique=True),
        Index("ix_inventory_items_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryItem id={self.id} sku={self.sku!r} "
            f"quantity={self.quantity}>"
        )