"""Rotas mínimas obrigatórias do microsserviço de inventário.

CRUD de itens de estoque sob o prefixo `/inventory/items`, com tipagem
estática (`response_model`), validação via modelos Pydantic e respostas
padrão (201 Created, 200 OK, 204 No Content, 404 Not Found). Desde a
Aula 6 as rotas consomem o serviço transacional (`InventoryService`)
sobre o PostgreSQL via SQLAlchemy.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    InventoryItem,
    InventoryItemCreate,
    InventoryItemUpdate,
    StockAdjustRequest,
)
from app.services import (
    DuplicateSkuError,
    InsufficientStockError,
    InventoryService,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


def get_service(session: Session = Depends(get_session)) -> InventoryService:
    return InventoryService(session)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado."
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.get(
    "/items",
    response_model=List[InventoryItem],
    status_code=status.HTTP_200_OK,
    summary="Lista todos os itens de estoque",
)
def list_items(service: InventoryService = Depends(get_service)) -> List[InventoryItem]:
    return service.list_items()


@router.post(
    "/items",
    response_model=InventoryItem,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um novo item de estoque",
    responses={status.HTTP_409_CONFLICT: {"description": "SKU já cadastrado."}},
)
def create_item(
    payload: InventoryItemCreate, service: InventoryService = Depends(get_service)
) -> InventoryItem:
    try:
        return service.create_item(payload)
    except DuplicateSkuError as exc:
        raise _conflict(str(exc)) from exc
    except IntegrityError:
        raise _conflict("SKU já cadastrado.") from None


@router.get(
    "/items/{item_id}",
    response_model=InventoryItem,
    status_code=status.HTTP_200_OK,
    summary="Detalha um item de estoque",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Item não encontrado."}},
)
def get_item(item_id: int, service: InventoryService = Depends(get_service)) -> InventoryItem:
    item = service.get_item(item_id)
    if item is None:
        raise _not_found()
    return item


@router.patch(
    "/items/{item_id}",
    response_model=InventoryItem,
    status_code=status.HTTP_200_OK,
    summary="Atualiza parcialmente um item de estoque",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Item não encontrado."}},
)
def update_item(
    item_id: int,
    payload: InventoryItemUpdate,
    service: InventoryService = Depends(get_service),
) -> InventoryItem:
    try:
        item = service.update_item(item_id, payload)
    except DuplicateSkuError as exc:
        raise _conflict(str(exc)) from exc
    if item is None:
        raise _not_found()
    return item


@router.patch(
    "/items/{item_id}/stock",
    response_model=InventoryItem,
    status_code=status.HTTP_200_OK,
    summary="Ajusta o estoque de um item (transação)",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Item não encontrado."},
        status.HTTP_409_CONFLICT: {"description": "Estoque não pode ficar negativo."},
    },
)
def adjust_stock(
    item_id: int,
    payload: StockAdjustRequest,
    service: InventoryService = Depends(get_service),
) -> InventoryItem:
    try:
        item = service.adjust_stock(item_id, payload.delta)
    except InsufficientStockError as exc:
        raise _conflict(str(exc)) from exc
    if item is None:
        raise _not_found()
    return item


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um item de estoque",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Item não encontrado."}},
)
def delete_item(item_id: int, service: InventoryService = Depends(get_service)) -> None:
    if not service.delete_item(item_id):
        raise _not_found()