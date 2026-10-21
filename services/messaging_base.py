"""Peças compartilhadas pelos transportes AMQP e Kafka.

Os dois transportes têm o mesmo contrato de domínio — publicar um dicionário
JSON, consumir com pelo menos uma vez, reentregar com recuo exponencial e matar
para a DLQ — mas falam protocolos diferentes. Tudo que não depende do protocolo
mora aqui: o log estruturado, os nomes dos headers de controle, o cálculo do
recuo, a leitura do contador de tentativas, que chega como ``dict`` no AMQP e
como lista de pares no Kafka, e a **política de reentrega**.

Manter esses detalhes num só lugar garante que a política de reentrega não
divirja entre os brokers; o que é específico de cada um (conexão, topologia,
ack/commit) permanece no módulo do transporte.

A política de consumo é expressa como uma função que recebe do transporte as
três operações de protocolo — republicar, confirmar e matar. É o inverso da
duplicação que existia antes: as duas árvores de decisão eram idênticas e
estavam copiadas, uma por arquivo; agora há **uma** árvore, e cada transporte
se limita a dizer como cada operação acontece no seu protocolo.
"""

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from django.conf import settings

from services.log_estruturado import LoggerEstruturado

logger = logging.getLogger("synapseshop.mensageria")
log = LoggerEstruturado(logger)

HEADER_TENTATIVA = "x-retry-count"
HEADER_ERRO = "x-ultimo-erro"


class MensageriaIndisponivel(RuntimeError):
    """O broker não pôde ser alcançado ou recusou a publicação."""


@dataclass(frozen=True)
class ResultadoPublicacao:
    """Desfecho de uma publicação, normalizado entre os transportes.

    O AMQP devolve o ``correlation_id`` da entrega e o Kafka devolve
    ``(particao, offset)``. Quem publica precisa saber se a mensagem **entrou**,
    não em que formato o broker conta isso — por isso o desfecho é o mesmo nos
    dois, e o identificador bruto do broker vai em ``identificador``.
    """

    confirmado: bool
    identificador: str = ""
    particao: Optional[int] = None
    offset: Optional[int] = None


class ProdutorEventoProtocol(Protocol):
    """Superfície do produtor, idêntica nos dois transportes."""

    def conectar(self) -> None:
        """Abre a conexão com o broker."""

    def fechar(self) -> None:
        """Fecha a conexão com o broker (best effort)."""

    def publicar(self, evento: Dict[str, Any], idempotency_key: str) -> ResultadoPublicacao:
        """Publica o evento e devolve o desfecho normalizado."""

    def __enter__(self) -> "ProdutorEventoProtocol":
        """Uso como gerenciador de contexto."""

    def __exit__(self, *_excecao) -> None:
        """Fecha a conexão ao sair do gerenciador de contexto."""


class ConsumidorEventoProtocol(Protocol):
    """Superfície do consumidor, idêntica nos dois transportes."""

    @property
    def topologia(self) -> Any:
        """Topologia do evento consumido."""

    def executar(self) -> None:
        """Consome em laço até ``parar()`` ou o broker cair."""

    def parar(self) -> None:
        """Pede a parada do laço de consumo."""


# A política de consumo é genérica sobre o protocolo: o transporte entrega as
# três operações e o corpo decide o que fazer com elas.
Republicar = Callable[[bytes, Optional[Dict[str, Any]], Dict[str, Any]], Optional[str]]
"""Republica o corpo com headers novos.

Devolve ``None`` quando o broker confirmou a republicação e a descrição do
problema quando não confirmou — nesse caso a mensagem original **não** é
confirmada, e volta a ser entregue em vez de ser perdida.
"""

Confirmar = Callable[[], None]
"""Confirma a entrega original (``ack`` no AMQP, ``commit`` no Kafka)."""

Matar = Callable[[bytes, Optional[Dict[str, Any]], Dict[str, Any], str], bool]
"""Mata a mensagem para a DLQ. Devolve ``True`` quando a morte foi confirmada."""

Campos = Callable[[], Dict[str, Any]]
"""Campos de log que só o transporte conhece (partição, offset, correlação)."""


def _duracao_ms(inicio: float) -> float:
    """Duração desde ``inicio`` (``perf_counter``), em milissegundos."""
    return round((time.perf_counter() - inicio) * 1000, 3)


def esperar_reentrega(tentativa: int) -> float:
    """Recuo exponencial limitado por ``MENSAGERIA_BACKOFF_MAX_MS``."""
    atraso_ms = min(
        settings.MENSAGERIA_BACKOFF_BASE_MS * (2 ** (tentativa - 1)),
        settings.MENSAGERIA_BACKOFF_MAX_MS,
    )
    return atraso_ms / 1000.0


