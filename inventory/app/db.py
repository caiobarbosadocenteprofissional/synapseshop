"""Configuração do SQLAlchemy para o microsserviço de inventário (Aula 6).

Estabelece a conexão transacional com o PostgreSQL por meio do driver
`psycopg` e expõe o `engine`, a fábrica de sessões (`SessionLocal`) e a
dependency `get_session` usada pelo FastAPI.

A URL de conexão é montada a partir das variáveis `POSTGRES_*`
padrão do orquestrador, reconciliando com a convenção já usada pela API
principal (Aula 3). A variável `DATABASE_URL`, se fornecida, tem
prioridade.
"""

from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "synapseshop")
POSTGRES_USER = os.getenv("POSTGRES_USER", "synapseshop")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "synapseshop")


def database_url() -> str:
    """Devolve a URL de conexão (prioridade para `DATABASE_URL` explícita)."""
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    return (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


engine = create_engine(database_url(), pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base declarativa dos modelos ORM do inventário."""


def get_session() -> Generator[Session, None, None]:
    """Dependency do FastAPI: abre uma sessão, injeta nos endpoints e fecha."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()