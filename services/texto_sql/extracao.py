"""Extração da instrução SQL da resposta textual da LLM (Aula 21)."""

from __future__ import annotations

import re

from services.texto_sql.erros import SqlInseguro

_BLOCO_CERCADO = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_INICIO_SQL = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)
_ROTULO = re.compile(r"^\s*(?:SQL|Query|Consulta)\s*:\s*", re.IGNORECASE)


def extrair_sql(resposta: str) -> str:
    """Devolve apenas a instrução, removendo cercas markdown e rótulos.

    O modelo pode devolver `` ```sql ... ``` ``, ``SQL: SELECT ...`` ou texto
    explicativo antes da query. A extração é deliberadamente tolerante, mas
    **não** tenta corrigir SQL inválido: isso é papel do validador.
    """
    texto = (resposta or "").strip().lstrip("\ufeff")
    if not texto:
        raise SqlInseguro("A LLM não retornou nenhuma instrução SQL.")

    bloco = _BLOCO_CERCADO.search(texto)
    if bloco:
        texto = bloco.group(1).strip()

    texto = _ROTULO.sub("", texto).strip()
    inicio = _INICIO_SQL.search(texto)
    if not inicio:
        raise SqlInseguro("A resposta da LLM não contém SELECT ou WITH.")
    texto = texto[inicio.start() :].strip()

    texto = texto.rstrip().rstrip(";").strip()
    if not texto:
        raise SqlInseguro("A LLM não retornou nenhuma instrução SQL.")
    return texto
