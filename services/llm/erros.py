"""Erros do provedor de LLM, cada um com o status HTTP que a API devolve."""


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
ERROS_REENTREGAVEIS = (LLMTimeout, LLMTaxaLimitada, LLMIndisponivel)
