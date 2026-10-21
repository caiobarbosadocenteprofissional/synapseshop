"""Envelope comum e validação estrutural dos eventos (Aulas 9 a 11)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Dict, Tuple

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
