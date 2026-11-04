"""Integração do endpoint admin ``/api/v1/ask_sql/`` (Aula 21)."""

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
    settings.LLM_API_KEY = "chave-de-teste"
    settings.LLM_MAX_TENTATIVAS = 1
    settings.LLM_CIRCUITO_LIMITE_FALHAS = 100
    return settings


def _resposta(conteudo, prompt=10, output=20):
    return {
        "choices": [{"message": {"content": conteudo}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


def test_ask_sql_exige_autenticacao(api_client):
    resposta = api_client.post(
        "/api/v1/ask_sql/", {"question": "quais usuários?"}, format="json"
    )
    assert resposta.status_code == 401


@pytest.mark.django_db
def test_ask_sql_exige_admin(authenticated_client, llm_configurado):
    resposta = authenticated_client.post(
        "/api/v1/ask_sql/", {"question": "quais usuários?"}, format="json"
    )
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_ask_sql_sucesso(admin_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(
        llm,
        "_requisitar",
        lambda *a, **k: _resposta(
            "SELECT username FROM repositories_user ORDER BY id LIMIT 5"
        ),
    )

    resposta = admin_client.post(
        "/api/v1/ask_sql/",
        {"question": "Quais usuários existem?"},
        format="json",
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["question"] == "Quais usuários existem?"
    assert corpo["sql"].startswith("SELECT username")
    assert corpo["columns"] == ["username"]
    assert corpo["count"] >= 1
    assert corpo["rows"]
    assert corpo["truncated"] is False
    assert corpo["meta"]["tokens_prompt"] == 10


@pytest.mark.django_db
def test_ask_sql_trunca_resultado(
    admin_client, usuario, llm_configurado, monkeypatch, settings
):
    settings.ASK_SQL_MAX_LINHAS = 1
    monkeypatch.setattr(
        llm,
        "_requisitar",
        lambda *a, **k: _resposta(
            "SELECT username FROM repositories_user ORDER BY id LIMIT 5"
        ),
    )

    resposta = admin_client.post(
        "/api/v1/ask_sql/", {"question": "liste usuários"}, format="json"
    )

    assert resposta.status_code == 200
    assert resposta.json()["count"] == 1
    assert resposta.json()["truncated"] is True


@pytest.mark.django_db
def test_ask_sql_bloqueia_escrita(admin_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(
        llm,
        "_requisitar",
        lambda *a, **k: _resposta("DELETE FROM repositories_user"),
    )

    resposta = admin_client.post(
        "/api/v1/ask_sql/", {"question": "apague usuários"}, format="json"
    )

    assert resposta.status_code == 400
    assert resposta.json()["erro"] == "SqlInseguro"


@pytest.mark.django_db
def test_ask_sql_sql_invalido_vira_422(admin_client, llm_configurado, monkeypatch):
    monkeypatch.setattr(
        llm,
        "_requisitar",
        lambda *a, **k: _resposta(
            "SELECT coluna_inexistente FROM repositories_user"
        ),
    )

    resposta = admin_client.post(
        "/api/v1/ask_sql/", {"question": "liste algo"}, format="json"
    )

    assert resposta.status_code == 422
    assert resposta.json()["erro"] == "SqlInvalido"


@pytest.mark.django_db
def test_ask_sql_mapeia_erro_da_llm(admin_client, llm_configurado, monkeypatch):
    def falhar(*a, **k):
        raise llm.LLMTaxaLimitada("rate limit")

    monkeypatch.setattr(llm, "_requisitar", falhar)

    resposta = admin_client.post(
        "/api/v1/ask_sql/", {"question": "liste usuários"}, format="json"
    )

    assert resposta.status_code == 429


@pytest.mark.parametrize("corpo", [{}, {"question": ""}, {"question": "  "}, {"question": "a"}])
def test_ask_sql_valida_pergunta(admin_client, llm_configurado, corpo):
    resposta = admin_client.post("/api/v1/ask_sql/", corpo, format="json")
    assert resposta.status_code == 400
