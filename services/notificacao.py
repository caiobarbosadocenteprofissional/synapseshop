"""Notificação ao cliente após o pagamento (Aula 11).

É o lado **consumidor** do segundo elo do fluxo: o ``notificacao-worker`` recebe
``PagamentoProcessado``, grava a ``Notificacao`` quando o pagamento foi aprovado e
publica ``NotificacaoEnviada`` — fechando ``Pedido ➔ Pagamento ➔ Notificação``.

O envio é **simulado**: o que se prova é a etapa da cadeia, não a entrega de uma
mensagem real ao cliente. A linha gravada no banco é a evidência de que o evento
foi consumido, e ``GET /api/v1/notificacoes/`` é a forma de observá-la por fora.

Duas decisões que valem registro:

1. **Pagamento recusado não notifica.** Um cliente cujo pagamento foi recusado
   recebe a confirmação da recusa no ``GET`` do pedido, e não uma notificação de
   "seu pagamento foi aprovado". Notificar o desfecho negativo é decisão de produto
   de cada sistema; aqui o comportamento simulado é o Recusa ➔ nenhum registro, e
   o log registra explicitamente a decisão para que a ausência não pareça perda de
   mensagem.
2. **A notificação é gravada uma vez só.** Além da chave de deduplicação do
   evento (``Notificacao.evento_origem`` com índice único), a gravação acontece
   dentro da mesma transação que consulta a chave de deduplicação — a reentrega
   encontra o registro já existente e o efeito é o mesmo de sempre.
"""

import json
import logging
import time
from typing import Any, Dict, Tuple

from django.db import IntegrityError, transaction

from events.contracts import EventoNotificacaoEnviada, EventoPagamentoProcessado
from events.topology import chave_de, topologia_de
from repositories.models import Notificacao, Pagamento, Pedido
from services import idempotencia
from services.events import NOTIFICACAO_REGISTRADA, emitir_apos_commit
from services.publicacao import publicar_evento

logger = logging.getLogger("synapseshop.notificacao")


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `event_type` e a colisão seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


class PagamentoInexistente(RuntimeError):
    """O evento aponta para um pagamento que não está no repositório."""


def _destinatario(usuario) -> str:
    """Endereço de destino da notificação.

    O e-mail é preferível quando existe porque é o canal que o usuário enxerga em
    ``GET /api/v1/notificacoes/``; sem e-mail, o identificador do usuário ainda
    identifica o destinatário de um canal simulado.
    """
    return usuario.email or f"usuario-{usuario.pk}@sem-email.invalido"


def _mensagem(pedido: Pedido, pagamento: Pagamento) -> Tuple[str, str]:
    """Assunto e corpo da notificação, derivados do pedido e do pagamento."""
    return (
        f"Pedido #{pedido.pk} confirmado",
        (
            f"Olá! O pagamento do pedido #{pedido.pk} foi aprovado "
            f"({pagamento.referencia}). Total pago: R$ {pagamento.valor}. "
            f"O pedido está pronto para o próximo passo."
        ),
    )


def evento_notificacao_enviada(notificacao: Notificacao) -> EventoNotificacaoEnviada:
    """Monta o evento ``NotificacaoEnviada`` da notificação gravada."""
    return EventoNotificacaoEnviada(
        idempotency_key=chave_de(notificacao.pk, "notificacao"),
        notificacao_id=notificacao.pk,
        pedido_id=notificacao.pedido_id,
        pagamento_id=notificacao.pagamento_id,
        canal=notificacao.canal,
        destinatario=notificacao.destinatario,
        assunto=notificacao.assunto,
        correlation_id=notificacao.pedido.correlation_id or "",
    )


def publicar_notificacao_enviada(notificacao: Notificacao) -> bool:
    """Publica o evento. ``False`` quando o broker não aceitou."""
    evento = evento_notificacao_enviada(notificacao)
    return publicar_evento(
        evento=evento.to_dict(),
        idempotency_key=evento.idempotency_key,
        topologia=topologia_de(evento.event_type),
        prefixo_log="notificacao",
        client_id="synapseshop-notificacao-worker",
        extra={
            "notificacao_id": notificacao.pk,
            "pedido_id": notificacao.pedido_id,
            "correlation_id": evento.correlation_id or None,
        },
    )


