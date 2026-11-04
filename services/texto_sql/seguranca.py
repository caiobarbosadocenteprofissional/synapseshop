"""Política de segurança do SQL gerado pela LLM (Aula 21).

A defesa é em camadas: extração de uma única instrução, allow-list de tabelas e
colunas, bloqueio de palavras/funções perigosas, remoção de wildcard e, na
execução, transação PostgreSQL read-only com ``statement_timeout``. Nenhuma
camada sozinha é suficiente; juntas reduzem o risco de uma alucinação virar
mutação ou exfiltração.
"""

from __future__ import annotations

import re

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, TokenList
from sqlparse.tokens import Comment, Keyword, Name, Wildcard

from services.texto_sql.erros import SqlInseguro
from services.texto_sql.schema import (
    COLUNAS_SENSIVEIS,
    TABELAS,
    colunas_da_tabela,
    tabelas_permitidas,
)

_PALAVRAS_PROIBIDAS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|"
    r"COPY|VACUUM|CALL|MERGE|REPLACE|ATTACH|DETACH|PRAGMA|EXECUTE|PREPARE|"
    r"DEALLOCATE|LISTEN|NOTIFY|SET|RESET|SHOW|LOCK|DO|INTO|RETURNING|"
    r"BEGIN|COMMIT|ROLLBACK|FOR\s+(?:(?:NO\s+)?KEY\s+)?(?:UPDATE|SHARE))\b",
    re.IGNORECASE,
)
_FUNCOES_PROIBIDAS = re.compile(
    r"\b(?:pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|"
    r"lo_import|lo_export|dblink|current_setting|set_config|"
    r"pg_terminate_backend|pg_cancel_backend|pg_reload_conf|"
    r"pg_rotate_logfile|pg_create_restore_point|pg_switch_wal|pg_promote|"
    r"pg_start_backup|pg_stop_backup|nextval|setval|row_to_json|to_json|"
    r"to_jsonb|json_agg|jsonb_agg|array_agg|hstore|json_build_array|"
    r"jsonb_build_array|json_build_object|jsonb_build_object|"
    r"json_object_agg|jsonb_object_agg)\s*\(",
    re.IGNORECASE,
)
_SCHEMAS_PROIBIDOS = re.compile(
    r"\b(?:information_schema|pg_catalog|pg_toast|pg_temp)\b", re.IGNORECASE
)
_WILDCARD = re.compile(
    r"(?:\bSELECT\s+(?:DISTINCT\s+)?\*)|(?:,\s*\*)|(?:\b\w+\.\*)",
    re.IGNORECASE,
)


def _mascarar_literais(sql: str) -> str:
    """Troca strings por ``''`` para não confundir palavras dentro de literais."""
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def _coletar_ctes(tokens: list, indice: int, ctes: set[str]) -> None:
    for token in tokens[indice:]:
        if isinstance(token, IdentifierList):
            for identificador in token.get_identifiers():
                if isinstance(identificador, Identifier) and identificador.get_real_name():
                    ctes.add(identificador.get_real_name().lower())
            return
        if isinstance(token, Identifier) and token.get_real_name():
            ctes.add(token.get_real_name().lower())
            return
        if token.ttype is Keyword and token.normalized.upper() == "RECURSIVE":
            continue
        if token.is_whitespace or token.ttype in Comment:
            continue
        return


def _registrar_fonte(
    token, ctes: set[str], tabelas: set[str], aliases: dict[str, str]
) -> None:
    if isinstance(token, IdentifierList):
        for identificador in token.get_identifiers():
            _registrar_fonte(identificador, ctes, tabelas, aliases)
        return
    if isinstance(token, Identifier):
        real = (token.get_real_name() or "").lower()
        alias = (token.get_alias() or "").lower()
        if real:
            tabelas.add(real)
            aliases[real] = real
        if alias and real:
            aliases[alias] = real
        for filho in token.tokens:
            if isinstance(filho, Parenthesis):
                _coletar_fontes(filho, ctes, tabelas, aliases)
        return
    if isinstance(token, Parenthesis):
        _coletar_fontes(token, ctes, tabelas, aliases)
        return
    if token.ttype in Name:
        nome = token.value.lower()
        tabelas.add(nome)
        aliases[nome] = nome


def _coletar_fontes(
    token_list: TokenList,
    ctes: set[str],
    tabelas: set[str],
    aliases: dict[str, str],
) -> None:
    tokens = [
        token
        for token in token_list.tokens
        if not token.is_whitespace and token.ttype not in Comment
    ]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        normalizado = token.normalized.upper()
        if token.ttype in Keyword.CTE or normalizado == "WITH":
            _coletar_ctes(tokens, i + 1, ctes)
        if token.ttype is Keyword and (
            normalizado == "FROM" or normalizado.endswith("JOIN")
        ):
            j = i + 1
            while (
                j < len(tokens)
                and tokens[j].ttype is Keyword
                and tokens[j].normalized.upper() in ("ONLY", "LATERAL")
            ):
                j += 1
            if j < len(tokens):
                _registrar_fonte(tokens[j], ctes, tabelas, aliases)
                i = j
        elif token.is_group:
            _coletar_fontes(token, ctes, tabelas, aliases)
        i += 1


def _identificadores(token_list: TokenList):
    for token in token_list.tokens:
        if isinstance(token, Identifier):
            yield token
        if token.is_group:
            yield from _identificadores(token)


def _tem_select(token: TokenList) -> bool:
    return any(
        filho.ttype is Keyword.DML and filho.normalized.upper() == "SELECT"
        for filho in token.flatten()
    )


