"""Schema de negócio exposto à LLM e allow-list do Texto-para-SQL (Aula 21).

A lista é explícita de propósito: refletir o banco automaticamente exporia
tabelas de autenticação, deduplicação e métricas. Só entram aqui as tabelas que
respondem perguntas de negócio, e cada tabela declara apenas as colunas que
podem aparecer no SQL gerado.
"""

from __future__ import annotations

from typing import Dict

TABELAS: Dict[str, Dict[str, object]] = {
    "repositories_user": {
        "descricao": "Usuários cadastrados (clientes e administradores).",
        "colunas": {
            "id": "bigint PK",
            "username": "varchar",
            "role": "varchar (admin|user)",
            "is_active": "boolean",
            "date_joined": "timestamptz",
        },
    },
    "repositories_category": {
        "descricao": "Categorias do catálogo.",
        "colunas": {
            "id": "bigint PK",
            "name": "varchar",
            "description": "text",
            "created_at": "timestamptz",
        },
    },
    "repositories_item": {
        "descricao": "Itens/produtos do catálogo.",
        "colunas": {
            "id": "bigint PK",
            "name": "varchar",
            "description": "text",
            "price": "numeric(10,2)",
            "category_id": "bigint FK -> repositories_category.id",
            "is_active": "boolean",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
        },
    },
    "repositories_pedido": {
        "descricao": "Pedidos realizados pelos usuários.",
        "colunas": {
            "id": "bigint PK",
            "usuario_id": "bigint FK -> repositories_user.id",
            "status": "varchar (PENDENTE|PROCESSANDO|PAGO|CANCELADO|FALHA)",
            "total": "numeric(12,2)",
            "processado_em": "timestamptz nullable",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
        },
    },
    "repositories_pedidoitem": {
        "descricao": "Itens de cada pedido, com preço congelado.",
        "colunas": {
            "id": "bigint PK",
            "pedido_id": "bigint FK -> repositories_pedido.id",
            "item_id": "bigint FK -> repositories_item.id",
            "quantidade": "integer",
            "preco_unitario": "numeric(10,2)",
        },
    },
    "repositories_pagamento": {
        "descricao": "Pagamento simulado de um pedido (um por pedido).",
        "colunas": {
            "id": "bigint PK",
            "pedido_id": "bigint FK -> repositories_pedido.id",
            "status": "varchar (APROVADO|RECUSADO)",
            "valor": "numeric(12,2)",
            "forma_pagamento": "varchar",
            "processado_em": "timestamptz nullable",
            "created_at": "timestamptz",
        },
    },
}

COLUNAS_SENSIVEIS = frozenset(
    {
        "password",
        "email",
        "first_name",
        "last_name",
        "last_login",
        "is_staff",
        "is_superuser",
        "groups",
        "user_permissions",
        "idempotency_key",
        "correlation_id",
        "referencia",
        "destinatario",
        "assunto",
        "conteudo",
        "evento_origem",
    }
)


def descrever_schema() -> str:
    """DDL/descrição enxuta para o prompt, sem colunas sensíveis."""
    linhas: list[str] = []
    for tabela, meta in TABELAS.items():
        linhas.append(f"Tabela {tabela} — {meta['descricao']}")
        for coluna, tipo in meta["colunas"].items():  # type: ignore[union-attr]
            linhas.append(f"  {coluna} {tipo}")
        linhas.append("")
    linhas.append(
        "Relações: repositories_pedido.usuario_id = repositories_user.id; "
        "repositories_pedidoitem.pedido_id = repositories_pedido.id; "
        "repositories_pedidoitem.item_id = repositories_item.id; "
        "repositories_pagamento.pedido_id = repositories_pedido.id; "
        "repositories_item.category_id = repositories_category.id."
    )
    return "\n".join(linhas)


def tabelas_permitidas() -> frozenset[str]:
    return frozenset(TABELAS)


def colunas_da_tabela(tabela: str) -> frozenset[str]:
    meta = TABELAS.get(tabela)
    if not meta:
        return frozenset()
    return frozenset(meta["colunas"])


def todas_as_colunas() -> frozenset[str]:
    return frozenset(
        coluna for meta in TABELAS.values() for coluna in meta["colunas"]
    )
