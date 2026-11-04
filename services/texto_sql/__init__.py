"""Texto-para-SQL: prompt, validação e execução read-only (Aula 21)."""

from __future__ import annotations

from django.conf import settings

from services import llm as llm_service
from services.llm.redacao import redigir
from services.prompts import montar_mensagens_sql
from services.texto_sql.erros import SqlInseguro, SqlInvalido, TextoSqlErro
from services.texto_sql.execucao import executar_sql
from services.texto_sql.extracao import extrair_sql
from services.texto_sql.schema import descrever_schema
from services.texto_sql.seguranca import validar_sql


def responder(pergunta: str) -> dict:
    """Traduz a pergunta em SQL, valida a política e executa a leitura."""
    pergunta_redigida, redacoes = redigir(pergunta)
    mensagens = montar_mensagens_sql(descrever_schema(), pergunta_redigida)
    resposta = llm_service.completar(
        mensagens=mensagens,
        temperature=getattr(settings, "ASK_SQL_TEMPERATURE", 0.0),
        max_tokens=getattr(settings, "ASK_SQL_MAX_TOKENS", 512),
        operacao="texto_sql",
    )

    sql = extrair_sql(resposta["conteudo"])
    sql = validar_sql(sql)
    resultado = executar_sql(
        sql,
        max_linhas=getattr(settings, "ASK_SQL_MAX_LINHAS", 200),
        timeout_ms=getattr(settings, "ASK_SQL_TIMEOUT_MS", 5000),
    )
    return {
        "question": pergunta,
        "sql": sql,
        **resultado,
        "meta": {**resposta["meta"], "redacoes": redacoes},
    }


__all__ = [
    "SqlInseguro",
    "SqlInvalido",
    "TextoSqlErro",
    "descrever_schema",
    "executar_sql",
    "extrair_sql",
    "responder",
    "validar_sql",
]