def ler_tentativa(cabecalhos) -> int:
    """Lê ``x-retry-count`` de headers AMQP (mapa) ou Kafka (lista de pares)."""
    if not cabecalhos:
        return 0
    pares = cabecalhos.items() if isinstance(cabecalhos, Mapping) else cabecalhos
    for nome, valor in pares:
        if nome != HEADER_TENTATIVA:
            continue
        if isinstance(valor, bytes):
            valor = valor.decode("utf-8", "replace")
        try:
            return int(valor or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def serializar_evento(evento: Dict[str, Any]) -> bytes:
    """Serializa o envelope em JSON UTF-8, preservando acentos."""
    return json.dumps(evento, ensure_ascii=False).encode("utf-8")


def processar_evento(
    *,
    corpo: bytes,
    tentativa: int,
    handler: Callable[[Dict[str, Any], int], None],
    republicar: Republicar,
    confirmar: Confirmar,
    matar: Matar,
    campos: Campos,
    destino_dlq: str,
) -> None:
    """Aplica o handler e decide entre reentregar e matar para a DLQ.

    A ordem é o que dá segurança ao *at-least-once*: o efeito é aplicado
    **antes** da confirmação, e a confirmação só acontece depois que a
    reentrega foi aceita pelo broker. Uma republicação que o broker não
    confirma deixa a mensagem original onde ela estava — ela volta a ser
    entregue em vez de ser perdida.
    """
    inicio = time.perf_counter()
    try:
        evento = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        # Corpo ilegível não tem como ser reprocessado: vai direto para a DLQ.
        _matar_para_dlq(
            corpo=corpo,
            evento=None,
            erro=f"corpo invalido: {exc}",
            tentativa=tentativa,
            matar=matar,
            campos=campos,
            destino_dlq=destino_dlq,
            inicio=inicio,
        )
        return

    chave = evento.get("idempotency_key") if isinstance(evento, dict) else None
    try:
        handler(evento, tentativa)
    except Exception as exc:  # noqa: BLE001 - política de falha do consumidor
        _reentregar_ou_matar(
            corpo=corpo,
            evento=evento,
            chave=chave,
            erro=str(exc),
            tentativa=tentativa,
            republicar=republicar,
            confirmar=confirmar,
            matar=matar,
            campos=campos,
            destino_dlq=destino_dlq,
            inicio=inicio,
        )
        return

    confirmar()
    log(
        "mensageria.consumido",
        **{
            **campos(),
            "idempotency_key": chave,
            "tentativa": tentativa,
            "resultado": "ok",
            "duracao_ms": _duracao_ms(inicio),
        },
    )


def _reentregar_ou_matar(
    *,
    corpo: bytes,
    evento: Optional[Dict[str, Any]],
    chave: Optional[str],
    erro: str,
    tentativa: int,
    republicar: Republicar,
    confirmar: Confirmar,
    matar: Matar,
    campos: Campos,
    destino_dlq: str,
    inicio: float,
) -> None:
    """Republica com tentativa+1 e recuo exponencial, ou mata para a DLQ."""
    if tentativa >= settings.MENSAGERIA_MAX_RETRIES:
        _matar_para_dlq(
            corpo=corpo,
            evento=evento,
            erro=erro,
            tentativa=tentativa,
            matar=matar,
            campos=campos,
            destino_dlq=destino_dlq,
            inicio=inicio,
        )
        return

    proxima = tentativa + 1
    espera = esperar_reentrega(proxima)
    falha = republicar(
        corpo,
        evento,
        {HEADER_TENTATIVA: proxima, HEADER_ERRO: erro[:500]},
    )
    time.sleep(espera)
    if falha is not None:
        # Sem confirmar a republicação, a original não é confirmada: ela volta
        # a ser entregue em vez de ser perdida. O transporte já a deixou onde
        # tinha de ficar (reenfileirada no AMQP, offset não commitado no Kafka).
        log(
            "mensageria.reentrega.falhou",
            **{
                **campos(),
                "idempotency_key": chave,
                "tentativa": tentativa,
                "erro": falha,
                "duracao_ms": _duracao_ms(inicio),
            },
        )
        return

    confirmar()
    log(
        "mensageria.reentrega",
        **{
            **campos(),
            "idempotency_key": chave,
            "tentativa": tentativa,
            "proxima_tentativa": proxima,
            "espera_ms": round(espera * 1000, 3),
            "erro": erro[:500],
            "duracao_ms": _duracao_ms(inicio),
        },
    )


def _matar_para_dlq(
    *,
    corpo: bytes,
    evento: Optional[Dict[str, Any]],
    erro: str,
    tentativa: int,
    matar: Matar,
    campos: Campos,
    destino_dlq: str,
    inicio: float,
) -> None:
    """Esgotou as tentativas (ou o corpo é ilegível): manda para a DLQ."""
    cabecalhos = {HEADER_TENTATIVA: tentativa, HEADER_ERRO: str(erro)[:500]}
    if not matar(corpo, evento, cabecalhos, str(erro)):
        # A mensagem não chegou à DLQ: ela não é confirmada e volta a ser
        # entregue, para que a morte não vire perda.
        log(
            "mensageria.dlq.falhou",
            **{
                **campos(),
                "tentativa": tentativa,
                "erro": "broker nao confirmou a publicacao na DLQ; original nao confirmada",
                "duracao_ms": _duracao_ms(inicio),
            },
        )
        return

    log(
        "mensageria.dlq",
        **{
            **campos(),
            "idempotency_key": evento.get("idempotency_key") if isinstance(evento, dict) else None,
            "tentativa": tentativa,
            "dlq": destino_dlq,
            "erro": str(erro)[:500],
            "duracao_ms": _duracao_ms(inicio),
        },
    )


__all__ = [
    "Campos",
    "Confirmar",
    "ConsumidorEventoProtocol",
    "HEADER_ERRO",
    "HEADER_TENTATIVA",
    "Matar",
    "MensageriaIndisponivel",
    "ProdutorEventoProtocol",
    "Republicar",
    "ResultadoPublicacao",
    "esperar_reentrega",
    "ler_tentativa",
    "processar_evento",
    "serializar_evento",
]
