"""Painel analítico do SynapseShop (Aula 19).

Consultas exclusivamente parametrizadas via ``db.execute_query`` (SQLAlchemy
``text()`` + bind parameters), com cache de 60 segundos para proteger o banco.
O painel usa os dados reais de pedidos; não há massa sintética de fallback.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from db import execute_query
except Exception:
    execute_query = None

STATUS_PEDIDO = ["PENDENTE", "PROCESSANDO", "PAGO", "CANCELADO", "FALHA"]

st.set_page_config(page_title="SynapseShop - Painel de Dados", layout="wide")
st.title("SynapseShop - Painel de Dados")
st.caption("Pedidos e clientes | Consultas parametrizadas, cache e atualização em tempo real")


@st.cache_data(ttl=60)
def carregar_pedidos(
    data_inicial: date,
    data_final: date,
    status: tuple[str, ...],
    cliente: str,
) -> pd.DataFrame:
    if execute_query is None:
        raise RuntimeError("Módulo db.py não pôde ser importado.")

    sql = """
        SELECT
            p.id,
            u.username AS cliente,
            p.status,
            p.total,
            p.created_at
        FROM repositories_pedido AS p
        JOIN repositories_user AS u ON u.id = p.usuario_id
        WHERE p.created_at::date BETWEEN :data_inicial AND :data_final
    """
    params: dict[str, object] = {
        "data_inicial": data_inicial,
        "data_final": data_final,
    }

    if status:
        sql += " AND p.status = ANY(:statuses)"
        params["statuses"] = list(status)

    cliente = cliente.strip()
    if cliente:
        sql += " AND u.username ILIKE :cliente"
        params["cliente"] = f"%{cliente}%"

    sql += " ORDER BY p.created_at DESC LIMIT 500"
    return pd.DataFrame(execute_query(sql, params))


with st.sidebar:
    st.header("Filtros")
    hoje = date.today()
    data_inicial = st.date_input("Data inicial", value=hoje - timedelta(days=30))
    data_final = st.date_input("Data final", value=hoje)
    status_selecionados = st.multiselect(
        "Status do pedido",
        options=STATUS_PEDIDO,
        default=STATUS_PEDIDO,
    )
    cliente = st.text_input("Cliente (username)", value="")

try:
    df = carregar_pedidos(
        data_inicial,
        data_final,
        tuple(status_selecionados),
        cliente,
    )
except Exception as exc:
    st.error(f"Não foi possível consultar os pedidos: {exc}")
    st.info("Verifique a conexão PostgreSQL e as variáveis DB_* do serviço streamlit.")
    st.stop()

if df.empty:
    st.info("Nenhum pedido encontrado para os filtros selecionados.")
    st.stop()

df["created_at"] = pd.to_datetime(df["created_at"])
df["total"] = pd.to_numeric(df["total"], errors="coerce").fillna(0)

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Pedidos", f"{len(df):,}".replace(",", "."))
kpi2.metric("Receita", f"R$ {df['total'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
kpi3.metric("Ticket médio", f"R$ {df['total'].mean():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
kpi4.metric("Cancelados", int((df["status"] == "CANCELADO").sum()))

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("Pedidos por status")
    status_df = (
        df.groupby("status", as_index=False)
        .size()
        .rename(columns={"size": "pedidos"})
        .set_index("status")
    )
    st.bar_chart(status_df)

with col2:
    st.subheader("Pedidos por dia")
    por_dia = df.assign(dia=df["created_at"].dt.date).groupby("dia").size()
    st.line_chart(por_dia)

st.divider()
st.subheader("Pedidos encontrados")
tabela = df[["id", "cliente", "status", "total", "created_at"]].copy()
tabela["created_at"] = tabela["created_at"].dt.strftime("%d/%m/%Y %H:%M")
st.dataframe(tabela, use_container_width=True, hide_index=True)
st.caption("Limite de 500 pedidos por consulta; refine os filtros para ver outros resultados.")
