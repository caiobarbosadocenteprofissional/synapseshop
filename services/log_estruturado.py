"""Log estruturado em JSON compartilhado por serviços, workers e API.

Antes da Aula 15 havia 10 cópias quase idênticas de ``_log`` espalhadas por
``services/``, ``workers/`` e ``api/views.py`` — todas serializavam o mesmo
envelope ``{"evento": ..., **campos}`` com ``ensure_ascii=False`` e filtravam
campos ``None``. Este módulo é a única implementação dessa convenção.

O logger continua sendo o de cada módulo (``synapseshop.mensageria``,
``synapseshop.worker`` etc.) para preservar a separação dos sinks; o que foi
unificado é só a montagem da linha.
"""

import json
import logging
from typing import Any


def log_evento(logger: logging.Logger, nome_evento: str, **campos: Any) -> None:
    """Emite uma linha JSON com o envelope ``{"evento": ..., **campos}``.

    O primeiro parâmetro posicional não se chama ``evento`` de propósito: os
    payloads de domínio carregam um campo ``event_type``/``evento`` e a
    colisão de nome seria um ``TypeError``. Campos ``None`` são omitidos.
    """
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )
