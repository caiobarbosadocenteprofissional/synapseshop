"""Testes de integração de ``/api/v1/assist`` (Aula 14).

Exercitam a pilha completa (URL → view → serializer → ``services.llm``) com o
provedor de LLM sempre substituído por um mock: o que se verifica é o **contrato
HTTP** diante de cada modo de falha — 400 de validação, 429 de limite de taxa,
502 de provedor indisponível, 503 de serviço desabilitado/circuito aberto e 504
de timeout.
"""

import pytest

from services import llm

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _estado_limpo():
    llm.resetar_metricas()
    llm.redefinir_circuito()
    yield
    llm.resetar_metricas()
    llm.redefinir_circuito()


@pytest.fixture
def llm_configurado(settings):
    """Habilita o assistente com um único disparo (sem retry) para os testes."""
    settings.LLM_API_KEY = "chave-de-teste"
    settings.LLM_MAX_TENTATIVAS = 1
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 100
    return settings


def _resposta(conteudo="resumo dos logs", prompt=10, output=20):
    return {
        "choices": [{"message": {"content": conteudo}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


# --------------------------------------------------------------------------- #
# Autenticação e validação de entrada
# --------------------------------------------------------------------------- #
def test_assist_exige_autenticacao(api_client):
    resposta = api_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert resposta.status_code == 401


@pytest.mark.parametrize(
    "corpo",
    [
        {"mode": "traduzir", "logs": "x"},
        {"mode": "summarize", "logs": []},
        {"mode": "summarize", "logs": ["ok", 123]},
        {"mode": "summarize", "logs": {"nao": "texto"}},
        {"logs": "sem modo"},
        {"mode": "summarize", "logs": "x", "temperature": 5.0},
        {"mode": "summarize", "logs": "x", "max_tokens": 0},
    ],
)
def test_assist_valida_payload(authenticated_client, llm_configurado, corpo):
    resposta = authenticated_client.post("/api/v1/assist/", corpo, format="json")
    assert resposta.status_code == 400


def test_assist_rejeita_logs_vazios(authenticated_client, llm_configurado):
    resposta = authenticated_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "   "}, format="json"
    )
    assert resposta.status_code == 400


def test_assist_limita_max_tokens(authenticated_client, settings, llm_configurado):
    settings.LLM_MAX_TOKENS_LIMITE = 256
    resposta = authenticated_client.post(
        "/api/v1/assist/",
        {"mode": "summarize", "logs": "x", "max_tokens": 5000},
        format="json",
    )
    assert resposta.status_code == 400


# --------------------------------------------------------------------------- #
# Sucesso
# --------------------------------------------------------------------------- #
def test_assist_sucesso(authenticated_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta("tudo ok", 15, 25))

    resposta = authenticated_client.post(
        "/api/v1/assist/",
        {"mode": "summarize", "logs": "bruno@example.com falhou"},
        format="json",
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["answer"] == "tudo ok"
    assert corpo["meta"]["tokens_prompt"] == 15
    assert corpo["meta"]["tokens_output"] == 25
    assert corpo["meta"]["redacoes"] == 1


def test_assist_aceita_lista_de_logs(authenticated_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta())
    resposta = authenticated_client.post(
        "/api/v1/assist/",
        {"mode": "explain", "logs": ["linha 1", "linha 2"], "temperature": 0.5},
        format="json",
    )
    assert resposta.status_code == 200


# --------------------------------------------------------------------------- #
# Falhas do provedor mapeadas para status HTTP
# --------------------------------------------------------------------------- #
def _falhar_com(excecao):
    def requisitar(*a, **k):
        raise excecao

    return requisitar


def test_assist_429_vira_429(authenticated_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(
        llm, "_requisitar", _falhar_com(llm.LLMTaxaLimitada("rate limit"))
    )
    resposta = authenticated_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert resposta.status_code == 429


def test_assist_500_vira_502(authenticated_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(
        llm, "_requisitar", _falhar_com(llm.LLMIndisponivel("provedor fora"))
    )
    resposta = authenticated_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert resposta.status_code == 502


def test_assist_timeout_vira_504(authenticated_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(llm, "_requisitar", _falhar_com(llm.LLMTimeout("lento")))
    resposta = authenticated_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert resposta.status_code == 504


def test_assist_sem_api_key_vira_503(authenticated_client, settings):
    settings.LLM_API_KEY = ""
    resposta = authenticated_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert resposta.status_code == 503


def test_assist_circuito_aberto_vira_503(authenticated_client, settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    settings.LLM_MAX_TENTATIVAS = 1
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 1
    monkeypatch.setattr(
        llm, "_requisitar", _falhar_com(llm.LLMIndisponivel("provedor fora"))
    )
    payload = {"mode": "summarize", "logs": "x"}

    assert authenticated_client.post("/api/v1/assist/", payload, format="json").status_code == 502
    assert authenticated_client.post("/api/v1/assist/", payload, format="json").status_code == 503


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def test_stats_exige_admin(authenticated_client):
    assert authenticated_client.get("/api/v1/assist/stats/").status_code == 403


def test_stats_exige_autenticacao(api_client):
    assert api_client.get("/api/v1/assist/stats/").status_code == 401


def test_stats_devolve_metricas(admin_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta(prompt=5, output=7))
    admin_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )

    resposta = admin_client.get("/api/v1/assist/stats/")
    assert resposta.status_code == 200
    metricas = resposta.json()
    assert metricas["chamadas"] == 1
    assert metricas["tokens_total"] == 12
    assert metricas["circuito"]["estado"] == "closed"


def test_stats_post_zera_contadores(admin_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(llm, "_requisitar", lambda *a, **k: _resposta())
    admin_client.post(
        "/api/v1/assist/", {"mode": "summarize", "logs": "x"}, format="json"
    )
    assert admin_client.get("/api/v1/assist/stats/").json()["chamadas"] == 1

    resposta = admin_client.post("/api/v1/assist/stats/")
    assert resposta.status_code == 200
    assert resposta.json()["chamadas"] == 0
