"""Dashboard de desempenho da API do SynapseShop (Aula 20).

As métricas vêm exclusivamente da tabela ``repositories_apirequestlog``, alimentada pelo
middleware ``ApiRequestLogMiddleware``. Não há dados sintéticos de fallback: se
a coleta estiver desligada ou a tabela vazia, o painel informa o operador.
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

STATUS_GROUPS = {
    "2xx (sucesso)": list(range(200, 300)),
    "3xx (redirecionamento)": list(range(300, 400)),
    "4xx (erro do cliente)": list(range(400, 500)),
    "5xx (erro do servidor)": list(range(500, 600)),
}


@st.cache_data(ttl=60)
def carregar_endpoints() -> list[str]:
    if execute_query is None:
        raise RuntimeError("Módulo db.py não pôde ser importado.")
    rows = execute_query(
        "SELECT DISTINCT endpoint FROM repositories_apirequestlog ORDER BY endpoint"
    )
    return [row["endpoint"] for row in rows]


@st.cache_data(ttl=60)
def carregar_metricas(
    data_inicial: date,
    data_final: date,
    endpoint: str,
    status_codes: tuple[int, ...],
) -> pd.DataFrame:
    if execute_query is None:
        raise RuntimeError("Módulo db.py não pôde ser importado.")

    sql = """
        SELECT method, endpoint, status_code, response_time_ms, created_at
        FROM repositories_apirequestlog
        WHERE created_at::date BETWEEN :data_inicial AND :data_final
    """
    params: dict[str, object] = {
        "data_inicial": data_inicial,
        "data_final": data_final,
    }
    if endpoint != "Todos":
        sql += " AND endpoint = :endpoint"
        params["endpoint"] = endpoint
    if status_codes:
        sql += " AND status_code = ANY(:status_codes)"
        params["status_codes"] = list(status_codes)
    sql += " ORDER BY created_at DESC LIMIT 50000"
    return pd.DataFrame(execute_query(sql, params))


st.set_page_config(page_title="SynapseShop - Desempenho da API", layout="wide")
st.title("SynapseShop - Desempenho da API")
st.caption("Métricas reais coletadas pelo middleware | cache de 60 s")

try:
    endpoints_disponiveis = carregar_endpoints()
except Exception as exc:
    st.error(f"Não foi possível consultar a tabela de métricas: {exc}")
    st.info(
        "Confirme se a migração 0005 foi aplicada e se API_METRICS_ENABLED=true."
    )
    st.stop()

with st.sidebar:
    st.header("Filtros")
    hoje = date.today()
    data_inicial = st.date_input("Data inicial", value=hoje - timedelta(days=7))
    data_final = st.date_input("Data final", value=hoje)
    endpoint = st.selectbox(
        "Endpoint",
        options=["Todos", *endpoints_disponiveis],
        index=0,
    )
    status_labels = st.multiselect(
        "Faixa de status",
        options=list(STATUS_GROUPS),
        default=list(STATUS_GROUPS),
    )

status_codes = tuple(
    codigo for label in status_labels for codigo in STATUS_GROUPS[label]
)

try:
    df = carregar_metricas(data_inicial, data_final, endpoint, status_codes)
except Exception as exc:
    st.error(f"Não foi possível carregar as métricas: {exc}")
    st.stop()

if df.empty:
    st.info(
        "Nenhuma métrica encontrada. Gere tráfego na API ou ajuste os filtros; "
        "o painel não inventa dados de fallback."
    )
    st.stop()

df["created_at"] = pd.to_datetime(df["created_at"])
df["response_time_ms"] = pd.to_numeric(df["response_time_ms"], errors="coerce")
df["status_code"] = pd.to_numeric(df["status_code"], errors="coerce").astype("Int64")

total = len(df)
latencia_media = df["response_time_ms"].mean()
latencia_p95 = df["response_time_ms"].quantile(0.95)
taxa_erro = (df["status_code"] >= 400).mean() * 100

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Requisições", f"{total:,}".replace(",", "."))
kpi2.metric("Latência média", f"{latencia_media:.1f} ms")
kpi3.metric("Latência p95", f"{latencia_p95:.1f} ms")
kpi4.metric("Taxa de erro", f"{taxa_erro:.1f}%")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("Throughput por dia")
    por_dia = (
        df.assign(dia=df["created_at"].dt.date)
        .groupby("dia")
        .size()
        .rename("requisicoes")
    )
    st.line_chart(por_dia)

with col2:
    st.subheader("Latência média por dia")
    latencia_dia = (
        df.assign(dia=df["created_at"].dt.date)
        .groupby("dia")["response_time_ms"]
        .mean()
        .rename("latencia_ms")
    )
    st.line_chart(latencia_dia)

st.divider()

col3, col4 = st.columns(2)
with col3:
    st.subheader("Distribuição por status")
    por_status = df.groupby("status_code").size().rename("requisicoes")
    st.bar_chart(por_status)

with col4:
    st.subheader("Top endpoints")
    top_endpoints = (
        df.groupby("endpoint")
        .size()
        .sort_values(ascending=False)
        .head(10)
        .rename("requisicoes")
    )
    st.bar_chart(top_endpoints)

st.divider()
st.subheader("Amostras coletadas")
tabela = df[["created_at", "method", "endpoint", "status_code", "response_time_ms"]].copy()
tabela["created_at"] = tabela["created_at"].dt.strftime("%d/%m/%Y %H:%M:%S")
tabela["response_time_ms"] = tabela["response_time_ms"].round(1)
st.dataframe(tabela, use_container_width=True, hide_index=True)
st.caption("Até 50.000 amostras por consulta; reduza o período para detalhar.")
