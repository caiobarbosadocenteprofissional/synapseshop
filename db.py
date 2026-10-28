"""
Módulo de conexão segura com o banco de dados (Aula 19).

- Usa SQLAlchemy com pooling, timeouts e SSL/TLS obrigatório quando configurado.
- Todas as credenciais são lidas via variáveis de ambiente.
- Fornece helpers para execução de consultas parametrizadas (SEM interpolação de strings).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Variáveis de ambiente (padronizadas para Aula 19)
DB_HOST = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB", "synapseshop")
DB_USER = os.getenv("DB_USER") or os.getenv("POSTGRES_USER", "synapseshop")
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "synapseshop")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")


def _build_database_url() -> str:
    """Constrói URL de conexão PostgreSQL com SQLAlchemy."""
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    return (
        f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


def create_secure_engine() -> Engine:
    """Cria engine SQLAlchemy com pooling, timeouts e SSL/TLS."""
    url = _build_database_url()
    connect_args: Dict[str, Any] = {}
    # Exigir SSL/TLS quando em PostgreSQL
    if url.startswith("postgresql"):
        connect_args = {
            "sslmode": DB_SSLMODE,
            "connect_timeout": 10,
        }
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        connect_args=connect_args,
    )
    return engine


# Engine singleton para uso compartilhado
engine = create_secure_engine()


def execute_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Executa consulta SQL PARAMETRIZADA com bind parameters.
    NUNCA interpolate strings diretamente nesta função.
    """
    if params is None:
        params = {}
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        # Se não houver resultado (INSERT/UPDATE/DELETE), retorna lista vazia
        if result.returns_rows:
            rows = [dict(row._mapping) for row in result]
            return rows
        return []


def fetch_dataframe(sql: str, params: Optional[Dict[str, Any]] = None):
    """Retorna DataFrame pandas a partir de consulta parametrizada."""
    try:
        import pandas as pd
    except Exception as exc:
        raise ImportError("pandas é necessário para fetch_dataframe") from exc
    rows = execute_query(sql, params)
    return pd.DataFrame(rows)


# Allow-list para ordenação dinâmica segura (evita SQL Injection via ORDER BY)
ALLOWED_ORDER_COLUMNS = {"id", "created_at", "updated_at", "status", "total", "nome", "name", "price"}
ALLOWED_ORDER_DIRECTIONS = {"ASC", "DESC", "asc", "desc"}


def build_order_clause(order_by: Optional[str] = None, order_dir: Optional[str] = None) -> str:
    """
    Constrói cláusula ORDER BY segura usando allow-list.
    Nunca interpolar valores arbitrários do usuário.
    """
    if not order_by or order_by not in ALLOWED_ORDER_COLUMNS:
        return ""
    direction = (order_dir or "ASC").upper()
    if direction not in ALLOWED_ORDER_DIRECTIONS:
        direction = "ASC"
    return f"ORDER BY {order_by} {direction}"
