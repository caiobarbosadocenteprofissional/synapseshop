"""create inventory_items

Revision ID: 0001
Revises:
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "quantity", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "quantity >= 0", name="ck_inventory_items_quantity_non_negative"
        ),
    )
    op.create_index("ix_inventory_items_sku", "inventory_items", ["sku"], unique=True)
    op.create_index("ix_inventory_items_name", "inventory_items", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_inventory_items_name", table_name="inventory_items")
    op.drop_index("ix_inventory_items_sku", table_name="inventory_items")
    op.drop_table("inventory_items")