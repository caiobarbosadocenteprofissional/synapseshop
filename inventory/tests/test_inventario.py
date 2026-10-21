"""Testes do microsserviço de inventário (Aulas 5 e 6).

O foco é o **contrato** do serviço: o que a API de inventário aceita na
entrada, o que devolve na saída e o que o banco garante. Dois defeitos
clássicos moram aqui e nenhum dos dois é visível pelo contrato OpenAPI:

- ``quantity`` era declarado como ``int`` com default ``None`` — o tipo
  mentia, e um ``null`` no corpo do PATCH acabava como ``NULL`` numa coluna
  ``NOT NULL``;
- a resposta omitia ``updated_at``, campo que o modelo mantém e o cliente
  precisa para saber a versão do registro.

A camada de repositório também ganhou uma whitelist de campos atualizáveis:
``update_item(**changes)`` sem whitelist transforma qualquer chave em coluna.
"""

import pytest

from app.models import InventoryItem
from app.repository import CAMPOS_ATUALIZAVEIS, InventoryRepository
from app.schemas import InventoryItemCreate, InventoryItemUpdate
from app.services import DuplicateSkuError, InsufficientStockError, InventoryService

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Schemas — o contrato de entrada e de saída
# --------------------------------------------------------------------------


def test_update_aceita_quantity_nulo():
    """``null`` é uma atualização válida: significa "não alterar"."""
    payload = InventoryItemUpdate(quantity=None)
    assert payload.quantity is None


def test_update_rejeita_quantity_negativo():
    with pytest.raises(ValueError):
        InventoryItemUpdate(quantity=-1)


def test_resposta_traz_updated_at(item_criado):
    """O modelo mantém ``updated_at``; a resposta precisa devolvê-lo."""
    assert item_criado.updated_at is not None


def test_resposta_serializa_updated_at(servico, item_criado):
    from app.schemas import InventoryItem

    resposta = InventoryItem.model_validate(item_criado)
    assert resposta.updated_at == item_criado.updated_at


# --------------------------------------------------------------------------
# Serviço — as regras de domínio
# --------------------------------------------------------------------------


def test_update_com_null_nao_altera_o_estoque(servico, item_criado):
    """O defeito que motivou a correção: ``null`` virava ``NULL`` no banco."""
    atualizado = servico.update_item(item_criado.id, InventoryItemUpdate(quantity=None))

    assert atualizado is not None
    assert atualizado.quantity == 10


def test_update_com_null_em_varios_campos_nao_altera_nada(servico, item_criado):
    atualizado = servico.update_item(
        item_criado.id,
        InventoryItemUpdate(sku=None, name=None, quantity=None),
    )

    assert atualizado is not None
    assert atualizado.sku == "SKU-001"
    assert atualizado.name == "Teclado"
    assert atualizado.quantity == 10


def test_update_altera_campos_preenchidos(servico, item_criado):
    atualizado = servico.update_item(
        item_criado.id, InventoryItemUpdate(name="Mouse", quantity=3)
    )

    assert atualizado is not None
    assert atualizado.name == "Mouse"
    assert atualizado.quantity == 3


def test_update_de_item_inexistente_devolve_none(servico):
    assert servico.update_item(999, InventoryItemUpdate(name="X")) is None


def test_sku_duplicado_e_rejeitado(servico, item_criado):
    with pytest.raises(DuplicateSkuError):
        servico.create_item(
            InventoryItemCreate(sku="SKU-001", name="Outro", quantity=1)
        )


def test_estoque_insuficiente_e_rejeitado(servico, item_criado):
    with pytest.raises(InsufficientStockError):
        servico.adjust_stock(item_criado.id, -100)


def test_ajuste_de_estoque_e_transacional(servico, item_criado):
    atualizado = servico.adjust_stock(item_criado.id, -4)

    assert atualizado is not None
    assert atualizado.quantity == 6


# --------------------------------------------------------------------------
# Repositório — a whitelist de campos
# --------------------------------------------------------------------------


def test_repositorio_ignora_campo_fora_da_whitelist(sessao, item_criado):
    """Uma chave desconhecida não pode virar coluna."""
    repositorio = InventoryRepository(sessao)
    atualizado = repositorio.update_item(item_criado.id, id=999, name="Mouse")

    assert atualizado is not None
    assert atualizado.id == item_criado.id
    assert atualizado.name == "Mouse"


def test_repositorio_ignora_none(sessao, item_criado):
    repositorio = InventoryRepository(sessao)
    atualizado = repositorio.update_item(item_criado.id, quantity=None)

    assert atualizado is not None
    assert atualizado.quantity == 10


def test_whitelist_cobre_os_campos_negociais():
    assert set(CAMPOS_ATUALIZAVEIS) == {"sku", "name", "quantity"}


def test_item_do_modelo_nao_aceita_estoque_negativo(sessao, item_criado):
    """A regra do banco (``CheckConstraint``) é a última linha de defesa."""
    import sqlalchemy

    item_criado.quantity = -5
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        sessao.commit()
    sessao.rollback()


def test_sku_e_unico_no_banco(sessao, item_criado):
    import sqlalchemy

    sessao.add(InventoryItem(sku="SKU-001", name="Duplicado", quantity=1))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        sessao.commit()
    sessao.rollback()


def test_servico_exposto_com_a_sessao_do_teste(sessao, item_criado):
    """O serviço é a única porta de entrada do domínio."""
    assert isinstance(InventoryService(sessao), InventoryService)
