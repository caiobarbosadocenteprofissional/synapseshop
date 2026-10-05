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

import json
import logging
import os
import sys
from fnmatch import fnmatchcase
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402  (após o ajuste de sys.path e DJANGO_SETTINGS_MODULE)

django.setup()

from django.conf import settings  # noqa: E402

from events.contracts import EVENTO_PAGAMENTO_PROCESSADO  # noqa: E402
from events.topology import topologia_de  # noqa: E402
from services import idempotencia  # noqa: E402
from services import notificacao  # noqa: E402
from services.messaging import ConsumidorEvento  # noqa: E402

logger = logging.getLogger("synapseshop.worker")


class ErroForcadoDeTeste(RuntimeError):
    """Falha proposital para exercitar a reentrega e a DLQ (DoD da Aula 11)."""


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: o contrato do
    # evento tem um campo `event_type` e a colisão de nome seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


def _falha_forcada(candidatos) -> bool:
    """Informa se este pagamento deve falhar de propósito (validação da DLQ)."""
    if os.environ.get("NOTIFICACAO_WORKER_FALHAR_SEMPRE", "").lower() in ("1", "true", "yes"):
        return True
    return any(
        fnmatchcase(candidato, padrao)
        for candidato in candidatos
        for padrao in settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS
        if candidato
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
    """Nome da fila/tópico de trabalho e da DLQ, conforme o broker ativo.

    O log de subida precisa dizer onde a mensagem entra e onde a morta sai, e os
    dois nomes são diferentes entre AMQP e Kafka. Tudo vem da topologia do evento,
    então este log não pode divergir do que o produtor usou.
    """
    topologia = topologia_de(EVENTO_PAGAMENTO_PROCESSADO)
    if settings.MENSAGERIA_BROKER == "kafka":
        return {
            "broker": "kafka",
            "evento": topologia.evento,
            "topico": topologia.topico,
            "dlq": topologia.dlq,
            "grupo": topologia.grupo,
            "particoes": settings.KAFKA_PARTICOES,
        }
    return {
        "broker": "rabbitmq",
        "evento": topologia.evento,
        "fila": topologia.fila,
        "dlq": topologia.fila_dlq,
        "prefetch": settings.RABBITMQ_PREFETCH,
    }


def main() -> None:
    consumidor = ConsumidorEvento(
        processar,
        topologia_de(EVENTO_PAGAMENTO_PROCESSADO),
        client_id="synapseshop-notificacao-worker",
    )
    # As chaves de deduplicação têm prazo de validade: as expiradas são
    # descartadas na subida do worker para a tabela não crescer sem limite.
    expiradas = idempotencia.limpar_expirados()
    _log(
        "worker.iniciado",
        worker="notificacao",
        max_retries=settings.MENSAGERIA_MAX_RETRIES,
        idempotencia_ttl=settings.IDEMPOTENCIA_TTL_SEGUNDOS,
        chaves_expiradas_removidas=expiradas,
        falha_forcada=bool(settings.NOTIFICACAO_WORKER_FALHA_IDEM_KEYS),
        **_destino_log(),
    )
    try:
        consumidor.executar()
    finally:
        _log("worker.encerrado", worker="notificacao")


if __name__ == "__main__":
    main()
