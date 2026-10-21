"""Dataclasses dos eventos de pedido, pagamento e notificação (Aulas 9 a 11)."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List

from events.contratos_base import (
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
    ContratoInvalido,
    _Evento,
    _decimal,
    _envelope_comum,
    _inteiro,
    _texto,
    _texto_do_campo,
    _validar_envelope,
)


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


@dataclass(frozen=True, kw_only=True)
class EventoPedidoCriado(_Evento):
    """Envelope completo do evento ``PedidoCriado``."""

    pedido_id: int
    usuario_id: int
    total: Decimal
    status: str
    itens: List[ItemPedidoCriado] = field(default_factory=list)
    event_type: str = EVENTO_PEDIDO_CRIADO

    _CAMPOS_DADOS = ("pedido_id", "usuario_id", "total", "status", "itens")
    _CAMPOS_TEXTO = ("total",)
    _CAMPOS_LISTA = ("itens",)

    @classmethod
    def from_dict(cls, bruto: Dict[str, Any]) -> "EventoPedidoCriado":
        """Reconstrói e **valida** o evento recebido pelo consumidor."""
        dados = _validar_envelope(bruto, EVENTO_PEDIDO_CRIADO)
        itens = [ItemPedidoCriado.from_dict(i) for i in dados["itens"]]
        if not itens:
            raise ContratoInvalido("pedido sem itens")

        return cls(
            **_envelope_comum(bruto),
            pedido_id=_inteiro(dados, "pedido_id"),
            usuario_id=_inteiro(dados, "usuario_id"),
            total=_decimal(dados, "total"),
            status=str(dados["status"]),
            itens=itens,
        )


@dataclass(frozen=True, kw_only=True)
class EventoPagamentoProcessado(_Evento):
    """Envelope do evento ``PagamentoProcessado`` (Aula 11).

    Os dois desfechos do pagamento — aprovado e recusado — viajam no **mesmo**
    evento, discriminados por ``dados.status``. A alternativa seria um evento
    por desfecho, o que duplicaria tópico, fila, produtor e consumidor para
    distinguir o que cabe em um campo.

    A chave de idempotência é ``pagamento:<id>``, e não a chave do pedido: a
    deduplicação é por ``(evento, idempotency_key)``, então um pagamento e o seu
    pedido são entradas diferentes e não se anulam.
    """

    pagamento_id: int
    pedido_id: int
    usuario_id: int
    valor: Decimal
    status: str
    forma_pagamento: str
    referencia: str
    event_type: str = EVENTO_PAGAMENTO_PROCESSADO

    _CAMPOS_DADOS = (
        "pagamento_id",
        "pedido_id",
        "usuario_id",
        "valor",
        "status",
        "forma_pagamento",
        "referencia",
    )
    _CAMPOS_TEXTO = ("valor",)

    @property
    def aprovado(self) -> bool:
        return self.status == "APROVADO"

    @classmethod
    def from_dict(cls, bruto: Dict[str, Any]) -> "EventoPagamentoProcessado":
        dados = _validar_envelope(bruto, EVENTO_PAGAMENTO_PROCESSADO)
        status = _texto_do_campo(dados, "status").upper()
        if status not in ("APROVADO", "RECUSADO"):
            raise ContratoInvalido(f"status de pagamento desconhecido: {status!r}")

        return cls(
            **_envelope_comum(bruto),
            pagamento_id=_inteiro(dados, "pagamento_id"),
            pedido_id=_inteiro(dados, "pedido_id"),
            usuario_id=_inteiro(dados, "usuario_id"),
            valor=_decimal(dados, "valor"),
            status=status,
            forma_pagamento=_texto_do_campo(dados, "forma_pagamento"),
            referencia=_texto_do_campo(dados, "referencia"),
        )


@dataclass(frozen=True, kw_only=True)
class EventoNotificacaoEnviada(_Evento):
    """Envelope do evento ``NotificacaoEnviada`` (Aula 11).

    Fecha a cadeia ``Pedido ➔ Pagamento ➔ Notificação`` e é publicado **pelo
    worker**, não pela API: é a prova de que o par produtor/consumidor funciona
    nos dois sentidos da arquitetura. O conteúdo da notificação não viaja no
    evento — ele está no banco, e o que o consumidor precisa é da identidade do
    registro e de quem foi avisado.
    """

    notificacao_id: int
    pedido_id: int
    pagamento_id: int
    canal: str
    destinatario: str
    assunto: str
    event_type: str = EVENTO_NOTIFICACAO_ENVIADA

    _CAMPOS_DADOS = (
        "notificacao_id",
        "pedido_id",
        "pagamento_id",
        "canal",
        "destinatario",
        "assunto",
    )

    @classmethod
    def from_dict(cls, bruto: Dict[str, Any]) -> "EventoNotificacaoEnviada":
        dados = _validar_envelope(bruto, EVENTO_NOTIFICACAO_ENVIADA)
        return cls(
            **_envelope_comum(bruto),
            notificacao_id=_inteiro(dados, "notificacao_id"),
            pedido_id=_inteiro(dados, "pedido_id"),
            pagamento_id=_inteiro(dados, "pagamento_id"),
            canal=_texto_do_campo(dados, "canal"),
            destinatario=_texto_do_campo(dados, "destinatario"),
            assunto=_texto_do_campo(dados, "assunto"),
        )