"""Publicação de eventos de domínio, comum aos três produtores (Aulas 9 a 11).

A Aula 9 publicou ``PedidoCriado``; a Aula 11 publica ``PagamentoProcessado`` (da
API) e ``NotificacaoEnviada`` (do worker). Os três pontos de publicação são o
mesmo procedimento — conectar, publicar, avisar se o broker recusou — e a diferença
está apenas na topologia e no nome do log.

Centralizar isso aqui resolve o problema que apareceu com a segunda publicação: o
caminho de falha (broker fora do ar) **não pode derrubar a requisição nem o
worker**, porque o dado já está commitado. A regra é sempre a mesma: registra o
log, devolve ``False`` e deixa quem chamou sinalizar na resposta. Publicar é
tentado, não exigido — e o desfecho fica visível no log e no corpo da resposta.

O que **não** é comum é o efeito colateral: quem chama decide o que fazer quando a
publicação falha, e por isso cada produtor registra o seu próprio evento de
negócio (``pedido.criado``, ``pagamento.registrado``, ``notificacao.registrada``)
com o campo ``evento_publicado``.
"""

import json
import logging
from typing import Any, Dict, Optional

from django.conf import settings

from events.topology import TopologiaEvento
from services.messaging import MensageriaIndisponivel, ProdutorEvento

logger = logging.getLogger("synapseshop.mensageria")


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `event_type` e a colisão seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


def publicar_evento(
    *,
    evento: Dict[str, Any],
    idempotency_key: str,
    topologia: TopologiaEvento,
    prefixo_log: str,
    client_id: str = "synapseshop-api",
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Publica o evento. Devolve ``False`` quando a publicação não aconteceu.

    ``False`` significa uma de três coisas, todas registradas em log com a mesma
    chave ``<prefixo>.publicacao_ignorada`` ou ``<prefixo>.publicacao_falhou``:
    a mensageria está desligada por ``MESSAGERIA_ENABLED``, o broker recusou, ou a
    publicação excedeu o tempo de confirmação.
    """
    if not settings.MESSAGERIA_ENABLED:
        _log(
            f"{prefixo_log}.publicacao_ignorada",
            idempotency_key=idempotency_key,
            motivo="MESSAGERIA_ENABLED=false",
            **(extra or {}),
        )
        return False

    try:
        with ProdutorEvento(topologia, client_id=client_id) as produtor:
            produtor.publicar(evento, idempotency_key)
        return True
    except MensageriaIndisponivel as exc:
        _log(
            f"{prefixo_log}.publicacao_falhou",
            idempotency_key=idempotency_key,
            erro=str(exc),
            **(extra or {}),
        )
        return False