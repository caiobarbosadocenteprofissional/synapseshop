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

from events.contratos_base import (
    CAMPOS_OBRIGATORIOS,
    CAMPOS_OBRIGATORIOS_DADOS,
    EVENTO_NOTIFICACAO_ENVIADA,
    EVENTO_PAGAMENTO_PROCESSADO,
    EVENTO_PEDIDO_CRIADO,
    MAX_CARACTERES_CHAVE,
    VERSAO_CONTRATO,
    ContratoInvalido,
)
from events.eventos import (
    EventoNotificacaoEnviada,
    EventoPagamentoProcessado,
    EventoPedidoCriado,
    ItemPedidoCriado,
)

__all__ = [
    "CAMPOS_OBRIGATORIOS",
    "CAMPOS_OBRIGATORIOS_DADOS",
    "EVENTO_NOTIFICACAO_ENVIADA",
    "EVENTO_PAGAMENTO_PROCESSADO",
    "EVENTO_PEDIDO_CRIADO",
    "MAX_CARACTERES_CHAVE",
    "VERSAO_CONTRATO",
    "ContratoInvalido",
    "EventoNotificacaoEnviada",
    "EventoPagamentoProcessado",
    "EventoPedidoCriado",
    "ItemPedidoCriado",
]
