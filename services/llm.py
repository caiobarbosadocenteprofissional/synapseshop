"""``llm_service`` — camada de acesso ao provedor de LLM (Aula 14).

Toda a comunicação com o provedor de IA passa por aqui. O objetivo não é "chamar
a API": é sobreviver a ela falhar. Um provedor de LLM é um serviço externo com
timeout, limite de taxa, indisponibilidade e cobrança por token, e cada um desses
modos de falha exige uma resposta diferente:

1. **Timeout** — sem um prazo curto (``LLM_TIMEOUT_S``), uma lentidão do provedor
   vira requisição pendurada. Um prazo de 5s transforma "travou" em "falhou", que
   é tratável.
2. **Retry com backoff exponencial + jitter** — falhas transitórias merecem uma
   segunda chance, mas retentar imediatamente em ritmo fixo sincroniza todos os
   clientes e piora a sobrecarga que causou a falha. O backoff espaça; o jitter
   (variação aleatória) desalinha quem subiu junto.
3. **Circuit breaker** (``closed``/``open``/``half-open``) — depois de N falhas
   consecutivas, insistir é só somar latência ao usuário. O circuito **abre** e
   passa a falhar rápido; após o repouso entra em **half-open** e deixa passar
   uma única tentativa de prova: se voltar a falhar, reabre; se passar, fecha.
4. **Redação (redaction)** — o prompt é o último ponto do dado dentro de casa.
   Email, CPF/CNPJ, cartão, telefone e segredos são substituídos por marcadores
   **antes** de sair para o provedor e antes de qualquer log.
5. **Telemetria** — latência, taxa de erro, tokens e custo estimado são contados
   a cada chamada e ficam legíveis em ``GET /api/v1/assist/stats/``.

O transporte HTTP usa apenas a biblioteca padrão (``urllib``): a Aula 14 é sobre
resiliência, não sobre adotar um cliente HTTP, e uma dependência a menos é uma
superfície a menos para atualizar.
"""

import json
import logging
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

from services.log_estruturado import log_evento
from services.prompts import MODOS, montar_mensagens, normalizar_logs

logger = logging.getLogger("synapseshop.ia")


# --------------------------------------------------------------------------- #
# Erros do provedor — cada um carrega o status HTTP que o endpoint devolve
# --------------------------------------------------------------------------- #
class LLMErro(Exception):
    """Erro base da camada de IA. ``status_http`` é o mapeamento para a API."""

    status_http = 502


class LLMConfiguracaoAusente(LLMErro):
    """``LLM_API_KEY`` não configurada: nada é enviado ao provedor."""

    status_http = 503


class LLMCircuitoAberto(LLMErro):
    """O circuito está aberto; a chamada falha rápido sem tocar o provedor."""

    status_http = 503


class LLMTimeout(LLMErro):
    """O provedor não respondeu dentro de ``LLM_TIMEOUT_S``."""

    status_http = 504


class LLMTaxaLimitada(LLMErro):
    """HTTP 429 — o provedor pediu para desacelerar."""

    status_http = 429


class LLMIndisponivel(LLMErro):
    """HTTP 5xx, erro de rede ou resposta inesperada do provedor."""

    status_http = 502


class LLMPayloadInvalido(LLMErro):
    """HTTP 4xx (exceto 429) — a requisição está errada; retentar não ajuda."""

    status_http = 400


# Erros que valem reentrega. ``LLMPayloadInvalido`` fica de fora de propósito:
# repetir uma requisição malformada só repete o erro.
_ERROS_REENTREGAVEIS = (LLMTimeout, LLMTaxaLimitada, LLMIndisponivel)