def _registrar(
    evento: EventoPagamentoProcessado, pagamento: Pagamento, pedido: Pedido
) -> Notificacao:
    """Grava a notificação do pagamento aprovado. Idempotente por construção."""
    existente = Notificacao.objects.filter(evento_origem=evento.event_id).first()
    if existente is not None:
        return existente

    assunto, conteudo = _mensagem(pedido, pagamento)
    try:
        with transaction.atomic():
            notificacao = Notificacao.objects.create(
                pedido=pedido,
                pagamento=pagamento,
                destinatario=_destinatario(pedido.usuario),
                canal=Notificacao.Canais.EMAIL,
                assunto=assunto,
                conteudo=conteudo,
                evento_origem=evento.event_id,
            )
            emitir_apos_commit(NOTIFICACAO_REGISTRADA, pedido_id=pedido.pk)
    except IntegrityError:
        # Reentrega que chegou depois da gravação: o índice único em
        # `evento_origem` decide e o registro vencedor é devolvido.
        vencedor = Notificacao.objects.filter(evento_origem=evento.event_id).first()
        if vencedor is None:
            raise
        return vencedor
    return notificacao


def processar_pagamento_processado(bruto: Dict[str, Any], tentativa: int = 0) -> None:
    """Handler do ``notificacao-worker`` para o evento ``PagamentoProcessado``.

    Idempotente: reentrega do mesmo evento não gera segunda notificação, porque a
    chave ``pagamento:<id>`` já está registrada e o ``evento_origem`` é único.
    Qualquer exceção sobe para o consumidor, que reentrega ou manda para a DLQ.
    """
    evento = EventoPagamentoProcessado.from_dict(bruto)
    inicio = time.perf_counter()

    if idempotencia.ja_processado(evento.event_type, evento.idempotency_key):
        _log(
            "worker.notificacao.duplicado",
            event_type=evento.event_type,
            correlation_id=evento.correlation_id,
            idempotency_key=evento.idempotency_key,
            pagamento_id=evento.pagamento_id,
            tentativa=tentativa,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )
        return

    with transaction.atomic():
        pagamento = (
            Pagamento.objects.select_related("pedido__usuario")
            .filter(pk=evento.pagamento_id)
            .first()
        )
        if pagamento is None:
            raise PagamentoInexistente(
                f"pagamento {evento.pagamento_id} referenciado pelo evento nao existe"
            )
        pedido = pagamento.pedido
        if pedido.pk != evento.pedido_id:
            raise PagamentoInexistente(
                f"evento do pagamento {pagamento.pk} aponta para o pedido "
                f"{evento.pedido_id}, mas o pagamento pertence ao pedido {pedido.pk}"
            )

        if not evento.aprovado:
            # Caminho negativo: nenhum registro e nenhum evento. O log existe
            # para que a ausência de notificação seja um desfecho observável.
            _log(
                "worker.notificacao.recusada",
                event_type=evento.event_type,
                correlation_id=evento.correlation_id,
                idempotency_key=evento.idempotency_key,
                pedido_id=pedido.pk,
                pagamento_id=pagamento.pk,
                status=evento.status,
                motivo="pagamento recusado nao gera notificacao",
                tentativa=tentativa,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
            )
            # Registra a chave para que a reentrega do recusado não reprocesse.
            idempotencia.registrar(
                evento.event_type, evento.idempotency_key,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
            )
            return

        notificacao = _registrar(evento, pagamento, pedido)

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 3)
    idempotencia.registrar(evento.event_type, evento.idempotency_key, duracao_ms=duracao_ms)
    publicado = publicar_notificacao_enviada(notificacao)
    _log(
        "worker.notificacao.processada",
        event_type=evento.event_type,
        correlation_id=evento.correlation_id,
        idempotency_key=evento.idempotency_key,
        pedido_id=pedido.pk,
        pagamento_id=pagamento.pk,
        notificacao_id=notificacao.pk,
        canal=notificacao.canal,
        destinatario=notificacao.destinatario,
        evento_publicado=publicado,
        tentativa=tentativa,
        resultado="ok",
        duracao_ms=duracao_ms,
    )
