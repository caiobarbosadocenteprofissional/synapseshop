"""Testes unitários do ``llm_service`` (Aula 14).

O foco é a **margem de erro** do provedor de LLM — exatamente o que a spec pede:
timeout, HTTP 429, HTTP 5xx e payload inválido —, além do retry com backoff, do
circuit breaker e da telemetria. O provedor é sempre substituído por um mock
(``_requisitar`` ou ``urllib.request.urlopen``): nenhum teste toca a Internet.
"""

import io
import socket
import urllib.error

import pytest

from services import llm, prompts

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _estado_limpo():
    """Zera telemetria e circuito antes/depois de cada teste."""
    llm.resetar_metricas()
    llm.redefinir_circuito()
    yield
    llm.resetar_metricas()
    llm.redefinir_circuito()


def _resposta(conteudo="resumo", prompt=10, output=20):
    return {
        "choices": [{"message": {"content": conteudo}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


def _erro_http(codigo):
    return urllib.error.HTTPError(
        "http://provedor", codigo, "erro", {}, io.BytesIO(b"corpo de erro")
    )


# --------------------------------------------------------------------------- #
# Tradução de falhas HTTP em erros de domínio
# --------------------------------------------------------------------------- #
def test_http_429_vira_taxa_limitada(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_erro_http(429))
    )
    with pytest.raises(llm.LLMTaxaLimitada):
        llm._http_post_json("http://x", {}, {}, 1)


def test_http_500_vira_indisponivel(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_erro_http(503))
    )
    with pytest.raises(llm.LLMIndisponivel):
        llm._http_post_json("http://x", {}, {}, 1)


def test_http_400_vira_payload_invalido(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_erro_http(400))
    )
    with pytest.raises(llm.LLMPayloadInvalido):
        llm._http_post_json("http://x", {}, {}, 1)


def test_url_error_de_timeout_vira_llm_timeout(monkeypatch):
    def falhar(*a, **k):
        raise urllib.error.URLError(socket.timeout("tempo esgotado"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", falhar)
    with pytest.raises(llm.LLMTimeout):
        llm._http_post_json("http://x", {}, {}, 1)


def test_url_error_de_rede_vira_indisponivel(monkeypatch):
    def falhar(*a, **k):
        raise urllib.error.URLError("host desconhecido")

    monkeypatch.setattr(llm.urllib.request, "urlopen", falhar)
    with pytest.raises(llm.LLMIndisponivel):
        llm._http_post_json("http://x", {}, {}, 1)


def test_timeout_direto_vira_llm_timeout(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError())
    )
    with pytest.raises(llm.LLMTimeout):
        llm._http_post_json("http://x", {}, {}, 1)


def test_os_error_vira_indisponivel(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("conexao recusada")),
    )
    with pytest.raises(llm.LLMIndisponivel):
        llm._http_post_json("http://x", {}, {}, 1)


def test_http_sucesso_parseia_json(monkeypatch):
    class RespostaFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"choices": []}'

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: RespostaFalsa())
    assert llm._http_post_json("http://x", {}, {}, 1) == {"choices": []}


# --------------------------------------------------------------------------- #
# Parsing da resposta do provedor
# --------------------------------------------------------------------------- #
def test_extrair_resposta_valida():
    conteudo, uso = llm._extrair(_resposta("ok", 3, 4))
    assert conteudo == "ok"
    assert uso == {"prompt_tokens": 3, "completion_tokens": 4}


def test_extrair_sem_usage_conta_zero():
    _, uso = llm._extrair({"choices": [{"message": {"content": "ok"}}]})
    assert uso == {"prompt_tokens": 0, "completion_tokens": 0}


def test_extrair_sem_choices_vira_indisponivel():
    with pytest.raises(llm.LLMIndisponivel):
        llm._extrair({"usage": {}})


def test_extrair_conteudo_vazio_vira_indisponivel():
    with pytest.raises(llm.LLMIndisponivel):
        llm._extrair({"choices": [{"message": {"content": "   "}}]})