# --------------------------------------------------------------------------- #
# Redação de dados sensíveis (LGPD/RGPD)
# --------------------------------------------------------------------------- #
# A ordem importa: padrões específicos primeiro, para que um número curto (CPF)
# não seja capturado por um mais largo (cartão) nem um segredo por uma URL.
_PADROES_REDACAO = (
    (
        "SEGREDO",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|"
            r"password|passwd|senha|authorization)\b\s*[:=]\s*[\"']?[^\s\"',;]+"
        ),
    ),
    ("BEARER", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("CNPJ", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("CARTAO", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("TELEFONE", re.compile(r"(?:\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}\b")),
)


def redigir(texto: str) -> Tuple[str, int]:
    """Substitui PII e segredos por marcadores. Devolve ``(texto, nº redações)``.

    A contagem, e não o conteúdo, é o que se registra em log: assim a política de
    privacidade é auditável ("esta requisição redigiu 3 dados") sem que o próprio
    log de auditoria vire uma nova cópia do dado sensível.
    """
    total = 0
    for marcador, padrao in _PADROES_REDACAO:
        texto, substituicoes = padrao.subn(f"[{marcador}_REDIGIDO]", texto)
        total += substituicoes
    return texto, total


# --------------------------------------------------------------------------- #
# Telemetria (latência, erros, tokens, custo)
# --------------------------------------------------------------------------- #
class _Telemetria:
    """Contadores em memória, protegidos por lock.

    Em memória porque a métrica desta aula é de processo único; um sistema com
    vários workers agregaria no Redis/Prometheus, o que é evolução registrada no
    backlog, não escopo agora.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.resetar()

    def resetar(self) -> None:
        with self._lock:
            self._chamadas = 0
            self._sucessos = 0
            self._erros = 0
            self._tokens_prompt = 0
            self._tokens_output = 0
            self._latencia_total_ms = 0.0
            self._custo_total_usd = 0.0
            self._por_tipo_erro: Dict[str, int] = {}

    def registrar_sucesso(
        self,
        *,
        latencia_ms: float,
        tokens_prompt: int,
        tokens_output: int,
        custo_usd: float,
    ) -> None:
        with self._lock:
            self._chamadas += 1
            self._sucessos += 1
            self._tokens_prompt += tokens_prompt
            self._tokens_output += tokens_output
            self._latencia_total_ms += latencia_ms
            self._custo_total_usd += custo_usd

    def registrar_erro(self, *, tipo_erro: str, latencia_ms: float) -> None:
        with self._lock:
            self._chamadas += 1
            self._erros += 1
            self._latencia_total_ms += latencia_ms
            self._por_tipo_erro[tipo_erro] = self._por_tipo_erro.get(tipo_erro, 0) + 1

    def metricas(self) -> Dict[str, Any]:
        with self._lock:
            chamadas = self._chamadas
            return {
                "chamadas": chamadas,
                "sucessos": self._sucessos,
                "erros": self._erros,
                "taxa_erro": round(self._erros / chamadas, 4) if chamadas else 0.0,
                "tokens_prompt": self._tokens_prompt,
                "tokens_output": self._tokens_output,
                "tokens_total": self._tokens_prompt + self._tokens_output,
                "latencia_media_ms": (
                    round(self._latencia_total_ms / chamadas, 3) if chamadas else 0.0
                ),
                "custo_total_usd": round(self._custo_total_usd, 6),
                "erros_por_tipo": dict(self._por_tipo_erro),
            }


_TELEMETRIA = _Telemetria()


def metricas() -> Dict[str, Any]:
    """Snapshot da telemetria, somado ao estado do circuito."""
    return {**_TELEMETRIA.metricas(), "circuito": _CIRCUITO.estado()}


def resetar_metricas() -> Dict[str, Any]:
    """Zera os contadores (usado pelo ``POST /api/v1/assist/stats/``)."""
    _TELEMETRIA.resetar()
    return metricas()


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
class CircuitBreaker:
    """Máquina de estados ``closed`` → ``open`` → ``half-open`` → ``closed``.

    Lê os limites de ``settings`` a cada transição (e não no ``__init__``) para
    que testes e operação possam reconfigurar sem recriar o objeto — o estado, que
    é o que precisa sobreviver às requisições, fica no objeto; a configuração fica
    nas settings.
    """

    FECHADO = "closed"
    ABERTO = "open"
    MEIO_ABERTO = "half-open"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._redefinir()

    def _redefinir(self) -> None:
        self._estado = self.FECHADO
        self._falhas = 0
        self._aberto_ate = 0.0

    def permitir(self) -> bool:
        """``False`` faz a chamada falhar rápido, sem tocar o provedor."""
        with self._lock:
            if self._estado == self.FECHADO:
                return True
            if self._estado == self.ABERTO:
                if time.monotonic() >= self._aberto_ate:
                    # Repouso vencido: libera UMA tentativa de prova.
                    self._estado = self.MEIO_ABERTO
                    return True
                return False
            return True  # half-open: a tentativa de prova está em voo

    def registrar_sucesso(self) -> None:
        with self._lock:
            self._redefinir()

    def registrar_falha(self) -> None:
        with self._lock:
            self._falhas += 1
            limite = getattr(settings, "LLM_CIRCUITO_LIMITE_FALHAS", 3)
            if self._estado == self.MEIO_ABERTO or self._falhas >= limite:
                self._estado = self.ABERTO
                self._aberto_ate = time.monotonic() + getattr(
                    settings, "LLM_CIRCUITO_RESET_SEGUNDOS", 30
                )

    def estado(self) -> Dict[str, Any]:
        with self._lock:
            return {"estado": self._estado, "falhas_consecutivas": self._falhas}


_CIRCUITO = CircuitBreaker()


def redefinir_circuito() -> Dict[str, Any]:
    """Fecha o circuito (usado entre testes e por ``POST /assist/stats/``)."""
    _CIRCUITO.registrar_sucesso()
    return _CIRCUITO.estado()


# --------------------------------------------------------------------------- #
# Transporte HTTP (stdlib) e parsing da resposta
# --------------------------------------------------------------------------- #
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
        except _ERROS_REENTREGAVEIS as exc:
            ultimo_erro = exc
            _CIRCUITO.registrar_falha()
            if tentativa >= max_tentativas:
                break
            espera = _espera_backoff(tentativa)
            _log(
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


# --------------------------------------------------------------------------- #
# Operação principal
# --------------------------------------------------------------------------- #
def _log(nome_evento: str, **campos: Any) -> None:
    log_evento(logger, nome_evento, **campos)


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
        _log(
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
    _log(
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
