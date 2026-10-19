"""Worker consumidor do evento ``PagamentoProcessado`` (Aula 11).

Roda como processo separado (``docker compose up notificacao-worker``) e é o lado
*consumidor* do segundo elo do fluxo: ``Pedido ➔ Pagamento ➔ Notificação``.

O que ele faz ao receber uma mensagem:

1. valida o contrato (``events.contracts``) — evento desconhecido ou corrompido é
   rejeitado antes de qualquer escrita;
2. consulta a chave de idempotência — reentrega de um evento já aplicado é
   confirmada sem efeito colateral;
3. aplica o efeito de domínio: pagamento aprovado gera ``Notificacao``; recusado
   não gera nada, e o log registra a decisão;
4. registra a chave de deduplicação com TTL e publica ``NotificacaoEnviada``,
   fechando a cadeia.

Se qualquer passo levantar exceção, a exceção sobe para
``services.messaging.ConsumidorEvento``, que aplica a política de reentrega (recuo
exponencial) e, ao esgotar as tentativas, deixa a mensagem morrer para a DLQ.

Este worker é a **segunda prova** do par produtor/consumidor da Camada 5: o
``pedido-worker`` consome o que a API publica, e este consome o que a API publica
**e publica de novo**. Um evento gerado dentro de um consumidor é o teste de que a
arquitetura funciona nos dois sentidos.

Simulação de erro para validar reentrega e DLQ (DoD da Aula 11, "erro forçado"):
``NOTIFICACAO_WORKER_FALHA_IDEM_KEYS=pedido:7`` faz o worker rejeitar o pagamento
do pedido 7, exercitando o caminho de falha **no segundo elo** do fluxo. Sem isso,
o retry e a DLQ das Aulas 9 e 10 só teriam evidência antes do pagamento.

O padrão casa com duas strings, e as duas existem por um motivo prático: o
``idempotency_key`` do evento é ``pagamento:<id>``, e esse id só existe **depois**
que a API grava o pagamento — quem precisa provocar a falha é justamente quem ainda
não tem o id. O ``pedido:<id>`` é conhecido por quem chama a API, então é o que
torna o cenário reproduzível. É um gancho de teste, não de produção: existe para
que o caminho de falha seja observável sem alterar o código.
"""

import os
import sys
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from workers.comum import (  # noqa: E402  (bootstrap do Django e do sys.path)
    ErroForcadoDeTeste,
    destino_log,
    executar_worker,
    falha_forcada,
)

from django.conf import settings  # noqa: E402

from events.contracts import EVENTO_PAGAMENTO_PROCESSADO  # noqa: E402
from services import notificacao  # noqa: E402


def _falha_forcada(candidatos) -> bool:
    """Informa se este pagamento deve falhar de propósito (validação da DLQ)."""
    return falha_forcada(
        candidatos,
        "NOTIFICACAO_WORKER_FALHAR_SEMPRE",
        settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS,
    )


def processar(bruto: Dict[str, Any], tentativa: int) -> None:
    """Handler do consumidor. A falha forçada acontece **antes** do efeito."""
    evento = bruto or {}
    # O `pedido_id` mora em `dados` — é o envelope que chega aqui, não o payload
    # desempacotado pelo contrato — e é dali que o cenário de falha tira o id.
    dados = evento.get("dados") or {}
    pedido_id = evento.get("pedido_id") or dados.get("pedido_id")
    candidatos = (
        str(evento.get("idempotency_key") or ""),
        f"pedido:{pedido_id}",
    )
    if _falha_forcada(candidatos):
        raise ErroForcadoDeTeste(
            f"falha forcada para o evento {evento.get('event_type')} "
            f"{evento.get('idempotency_key')} (pedido {pedido_id})"
        )
    notificacao.processar_pagamento_processado(bruto, tentativa)


def _destino_log() -> dict:
    """Nome da fila/tópico de trabalho e da DLQ, conforme o broker ativo."""
    return dict(destino_log(EVENTO_PAGAMENTO_PROCESSADO))


def main() -> None:
    executar_worker(
        nome="notificacao",
        evento=EVENTO_PAGAMENTO_PROCESSADO,
        handler=processar,
        client_id="synapseshop-notificacao-worker",
        falha_ativa=settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS,
    )


if __name__ == "__main__":
    main()