# --------------------------------------------------------------------------- #
# Backoff
# --------------------------------------------------------------------------- #
def test_backoff_cresce_e_respeita_o_teto(settings):
    settings.LLM_BACKOFF_BASE_MS = 250
    settings.LLM_BACKOFF_MAX_MS = 5000
    primeira = llm._espera_backoff(1)
    segunda = llm._espera_backoff(2)
    assert 0.125 <= primeira <= 0.25
    assert 0.25 <= segunda <= 0.5
    assert llm._espera_backoff(50) <= 5.0


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #
def test_retry_apos_429_e_sucesso(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 3
    chamadas = {"n": 0}

    def requisitar(*a, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise llm.LLMTaxaLimitada("429")
        return _resposta()

    esperas = []
    monkeypatch.setattr(llm, "_requisitar", requisitar)
    monkeypatch.setattr(llm, "_dormir", lambda s: esperas.append(s))

    resultado = llm.assistir(mode="summarize", logs="linha")
    assert resultado["answer"] == "resumo"
    assert resultado["meta"]["tentativas"] == 2
    assert len(esperas) == 1


def test_retry_esgota_tentativas_e_levanta_ultimo_erro(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 3
    monkeypatch.setattr(llm, "_dormir", lambda s: None)
    monkeypatch.setattr(
        llm, "_requisitar", lambda *a, **k: (_ for _ in ()).throw(llm.LLMIndisponivel("500"))
    )
    with pytest.raises(llm.LLMIndisponivel):
        llm.assistir(mode="explain", logs="linha")


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
def test_circuito_abre_apos_limite_e_falha_rapido(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 1
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 2
    monkeypatch.setattr(
        llm, "_requisitar", lambda *a, **k: (_ for _ in ()).throw(llm.LLMIndisponivel("500"))
    )

    for _ in range(2):
        with pytest.raises(llm.LLMIndisponivel):
            llm.assistir(mode="summarize", logs="linha")

    assert llm.metricas()["circuito"]["estado"] == "open"
    with pytest.raises(llm.LLMCircuitoAberto):
        llm.assistir(mode="summarize", logs="linha")


def test_circuito_half_open_fecha_com_sucesso(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 1
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 1
    settings.LLM_CIRCUITO_RESET_SEGUNDOS = 10

    relogio = {"t": 1000.0}
    monkeypatch.setattr(llm.time, "monotonic", lambda: relogio["t"])

    chamadas = {"n": 0}

    def requisitar(*a, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise llm.LLMIndisponivel("500")
        return _resposta("recuperado")

    monkeypatch.setattr(llm, "_requisitar", requisitar)

    with pytest.raises(llm.LLMIndisponivel):
        llm.assistir(mode="summarize", logs="linha")
    assert llm.metricas()["circuito"]["estado"] == "open"

    relogio["t"] += 100  # venceu o repouso -> half-open
    assert llm.assistir(mode="summarize", logs="linha")["answer"] == "recuperado"
    assert llm.metricas()["circuito"]["estado"] == "closed"


def test_permitir_em_half_open_libera(settings):
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 1
    settings.LLM_CIRCUITO_RESET_SEGUNDOS = 0
    llm._CIRCUITO.registrar_falha()  # abre o circuito
    assert llm._CIRCUITO.permitir() is True  # repouso vencido -> half-open
    assert llm._CIRCUITO.permitir() is True  # já em half-open: tentativa em voo


def test_payload_invalido_nao_abre_circuito(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 1
    monkeypatch.setattr(
        llm, "_requisitar", lambda *a, **k: (_ for _ in ()).throw(llm.LLMPayloadInvalido("400"))
    )
    with pytest.raises(llm.LLMPayloadInvalido):
        llm.assistir(mode="summarize", logs="linha")
    assert llm.metricas()["circuito"]["estado"] == "closed"


def test_dormir_usa_sleep(monkeypatch):
    espera = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: espera.append(s))
    llm._dormir(0.01)
    assert espera == [0.01]


# --------------------------------------------------------------------------- #
# Telemetria e custo
# --------------------------------------------------------------------------- #
def test_telemetria_conta_sucesso(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_PRECO_PROMPT_USD_MILHAO = 1.0
    settings.LLM_PRECO_OUTPUT_USD_MILHAO = 1.0
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta(prompt=100, output=200))

    llm.assistir(mode="summarize", logs="linha")
    metricas = llm.metricas()

    assert metricas["chamadas"] == 1
    assert metricas["sucessos"] == 1
    assert metricas["erros"] == 0
    assert metricas["tokens_prompt"] == 100
    assert metricas["tokens_output"] == 200
    assert metricas["tokens_total"] == 300
    assert metricas["custo_total_usd"] == pytest.approx(0.0003)


def test_telemetria_conta_erro_e_taxa(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 1
    monkeypatch.setattr(
        llm, "_requisitar", lambda *a, **k: (_ for _ in ()).throw(llm.LLMTimeout("timeout"))
    )
    with pytest.raises(llm.LLMTimeout):
        llm.assistir(mode="summarize", logs="linha")

    metricas = llm.metricas()
    assert metricas["erros"] == 1
    assert metricas["taxa_erro"] == 1.0
    assert metricas["erros_por_tipo"] == {"LLMTimeout": 1}


def test_custo_estimado(settings):
    settings.LLM_PRECO_PROMPT_USD_MILHAO = 0.15
    settings.LLM_PRECO_OUTPUT_USD_MILHAO = 0.6
    esperado = (1000 / 1_000_000) * 0.15 + (2000 / 1_000_000) * 0.6
    assert llm._custo_estimado_usd(1000, 2000) == pytest.approx(esperado)


def test_resetar_metricas_zera_contadores(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta())
    llm.assistir(mode="summarize", logs="linha")
    llm.resetar_metricas()
    assert llm.metricas()["chamadas"] == 0


# --------------------------------------------------------------------------- #
# Fluxo do assistente
# --------------------------------------------------------------------------- #
def test_assistir_sem_api_key_falha(settings):
    settings.LLM_API_KEY = ""
    with pytest.raises(llm.LLMConfiguracaoAusente):
        llm.assistir(mode="summarize", logs="linha")


def test_assistir_modo_invalido_falha(settings):
    settings.LLM_API_KEY = "chave"
    with pytest.raises(llm.LLMPayloadInvalido):
        llm.assistir(mode="traduzir", logs="linha")


def test_assistir_devolve_answer_e_meta(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta("explicado", 7, 9))
    resultado = llm.assistir(mode="explain", logs=["a", "b"])
    assert resultado["answer"] == "explicado"
    assert resultado["meta"]["tokens_prompt"] == 7
    assert resultado["meta"]["tokens_output"] == 9
    assert "modelo" in resultado["meta"]


def test_status_http_por_tipo_de_erro():
    assert llm.LLMConfiguracaoAusente.status_http == 503
    assert llm.LLMCircuitoAberto.status_http == 503
    assert llm.LLMTimeout.status_http == 504
    assert llm.LLMTaxaLimitada.status_http == 429
    assert llm.LLMIndisponivel.status_http == 502
    assert llm.LLMPayloadInvalido.status_http == 400


# --------------------------------------------------------------------------- #
# Templates de prompt
# --------------------------------------------------------------------------- #
def test_normalizar_logs_string():
    assert prompts.normalizar_logs("linha") == "linha"


def test_normalizar_logs_lista():
    assert prompts.normalizar_logs(["a", "b"]) == "a\nb"


def test_montar_mensagens_usa_prompt_do_modo():
    mensagens = prompts.montar_mensagens(prompts.MODO_EXPLICAR, "erro X")
    assert mensagens[0]["role"] == "system"
    assert "EXPLICAR" in mensagens[0]["content"]
    assert mensagens[1]["content"].endswith("erro X")
