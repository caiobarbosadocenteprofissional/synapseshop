"""Contratos das mensagens do fluxo de pedidos (Aulas 9 a 11).

O contrato é o acordo entre quem publica e quem consome. Ele é **estrutural**:
define os campos obrigatórios do envelope e do corpo de cada evento, e valida a
mensagem recebida antes de qualquer efeito no banco.

A Aula 11 acrescenta os dois eventos que completam o fluxo — pagamento e
notificação — sem duplicar o envelope. O que é comum a todos (discriminantes,
``idempotency_key``, validação) vive em ``_serializar_envelope`` e
``_validar_envelope``; o que é próprio de cada evento fica no dataclass.

Envelope comum (serializado como JSON):

.. code-block:: json

    {
      "event_id": "0f3c...uuid",
      "event_type": "PedidoCriado",
      "version": "1.0",
      "occurred_at": "2026-09-30T14:03:11.512000Z",
      "correlation_id": "b7a1...uuid",
      "idempotency_key": "pedido-2026-0001",
      "dados": { ... }
    }

Regras de contrato:

- ``event_type`` e ``version`` são discriminantes: o consumidor recusa um evento
  desconhecido ou de versão incompatível em vez de processá-lo pela metade.
- ``idempotency_key`` é a **chave de negócio** da idempotência. É obrigatória,
  tem no máximo 64 caracteres (limite do índice único) e é gerada pelo produtor
  quando o cliente não a fornece.
- Valores monetários viajam como ``str`` — ``float`` no JSON introduz erro de
  arredondamento em valores monetários.
- ``correlation_id`` atravessa a cadeia inteira (criação ➔ pagamento ➔
  notificação), então os logs dos três processos podem ser lidos como um só.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Dict, List, Tuple

EVENTO_PEDIDO_CRIADO = "PedidoCriado"
EVENTO_PAGAMENTO_PROCESSADO = "PagamentoProcessado"
EVENTO_NOTIFICACAO_ENVIADA = "NotificacaoEnviada"
VERSAO_CONTRATO = "1.0"

CAMPOS_OBRIGATORIOS = (
    "event_id",
    "event_type",
    "version",
    "occurred_at",
    "idempotency_key",
    "dados",
)

CAMPOS_OBRIGATORIOS_DADOS: Dict[str, Tuple[str, ...]] = {
    EVENTO_PEDIDO_CRIADO: ("pedido_id", "usuario_id", "total", "status", "itens"),
    EVENTO_PAGAMENTO_PROCESSADO: (
        "pagamento_id",
        "pedido_id",
        "usuario_id",
        "valor",
        "status",
        "forma_pagamento",
        "referencia",
    ),
    EVENTO_NOTIFICACAO_ENVIADA: (
        "notificacao_id",
        "pedido_id",
        "pagamento_id",
        "canal",
        "destinatario",
        "assunto",
    ),
}

MAX_CARACTERES_CHAVE = 64


class ContratoInvalido(ValueError):
    """Mensagem recebida não respeita o contrato do evento."""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _texto(valor: Any) -> str:
    """Monetário e identificadores como texto, sem float intermediário."""
    if isinstance(valor, Decimal):
        return format(valor, "f")
    return str(valor)


def _serializar_envelope(
    *,
    tipo: str,
    chave: str,
    dados: Dict[str, Any],
    event_id: str,
    occurred_at: str,
    correlation_id: str,
) -> Dict[str, Any]:
    """Monta o envelope comum. ``correlation_id`` cai no ``event_id`` se vazio."""
    return {
        "event_id": event_id,
        "event_type": tipo,
        "version": VERSAO_CONTRATO,
        "occurred_at": occurred_at,
        "correlation_id": correlation_id or event_id,
        "idempotency_key": chave,
        "dados": dados,
    }


def _validar_envelope(bruto: Any, tipo_esperado: str) -> Dict[str, Any]:
    """Valida o envelope e devolve o dicionário ``dados`` já conferido.

    Tudo que é comum aos três eventos é conferido aqui, e sempre **antes** de o
    consumidor tocar no banco: um evento de tipo errado, de outra versão ou sem
    campo obrigatório não chega a ser aplicado.
    """
    if not isinstance(bruto, dict):
        raise ContratoInvalido("evento deve ser um objeto JSON")

    faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in bruto]
    if faltando:
        raise ContratoInvalido(f"evento sem campo(s) obrigatório(s): {', '.join(faltando)}")

    if bruto["event_type"] != tipo_esperado:
        raise ContratoInvalido(f"evento inesperado: {bruto['event_type']!r}")
    if bruto["version"] != VERSAO_CONTRATO:
        raise ContratoInvalido(f"versão de contrato incompatível: {bruto['version']!r}")

    chave = str(bruto["idempotency_key"]).strip()
    if not chave:
        raise ContratoInvalido("idempotency_key vazio")
    if len(chave) > MAX_CARACTERES_CHAVE:
        raise ContratoInvalido(f"idempotency_key excede {MAX_CARACTERES_CHAVE} caracteres: {len(chave)}")

    dados = bruto["dados"]
    if not isinstance(dados, dict):
        raise ContratoInvalido("campo 'dados' deve ser um objeto JSON")
    faltando = [c for c in CAMPOS_OBRIGATORIOS_DADOS[tipo_esperado] if c not in dados]
    if faltando:
        raise ContratoInvalido(f"'dados' sem campo(s): {', '.join(faltando)}")
    return dados


def _inteiro(dados: Dict[str, Any], campo: str) -> int:
    try:
        return int(dados[campo])
    except (TypeError, ValueError) as exc:
        raise ContratoInvalido(f"campo '{campo}' inválido: {dados[campo]!r}") from exc


def _decimal(dados: Dict[str, Any], campo: str) -> Decimal:
    try:
        return Decimal(str(dados[campo]))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ContratoInvalido(f"campo '{campo}' inválido: {dados[campo]!r}") from exc


def _texto_do_campo(dados: Dict[str, Any], campo: str) -> str:
    valor = str(dados[campo]).strip()
    if not valor:
        raise ContratoInvalido(f"campo '{campo}' vazio")
    return valor


def _envelope_comum(bruto: Dict[str, Any]) -> Dict[str, Any]:
    """Campos do envelope que todo ``from_dict`` devolve para o construtor."""
    return {
        "idempotency_key": str(bruto["idempotency_key"]).strip(),
        "event_id": str(bruto["event_id"]),
        "occurred_at": str(bruto["occurred_at"]),
        "correlation_id": str(bruto.get("correlation_id") or bruto["event_id"]),
    }


@dataclass(frozen=True, kw_only=True)
class _Evento:
    """Envelope comum: campos fixos e serialização dirigida por ``_CAMPOS_DADOS``."""

    idempotency_key: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    version: str = VERSAO_CONTRATO
    occurred_at: str = field(default_factory=_agora)
    correlation_id: str = ""

    _CAMPOS_DADOS: ClassVar[Tuple[str, ...]] = ()
    _CAMPOS_TEXTO: ClassVar[Tuple[str, ...]] = ()
    _CAMPOS_LISTA: ClassVar[Tuple[str, ...]] = ()

    def to_dict(self) -> Dict[str, Any]:
        dados: Dict[str, Any] = {}
        for campo in self._CAMPOS_DADOS:
            valor = getattr(self, campo)
            if campo in self._CAMPOS_TEXTO:
                valor = _texto(valor)
            elif campo in self._CAMPOS_LISTA:
                valor = [item.to_dict() for item in valor]
            dados[campo] = valor
        return _serializar_envelope(
            tipo=self.event_type,
            chave=self.idempotency_key,
            dados=dados,
            event_id=self.event_id,
            occurred_at=self.occurred_at,
            correlation_id=self.correlation_id,
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