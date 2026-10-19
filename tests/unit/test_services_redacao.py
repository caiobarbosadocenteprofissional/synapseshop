"""Testes de redação de PII/segredos (Aula 14).

A privacidade é o ponto sensível do assistente: o texto dos logs sai da nossa
infraestrutura em direção a um provedor externo. Estes testes garantem que
e-mail, CPF/CNPJ, cartão, telefone e segredos são substituídos **antes** do envio
e que o log de auditoria guarda a contagem — nunca o dado.
"""

import json
import logging

import pytest

from services import llm

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _estado_limpo():
    llm.resetar_metricas()
    llm.redefinir_circuito()
    yield
    llm.resetar_metricas()
    llm.redefinir_circuito()


@pytest.mark.parametrize(
    "entrada,valor,marcador",
    [
        ("contato joao@example.com agora", "joao@example.com", "[EMAIL_REDIGIDO]"),
        ("cliente com CPF 123.456.789-09", "123.456.789-09", "[CPF_REDIGIDO]"),
        ("empresa CNPJ 12.345.678/0001-95", "12.345.678/0001-95", "[CNPJ_REDIGIDO]"),
        ("cartao 4111 1111 1111 1111", "4111 1111 1111 1111", "[CARTAO_REDIGIDO]"),
        ("telefone (11) 91234-5678", "(11) 91234-5678", "[TELEFONE_REDIGIDO]"),
        ("senha=abc123 na config", "abc123", "[SEGREDO_REDIGIDO]"),
        ("api_key: sk-teste-123", "sk-teste-123", "[SEGREDO_REDIGIDO]"),
        ("header Bearer abc.def.ghi", "abc.def.ghi", "[BEARER_REDIGIDO]"),
    ],
)
def test_redige_tipos_sensiveis(entrada, valor, marcador):
    texto, total = llm.redigir(entrada)
    assert marcador in texto
    assert total >= 1
    # O valor original não sobrevive no texto redigido.
    assert valor not in texto


def test_redige_multiplos_em_uma_linha():
    texto, total = llm.redigir("email a@b.com e CPF 111.222.333-44")
    assert total == 2
    assert "[EMAIL_REDIGIDO]" in texto
    assert "[CPF_REDIGIDO]" in texto


def test_texto_sem_pii_fica_intacto():
    entrada = "pedido id=42 criado com sucesso"
    texto, total = llm.redigir(entrada)
    assert texto == entrada
    assert total == 0


def test_redige_antes_de_enviar_ao_provedor(settings, monkeypatch):
    settings.LLM_API_KEY = "chave"
    capturado = {}

    def falso_post(url, payload, headers, timeout):
        capturado["payload"] = payload
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(llm, "_http_post_json", falso_post)

    resultado = llm.assistir(mode="summarize", logs="erro do cliente joao@example.com")

    corpo_enviado = json.dumps(capturado["payload"])
    assert "joao@example.com" not in corpo_enviado
    assert "[EMAIL_REDIGIDO]" in corpo_enviado
    assert resultado["meta"]["redacoes"] == 1


def test_log_de_auditoria_nao_contem_o_dado(settings, monkeypatch, caplog):
    settings.LLM_API_KEY = "chave"
    monkeypatch.setattr(
        llm,
        "_requisitar",
        lambda *a, **k: {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )

    with caplog.at_level(logging.INFO, logger="synapseshop.ia"):
        llm.assistir(mode="explain", logs="falha para maria@example.com")

    assert "maria@example.com" not in caplog.text
    assert "redacoes" in caplog.text
