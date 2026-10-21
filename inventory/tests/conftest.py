"""Preparo do ambiente de teste do microsserviço de inventário.

O inventário é um deployável **separado**: tem dependências próprias
(``inventory/requirements.txt``) e a suíte principal do Django a exclui
(``norecursedirs`` em ``pytest.ini``). Por isso ele tem a sua própria suíte,
executada com o mesmo comando de dentro do container do serviço:

.. code-block:: console

    pytest inventory/tests

O ``sys.path`` é ajustado para que ``app`` seja importável — é assim que o
serviço roda, com ``inventory/`` como raiz — e o banco é um SQLite em memória
para que o teste não dependa do PostgreSQL do Compose.
"""

import os
import sys
from pathlib import Path

RAIZ_INVENTARIO = Path(__file__).resolve().parent.parent
if str(RAIZ_INVENTARIO) not in sys.path:
    sys.path.insert(0, str(RAIZ_INVENTARIO))

# `app.db` monta o engine no import. Apontar para o SQLite garante que a
# suíte não exige o PostgreSQL do Compose apenas para importar o módulo.
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402
from app.schemas import InventoryItemCreate  # noqa: E402


@pytest.fixture
def sessao():
    """Sessão SQLAlchemy sobre um banco em memória, com o schema criado."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with fabrica() as sessao_sqlalchemy:
        yield sessao_sqlalchemy
    engine.dispose()


@pytest.fixture
def servico(sessao):
    """Serviço de inventário sobre a sessão do teste."""
    from app.services import InventoryService

    return InventoryService(sessao)


@pytest.fixture
def item_criado(servico):
    """Um item de estoque criado e pronto para uso."""
    return servico.create_item(
        InventoryItemCreate(sku="SKU-001", name="Teclado", quantity=10)
    )
