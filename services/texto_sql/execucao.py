"""Execução read-only do SQL validado (Aula 21)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, connection, transaction

from services.texto_sql.erros import SqlInvalido


def _jsonificavel(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (dt.datetime, dt.date, dt.time)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return bytes(valor).decode("utf-8", errors="replace")
    return valor


def executar_sql(sql: str, *, max_linhas: int, timeout_ms: int) -> dict:
    """Executa a consulta validada e devolve colunas/linhas/truncamento.

    O LIMIT é aplicado por fora, numa subconsulta, para que a IA não consiga
    contornar o teto com um ``LIMIT`` maior. Em PostgreSQL a transação ainda é
    marcada como ``READ ONLY`` e recebe ``statement_timeout``.
    """
    limite = max(1, int(max_linhas))
    consulta = f"SELECT * FROM ({sql}) AS ask_sql_result LIMIT {limite + 1}"

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                cursor.execute(consulta)
                colunas = [coluna[0] for coluna in cursor.description or []]
                linhas = cursor.fetchall()
    except DatabaseError as exc:
        raise SqlInvalido(f"Falha ao executar a consulta: {exc}") from exc

    truncado = len(linhas) > limite
    linhas = linhas[:limite]
    return {
        "columns": colunas,
        "rows": [[_jsonificavel(valor) for valor in linha] for linha in linhas],
        "count": len(linhas),
        "truncated": truncado,
    }
