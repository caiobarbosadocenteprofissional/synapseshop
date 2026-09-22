"""Microsserviço de inventário (FastAPI) — Pacote `app`.

Endpoints estruturados com tipagem estática, modelos Pydantic e respostas
padrão. Desde a Aula 6 os dados são persistidos no PostgreSQL via
SQLAlchemy + Alembic (camada relacional transacional).
"""

from __future__ import annotations