def _validar_nomes_compostos(tokens: list, aliases: dict[str, str]) -> None:
    """Rejeita projetar uma linha inteira (``SELECT u``, ``(u)`` ou ``u::text``)."""
    achatados = []
    for token in tokens:
        if token.is_group and _tem_select(token):
            continue
        achatados.extend(token.flatten() if token.is_group else [token])
    achatados = [token for token in achatados if not token.is_whitespace]
    anterior = None
    for indice, token in enumerate(achatados):
        seguinte = achatados[indice + 1] if indice + 1 < len(achatados) else None
        if token.ttype in Name:
            nome = token.value.strip('"').lower()
            qualificado = seguinte is not None and seguinte.value == "."
            alias_de_saida = (
                anterior is not None and anterior.normalized.upper() == "AS"
            )
            if nome in aliases and not qualificado and not alias_de_saida:
                raise SqlInseguro(
                    "Projete colunas explícitas; selecionar a linha inteira "
                    "não é permitido."
                )
        anterior = token


def _validar_projecao(statement: TokenList, aliases: dict[str, str]) -> None:
    tokens = [
        token
        for token in statement.tokens
        if not token.is_whitespace and token.ttype not in Comment
    ]
    for indice, token in enumerate(tokens):
        if token.is_group and _tem_select(token):
            _validar_projecao(token, aliases)
        if token.ttype is Keyword.DML and token.normalized.upper() == "SELECT":
            projecao = []
            for filho in tokens[indice + 1 :]:
                if filho.ttype is Keyword and filho.normalized.upper() in (
                    "FROM",
                    "UNION",
                    "EXCEPT",
                    "INTERSECT",
                ):
                    break
                projecao.append(filho)
            _validar_nomes_compostos(projecao, aliases)


def _validar_colunas(statement: TokenList, aliases: dict[str, str]) -> None:
    for identificador in _identificadores(statement):
        real = (identificador.get_real_name() or "").lower()
        parent = (identificador.get_parent_name() or "").lower()
        if not real:
            continue
        if real in COLUNAS_SENSIVEIS:
            raise SqlInseguro(f"Coluna sensível não permitida: {real}.")
        if not parent:
            continue
        tabela = aliases.get(parent)
        if tabela and tabela in TABELAS:
            if real not in colunas_da_tabela(tabela):
                raise SqlInseguro(
                    f"Coluna '{real}' não pertence à tabela permitida '{tabela}'."
                )


def _validar_wildcards(statement: TokenList) -> None:
    """Permite ``COUNT(*)``, mas bloqueia ``*`` como coluna (inclusive ``p.*``)."""
    tokens = [token for token in statement.flatten() if not token.is_whitespace]
    for indice, token in enumerate(tokens):
        if token.ttype is not Wildcard:
            continue
        anterior = tokens[indice - 1] if indice >= 1 else None
        antes_do_anterior = tokens[indice - 2] if indice >= 2 else None
        if (
            anterior is not None
            and anterior.value == "("
            and antes_do_anterior is not None
            and antes_do_anterior.normalized.upper() == "COUNT"
        ):
            continue
        raise SqlInseguro("SELECT * não é permitido; informe as colunas desejadas.")


def validar_sql(sql: str) -> str:
    """Valida a política e devolve o SQL normalizado (sem ``;`` final)."""
    texto = (sql or "").strip()
    if texto.endswith(";"):
        texto = texto[:-1].rstrip()
    if not texto:
        raise SqlInseguro("SQL vazio.")

    mascarado = _mascarar_literais(texto)
    if ";" in mascarado:
        raise SqlInseguro("Apenas uma instrução SQL é permitida.")
    if "--" in mascarado or "/*" in mascarado or "*/" in mascarado:
        raise SqlInseguro("Comentários SQL não são permitidos.")
    if "$$" in mascarado:
        raise SqlInseguro("Strings com dollar-quote não são permitidas.")

    statements = [stmt for stmt in sqlparse.parse(texto) if str(stmt).strip()]
    if len(statements) != 1:
        raise SqlInseguro("Apenas uma instrução SQL é permitida.")
    statement = statements[0]
    if statement.get_type() != "SELECT":
        raise SqlInseguro("Apenas consultas SELECT são permitidas.")

    _validar_wildcards(statement)
    palavra_proibida = _PALAVRAS_PROIBIDAS.search(mascarado)
    if palavra_proibida:
        raise SqlInseguro(
            f"Comando não permitido: {palavra_proibida.group(0).upper()}."
        )
    funcao_proibida = _FUNCOES_PROIBIDAS.search(mascarado)
    if funcao_proibida:
        raise SqlInseguro(f"Função não permitida: {funcao_proibida.group(0)}.")
    if _SCHEMAS_PROIBIDOS.search(mascarado):
        raise SqlInseguro("Schemas de sistema não são permitidos.")
    if _WILDCARD.search(mascarado):
        raise SqlInseguro("SELECT * não é permitido; informe as colunas desejadas.")

    ctes: set[str] = set()
    tabelas: set[str] = set()
    aliases: dict[str, str] = {}
    _coletar_fontes(statement, ctes, tabelas, aliases)

    nao_permitidas = (tabelas - ctes) - set(tabelas_permitidas())
    if nao_permitidas:
        nomes = ", ".join(sorted(nao_permitidas))
        raise SqlInseguro(f"Tabela(s) não permitida(s): {nomes}.")

    _validar_colunas(statement, aliases)
    _validar_projecao(statement, aliases)
    return texto
