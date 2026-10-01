"""Contrato da mensagem ``PedidoCriado`` (Aula 9).

O contrato é o acordo entre o produtor (API principal) e o consumidor
(``workers.pedido_worker``). Ele é **estrutural**: define os campos obrigatórios
do envelope e do corpo do evento, e valida a mensagem recebida antes de qualquer
efeito no banco.

Envelope (serializado como JSON):

.. code-block:: json

    {
      "event_id": "0f3c...uuid",
      "event_type": "PedidoCriado",
      "version": "1.0",
      "occurred_at": "2026-09-30T14:03:11.512000Z",
      "correlation_id": "b7a1...uuid",
      "idempotency_key": "pedido-2026-0001",
      "dados": { "pedido_id": 1, "usuario_id": 1, "total": "199.98",
                 "status": "PENDENTE", "itens": [
                   {"item_id": 1, "quantidade": 2, "preco_unitario": "99.99"} ] }
    }

Regras de contrato:

- ``event_type`` e ``version`` são discriminantes: o consumidor recusa um evento
  desconhecido ou de versão incompatível em vez de processá-lo pela metade.
- ``idempotency_key`` é a **chave de negócio** da idempotência. É obrigatória,
  tem no máximo 64 caracteres (limite do índice único) e é gerada pelo produtor
  quando o cliente não a fornece.
- Valores monetários viajam como ``str`` — ``float`` no JSON introduz erro de
  arredondamento em valores monetários.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

EVENTO_PEDIDO_CRIADO = "PedidoCriado"
VERSAO_CONTRATO = "1.0"

CAMPOS_OBRIGATORIOS = (
    "event_id",
    "event_type",
    "version",
    "occurred_at",
    "idempotency_key",
    "dados",
)

CAMPOS_OBRIGATORIOS_DADOS = ("pedido_id", "usuario_id", "total", "status", "itens")


class ContratoInvalido(ValueError):
    """Mensagem recebida não respeita o contrato do evento."""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _texto(valor: Any) -> str:
    """Monetário e identificadores como texto, sem float intermediário."""
    if isinstance(valor, Decimal):
        return format(valor, "f")
    return str(valor)


@dataclass(frozen=True)
class ItemPedidoCriado:
    item_id: int
    quantidade: int
    preco_unitario: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "quantidade": self.quantidade,
            "preco_unitario": _texto(self.preco_unitario),
        }

    @classmethod
    def from_dict(cls, bruto: Dict[str, Any]) -> "ItemPedidoCriado":
        faltando = [c for c in ("item_id", "quantidade", "preco_unitario") if c not in bruto]
        if faltando:
            raise ContratoInvalido(f"item do pedido sem campo(s): {', '.join(faltando)}")
        try:
            item = cls(
                item_id=int(bruto["item_id"]),
                quantidade=int(bruto["quantidade"]),
                preco_unitario=Decimal(str(bruto["preco_unitario"])),
            )
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ContratoInvalido(f"item do pedido inválido: {bruto}") from exc
        if item.quantidade < 1:
            raise ContratoInvalido(f"quantidade deve ser >= 1: {item.quantidade}")
        return item


@dataclass(frozen=True)
class EventoPedidoCriado:
    """Envelope completo do evento ``PedidoCriado``."""

    idempotency_key: str
    pedido_id: int
    usuario_id: int
    total: Decimal
    status: str
    itens: List[ItemPedidoCriado] = field(default_factory=list)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = EVENTO_PEDIDO_CRIADO
    version: str = VERSAO_CONTRATO
    occurred_at: str = field(default_factory=_agora)
    correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "version": self.version,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id or self.event_id,
            "idempotency_key": self.idempotency_key,
            "dados": {
                "pedido_id": self.pedido_id,
                "usuario_id": self.usuario_id,
                "total": _texto(self.total),
                "status": self.status,
                "itens": [item.to_dict() for item in self.itens],
            },
        }

    @classmethod
    def from_dict(cls, bruto: Dict[str, Any]) -> "EventoPedidoCriado":
        """Reconstrói e **valida** o evento recebido pelo consumidor."""
        if not isinstance(bruto, dict):
            raise ContratoInvalido("evento deve ser um objeto JSON")

        faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in bruto]
        if faltando:
            raise ContratoInvalido(f"evento sem campo(s) obrigatório(s): {', '.join(faltando)}")

        if bruto["event_type"] != EVENTO_PEDIDO_CRIADO:
            raise ContratoInvalido(f"evento inesperado: {bruto['event_type']!r}")
        if bruto["version"] != VERSAO_CONTRATO:
            raise ContratoInvalido(f"versão de contrato incompatível: {bruto['version']!r}")

        chave = str(bruto["idempotency_key"]).strip()
        if not chave:
            raise ContratoInvalido("idempotency_key vazio")
        if len(chave) > 64:
            raise ContratoInvalido(f"idempotency_key excede 64 caracteres: {len(chave)}")

        dados = bruto["dados"]
        if not isinstance(dados, dict):
            raise ContratoInvalido("campo 'dados' deve ser um objeto JSON")
        faltando = [c for c in CAMPOS_OBRIGATORIOS_DADOS if c not in dados]
        if faltando:
            raise ContratoInvalido(f"'dados' sem campo(s): {', '.join(faltando)}")

        itens = [ItemPedidoCriado.from_dict(i) for i in dados["itens"]]
        if not itens:
            raise ContratoInvalido("pedido sem itens")

        try:
            return cls(
                idempotency_key=chave,
                pedido_id=int(dados["pedido_id"]),
                usuario_id=int(dados["usuario_id"]),
                total=Decimal(str(dados["total"])),
                status=str(dados["status"]),
                itens=itens,
                event_id=str(bruto["event_id"]),
                occurred_at=str(bruto["occurred_at"]),
                correlation_id=str(bruto.get("correlation_id") or bruto["event_id"]),
            )
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ContratoInvalido(f"dados do evento inválidos: {dados}") from exc