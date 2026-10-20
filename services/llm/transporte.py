"""Transporte HTTP (stdlib) e parsing da resposta do provedor."""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

from services.llm.erros import (
    LLMIndisponivel,
    LLMPayloadInvalido,
    LLMTaxaLimitada,
    LLMTimeout,
)


def _http_post_json(
    url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float
) -> Dict[str, Any]:
    """POST JSON com a biblioteca padrão, traduzindo falhas em ``LLMErro``.

    A tradução é o valor desta função: o resto do serviço lida com exceções de
    domínio (``LLMTimeout`` etc.), não com ``HTTPError``/``URLError``.
    """
    corpo = json.dumps(payload).encode("utf-8")
    requisicao = urllib.request.Request(url, data=corpo, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 429:
            raise LLMTaxaLimitada(f"Provedor limitou a taxa (429): {detalhe}") from exc
        if exc.code >= 500:
            raise LLMIndisponivel(
                f"Provedor indisponível ({exc.code}): {detalhe}"
            ) from exc
        raise LLMPayloadInvalido(
            f"Provedor rejeitou a requisição ({exc.code}): {detalhe}"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise LLMTimeout(f"Timeout na conexão com o provedor: {exc.reason}") from exc
        raise LLMIndisponivel(f"Falha de rede com o provedor: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise LLMTimeout("Timeout na conexão com o provedor.") from exc
    except OSError as exc:
        raise LLMIndisponivel(f"Falha de rede com o provedor: {exc}") from exc


def _extrair(dados: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
    """Extrai a resposta e o uso de tokens do payload do provedor.

    Resposta vazia ou sem ``choices`` é ``LLMIndisponivel`` (e, portanto,
    reentregável): o provedor respondeu, mas não com o que o contrato promete.
    """
    try:
        conteudo = dados["choices"][0]["message"]["content"]
        uso = dados.get("usage") or {}
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMIndisponivel(f"Resposta inesperada do provedor: {exc}") from exc
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise LLMIndisponivel("O provedor devolveu uma resposta vazia.")
    return conteudo.strip(), {
        "prompt_tokens": int(uso.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(uso.get("completion_tokens", 0) or 0),
    }
