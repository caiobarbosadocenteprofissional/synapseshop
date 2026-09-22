"""Ambiente de migração do Alembic para o inventário.

Usa o `engine` já configurado em `app.db` (com a URL proveniente das
variáveis `POSTGRES_*`/`DATABASE_URL`) e o metadata dos modelos ORM
(`app.models`), permitindo tanto `upgrade`/`downgrade` quanto
`revision --autogenerate`.
"""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  — registra os modelos no metadata
from app.db import Base, database_url, engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Executa as migrações no modo offline (gera o SQL, sem conectar)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa as migrações conectado ao banco (modo online padrão)."""
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()