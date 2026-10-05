"""Pagamento simulado do pedido (Aula 11).

A API recebe o desfecho que o cliente quer observar (``APROVADO`` ou ``RECUSADO``)
e o persiste como se fosse a resposta de um adquirente. A simulação é o que
importa: o que a aula precisa provar é o **contrato** do pagamento — um pagamento
por pedido, com valor e estado congelados, publicação do evento e efeito
observável em outro processo.

Três decisões moram aqui:

1. **Um pagamento por pedido.** ``Pedido.pagamento`` é ``OneToOneField``, então a
   idempotência do pagamento é estrutural e não precisa de chave: repetir o
   pagamento devolve o mesmo registro com **200** e **não publica evento novo**.
   Criar um segundo pagamento do mesmo pedido é impossível pelo banco, não por
   uma condição no código.
2. **O estado do pedido muda junto do pagamento.** Aprovado leva o pedido a
   ``PAGO`` e recusado a ``CANCELADO``, na mesma transação da gravação do
   pagamento. Se o pedido fosse atualizado depois, existiria uma janela em que o
   pagamento está gravado e o pedido ainda diz ``PROCESSANDO``.
3. **O evento leva o desfecho, não o motivo.** ``PagamentoProcessado`` transporta
   ``dados.status``, e o ``notificacao-worker`` decide a partir dele: aprovado gera
   notificação, recusado não gera — e o log registra a decisão, que é o caminho
   negativo que o smoke test exercita.
"""

import json
import logging
import uuid
from typing import Tuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from events.contracts import EventoPagamentoProcessado
from events.topology import chave_de, topologia_de
from repositories.models import Pagamento, Pedido
from services.events import PAGAMENTO_APROVADO, PAGAMENTO_RECUSADO, emitir_apos_commit

logger = logging.getLogger("synapseshop.pagamento")


def _log(nome_evento: str, **campos) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `event_type` e a colisão seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


def _referencia_simulada() -> str:
    """Referência da transação simulada.

    O formato é o mesmo de um PIX (``E`` + 32 dígitos) porque é o único identificador
    de transação brasileiro com comprimento fixo; a unicidade da coluna garante que
    duas transações não se confundem.
    """
    return f"E{uuid.uuid4().hex[:32]}"


def registrar_pagamento(
    pedido: Pedido,
    resultado: str,
    forma_pagamento: str,
) -> Tuple[Pagamento, bool]:
    """Grava o pagamento e move o pedido para ``PAGO`` ou ``CANCELADO``.

    Devolve ``(pagamento, criado)``. ``criado=False`` significa que o pedido já
    tinha pagamento: o registro existente é devolvido e nada é gravado, o que faz
    a repetição da requisição ser inofensiva por construção.

    Tudo dentro de uma transação: pagamento, estado do pedido e evento de domínio
    (emitido no ``on_commit``, portanto depois do commit) formam um só desfecho.
    """
    existente = Pagamento.objects.filter(pedido=pedido).first()
    if existente is not None:
        _log(
            "pagamento.duplicado",
            pedido_id=pedido.pk,
            pagamento_id=existente.pk,
            status=existente.status,
        )
        return existente, False

    status = (
        Pagamento.Status.APROVADO
        if resultado == Pagamento.Status.APROVADO
        else Pagamento.Status.RECUSADO
    )
    novo_status_pedido = (
        Pedido.Status.PAGO if status == Pagamento.Status.APROVADO else Pedido.Status.CANCELADO
    )

    try:
        with transaction.atomic():
            pagamento = Pagamento.objects.create(
                pedido=pedido,
                status=status,
                # Valor congelado do pedido: o catálogo pode mudar depois, e o
                # histórico financeiro não pode.
                valor=pedido.total,
                forma_pagamento=forma_pagamento,
                referencia=_referencia_simulada(),
                processado_em=timezone.now(),
            )
            pedido.status = novo_status_pedido
            pedido.processado_em = timezone.now()
            pedido.save(update_fields=["status", "processado_em", "updated_at"])
    except IntegrityError:
        # Duas requisições simultâneas para o mesmo pedido: a restrição
        # OneToOne decide, e a perdedora devolve o pagamento vencedor.
        vencedor = Pagamento.objects.filter(pedido=pedido).first()
        if vencedor is None:
            raise
        _log(
            "pagamento.conflito",
            pedido_id=pedido.pk,
            pagamento_id=vencedor.pk,
        )
        return vencedor, False

    emitir_apos_commit(
        PAGAMENTO_APROVADO if status == Pagamento.Status.APROVADO else PAGAMENTO_RECUSADO,
        pedido_id=pedido.pk,
    )
    _log(
        "pagamento.registrado",
        pedido_id=pedido.pk,
        pagamento_id=pagamento.pk,
        usuario_id=pedido.usuario_id,
        status=status,
        valor=str(pagamento.valor),
        forma_pagamento=pagamento.forma_pagamento,
        referencia=pagamento.referencia,
        correlation_id=pedido.correlation_id,
        novo_status_pedido=novo_status_pedido,
    )
    return pagamento, True


def evento_pagamento_processado(pagamento: Pagamento) -> EventoPagamentoProcessado:
    """Monta o evento ``PagamentoProcessado`` do pagamento gravado.

    A chave de idempotência é ``pagamento:<id>`` e o ``correlation_id`` é o do
    pedido: é isso que liga os logs da API, do ``notificacao-worker`` e da
    notificação ao mesmo pedido.
    """
    return EventoPagamentoProcessado(
        idempotency_key=chave_de(pagamento.pk, "pagamento"),
        pagamento_id=pagamento.pk,
        pedido_id=pagamento.pedido_id,
        usuario_id=pagamento.pedido.usuario_id,
        valor=pagamento.valor,
        status=pagamento.status,
        forma_pagamento=pagamento.forma_pagamento,
        referencia=pagamento.referencia,
        correlation_id=pagamento.pedido.correlation_id or "",
    )


def publicar_pagamento_processado(pagamento: Pagamento) -> bool:
    """Publica o evento. ``False`` quando o broker não aceitou (ver ``services.publicacao``)."""
    from services.publicacao import publicar_evento

    evento = evento_pagamento_processado(pagamento)
    return publicar_evento(
        evento=evento.to_dict(),
        idempotency_key=evento.idempotency_key,
        topologia=topologia_de(evento.event_type),
        prefixo_log="pagamento",
        extra={"pagamento_id": pagamento.pk, "pedido_id": pagamento.pedido_id},
    )
