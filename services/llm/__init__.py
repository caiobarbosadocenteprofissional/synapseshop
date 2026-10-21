"""``llm_service`` — camada de acesso ao provedor de LLM (Aula 14).

Toda a comunicação com o provedor de IA passa por aqui. O objetivo não é "chamar
a API": é sobreviver a ela falhar. Timeout, retry com backoff + jitter, circuit
breaker, redação de PII e telemetria vivem neste pacote; o que é detalhe de uma
dessas responsabilidades mora em um módulo próprio e é reexportado aqui para que
``services.llm`` continue sendo o único nome que o resto do código conhece.

O transporte HTTP usa apenas a biblioteca padrão (``urllib``): a Aula 14 é sobre
resiliência, não sobre adotar um cliente HTTP, e uma dependência a menos é uma
superfície a menos para atualizar.
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

from services.llm.circuito import CircuitBreaker
from services.llm.erros import (
    ERROS_REENTREGAVEIS,
    LLMCircuitoAberto,
    LLMConfiguracaoAusente,
    LLMErro,
    LLMIndisponivel,
    LLMPayloadInvalido,
    LLMTaxaLimitada,
    LLMTimeout,
)
from services.llm.redacao import redigir
from services.llm.telemetria import _Telemetria
from services.llm.transporte import _extrair, _http_post_json
from services.log_estruturado import LoggerEstruturado
from services.prompts import MODOS, montar_mensagens, normalizar_logs

logger = logging.getLogger("synapseshop.ia")
log = LoggerEstruturado(logger)

_TELEMETRIA = _Telemetria()
_CIRCUITO = CircuitBreaker()


def metricas() -> Dict[str, Any]:
    """Snapshot da telemetria, somado ao estado do circuito."""
    return {**_TELEMETRIA.metricas(), "circuito": _CIRCUITO.estado()}


def resetar_metricas() -> Dict[str, Any]:
    """Zera os contadores (usado pelo ``POST /api/v1/assist/stats/``)."""
    _TELEMETRIA.resetar()
    return metricas()


def redefinir_circuito() -> Dict[str, Any]:
    """Fecha o circuito (usado entre testes e por ``POST /assist/stats/``)."""
    _CIRCUITO.registrar_sucesso()
    return _CIRCUITO.estado()


def _requisitar(
    mensagens: List[dict], temperature: float, max_tokens: int
) -> Dict[str, Any]:
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "messages": mensagens,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
    }
    return _http_post_json(url, payload, headers, settings.LLM_TIMEOUT_S)


def _dormir(segundos: float) -> None:
    """Ponto único de espera — isolado para os testes não esperarem de verdade."""
    time.sleep(segundos)


def _espera_backoff(tentativa: int) -> float:
    """Backoff exponencial com jitter (*equal jitter*).

    ``min(base * 2^(n-1), teto)`` dá o crescimento exponencial; metade fixa mais
    metade aleatória preserva o espaçamento mínimo e, ao mesmo tempo, desalinha
    clientes que falharam juntos — sem jitter, todos retentam no mesmo instante.
    """
    base = settings.LLM_BACKOFF_BASE_MS / 1000.0
    teto = settings.LLM_BACKOFF_MAX_MS / 1000.0
    atraso = min(base * (2 ** (tentativa - 1)), teto)
    return atraso / 2 + random.uniform(0, atraso / 2)


def _chamar_com_resiliencia(
    mensagens: List[dict], temperature: float, max_tokens: int
) -> Tuple[str, Dict[str, int], int]:
    """Chama o provedor com circuito aberto + retry. Devolve ``(resposta, uso, tentativas)``."""
    if not _CIRCUITO.permitir():
        raise LLMCircuitoAberto(
            "Circuito do provedor de LLM aberto; novas tentativas em breve."
        )

    max_tentativas = max(1, settings.LLM_MAX_TENTATIVAS)
    ultimo_erro: Optional[LLMErro] = None
    tentativas = 0
    for tentativa in range(1, max_tentativas + 1):
        tentativas = tentativa
        try:
            dados = _requisitar(mensagens, temperature, max_tokens)
            conteudo, uso = _extrair(dados)
        except ERROS_REENTREGAVEIS as exc:
            ultimo_erro = exc
            _CIRCUITO.registrar_falha()
            if tentativa >= max_tentativas:
                break
            espera = _espera_backoff(tentativa)
            log(
                "llm.reentrega",
                tentativa=tentativa,
                proxima_tentativa=tentativa + 1,
                espera_ms=round(espera * 1000, 1),
                erro=type(exc).__name__,
            )
            _dormir(espera)
        else:
            _CIRCUITO.registrar_sucesso()
            return conteudo, uso, tentativas

    assert ultimo_erro is not None  # o loop só sai sem retorno após registrar erro
    raise ultimo_erro


def _custo_estimado_usd(tokens_prompt: int, tokens_output: int) -> float:
    preco_prompt = getattr(settings, "LLM_PRECO_PROMPT_USD_MILHAO", 0.0)
    preco_output = getattr(settings, "LLM_PRECO_OUTPUT_USD_MILHAO", 0.0)
    return (tokens_prompt / 1_000_000) * preco_prompt + (
        tokens_output / 1_000_000
    ) * preco_output


def assistir(
    *,
    mode: str,
    logs: Any,
    temperature: float = 0.2,
    max_tokens: int = 256,
) -> Dict[str, Any]:
    """Sumariza/explica logs via LLM e devolve ``{"answer", "meta"}``.

    O fluxo é sempre o mesmo, e a ordem importa: **redigir antes de enviar** o
    texto ao provedor; só depois montar o prompt e chamar a camada resiliente.
    """
    if mode not in MODOS:
        raise LLMPayloadInvalido(f"Modo inválido: {mode!r}.")
    if not settings.LLM_API_KEY:
        raise LLMConfiguracaoAusente(
            "LLM_API_KEY não configurada; o assistente está desabilitado."
        )

    texto_redigido, redacoes = redigir(normalizar_logs(logs))
    mensagens = montar_mensagens(mode, texto_redigido)

    inicio = time.monotonic()
    try:
        conteudo, uso, tentativas = _chamar_com_resiliencia(
            mensagens, temperature, max_tokens
        )
    except LLMErro as exc:
        latencia_ms = round((time.monotonic() - inicio) * 1000, 3)
        _TELEMETRIA.registrar_erro(tipo_erro=type(exc).__name__, latencia_ms=latencia_ms)
        log(
            "llm.falha",
            modo=mode,
            erro=type(exc).__name__,
            estado_circuito=_CIRCUITO.estado()["estado"],
            latencia_ms=latencia_ms,
            redacoes=redacoes,
        )
        raise

    latencia_ms = round((time.monotonic() - inicio) * 1000, 3)
    tokens_prompt = uso["prompt_tokens"]
    tokens_output = uso["completion_tokens"]
    custo = _custo_estimado_usd(tokens_prompt, tokens_output)
    _TELEMETRIA.registrar_sucesso(
        latencia_ms=latencia_ms,
        tokens_prompt=tokens_prompt,
        tokens_output=tokens_output,
        custo_usd=custo,
    )
    log(
        "llm.resposta",
        modo=mode,
        modelo=settings.LLM_MODEL,
        tentativas=tentativas,
        tokens_prompt=tokens_prompt,
        tokens_output=tokens_output,
        custo_estimado_usd=round(custo, 8),
        latencia_ms=latencia_ms,
        redacoes=redacoes,
        estado_circuito=_CIRCUITO.estado()["estado"],
    )

    return {
        "answer": conteudo,
        "meta": {
            "tokens_prompt": tokens_prompt,
            "tokens_output": tokens_output,
            "tentativas": tentativas,
            "latencia_ms": latencia_ms,
            "custo_estimado_usd": round(custo, 8),
            "redacoes": redacoes,
            "modelo": settings.LLM_MODEL,
        },
    }


__all__ = [
    "CircuitBreaker",
    "ERROS_REENTREGAVEIS",
    "LLMCircuitoAberto",
    "LLMConfiguracaoAusente",
    "LLMErro",
    "LLMIndisponivel",
    "LLMPayloadInvalido",
    "LLMTaxaLimitada",
    "LLMTimeout",
    "assistir",
    "metricas",
    "redefinir_circuito",
    "redigir",
    "resetar_metricas",
]
