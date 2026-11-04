"""Painel Streamlit do SynapseShop (Aulas 19 a 21).

Aba 1: desempenho real da API, lido de ``repositories_apirequestlog``.
Aba 2: consulta em linguagem natural, admin-only, via ``POST /api/v1/ask_sql/``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
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

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")

STATUS_GROUPS = {
    "2xx (sucesso)": list(range(200, 300)),
    "3xx (redirecionamento)": list(range(300, 400)),
    "4xx (erro do cliente)": list(range(400, 500)),
    "5xx (erro do servidor)": list(range(500, 600)),
}


class ApiError(RuntimeError):
    def __init__(self, mensagem: str, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


def _api_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
    timeout: int = 45,
) -> dict:
    dados = None
    if payload is not None:
        dados = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    requisicao = urllib.request.Request(
        f"{API_BASE_URL}{path}", data=dados, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("detail", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise ApiError(str(detalhe), exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"API indisponível: {exc.reason}") from exc


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


def _render_login() -> None:
    with st.sidebar:
        st.header("Acesso à API")
        if st.session_state.get("access_token"):
            st.success(
                f"{st.session_state.get('username', 'admin')} "
                f"({st.session_state.get('role', '?')})"
            )
            if st.button("Sair"):
                for chave in ("access_token", "role", "username"):
                    st.session_state.pop(chave, None)
                st.rerun()
            return

        with st.form("login_api"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar")
        if not entrar:
            return
        try:
            dados = _api_request(
                "/api/v1/auth/token/",
                method="POST",
                payload={"username": username, "password": password},
                timeout=15,
            )
        except ApiError as exc:
            st.error(f"Falha no login: {exc}")
            return
        st.session_state["access_token"] = dados["access"]
        st.session_state["role"] = dados.get("role", "user")
        st.session_state["username"] = username
        st.rerun()


def _render_desempenho() -> None:
    try:
        endpoints_disponiveis = carregar_endpoints()
    except Exception as exc:
        st.error(f"Não foi possível consultar a tabela de métricas: {exc}")
        st.info(
            "Confirme se a migração 0005 foi aplicada e se API_METRICS_ENABLED=true."
        )
        return

    with st.sidebar:
        st.divider()
        st.header("Filtros de desempenho")
        hoje = date.today()
        data_inicial = st.date_input("Data inicial", value=hoje - timedelta(days=7))
        data_final = st.date_input("Data final", value=hoje)
        endpoint = st.selectbox(
            "Endpoint", options=["Todos", *endpoints_disponiveis], index=0
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
        return

    if df.empty:
        st.info(
            "Nenhuma métrica encontrada. Gere tráfego na API ou ajuste os filtros; "
            "o painel não inventa dados de fallback."
        )
        return

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
        st.bar_chart(df.groupby("status_code").size().rename("requisicoes"))
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
    tabela = df[
        ["created_at", "method", "endpoint", "status_code", "response_time_ms"]
    ].copy()
    tabela["created_at"] = tabela["created_at"].dt.strftime("%d/%m/%Y %H:%M:%S")
    tabela["response_time_ms"] = tabela["response_time_ms"].round(1)
    st.dataframe(tabela, use_container_width=True, hide_index=True)
    st.caption("Até 50.000 amostras por consulta; reduza o período para detalhar.")


def _render_ask_sql() -> None:
    st.subheader("Consulta em linguagem natural")
    st.caption(
        "Admin-only: a pergunta é traduzida em SQL read-only e executada no "
        "PostgreSQL. O SQL gerado e o resultado ficam visíveis para auditoria."
    )

    token = st.session_state.get("access_token")
    if not token:
        st.info("Entre com um usuário admin na barra lateral para usar esta aba.")
        return
    if st.session_state.get("role") != "admin":
        st.warning("Esta aba é restrita ao papel admin.")
        return

    with st.form("ask_sql"):
        pergunta = st.text_area(
            "Pergunta de negócio",
            placeholder="Ex.: quais usuários fizeram mais pedidos?",
            height=100,
        )
        enviar = st.form_submit_button("Consultar", type="primary")

    if not enviar:
        return
    if not pergunta.strip():
        st.error("Digite uma pergunta.")
        return

    try:
        resultado = _api_request(
            "/api/v1/ask_sql/",
            method="POST",
            payload={"question": pergunta.strip()},
            token=token,
            timeout=90,
        )
    except ApiError as exc:
        if exc.status == 401:
            st.session_state.pop("access_token", None)
            st.error("Sessão expirada; faça login novamente.")
        else:
            st.error(f"A consulta falhou: {exc}")
        return

    st.markdown("**SQL gerado**")
    st.code(resultado.get("sql", ""), language="sql")
    st.caption(
        f"Linhas: {resultado.get('count', 0)} | "
        f"truncado: {'sim' if resultado.get('truncated') else 'não'} | "
        f"latência LLM: {resultado.get('meta', {}).get('latencia_ms', '?')} ms"
    )
    linhas = resultado.get("rows") or []
    colunas = resultado.get("columns") or []
    if linhas and colunas:
        st.dataframe(
            pd.DataFrame(linhas, columns=colunas),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("A consulta não retornou linhas.")


st.set_page_config(page_title="SynapseShop - Painel", layout="wide")
st.title("SynapseShop - Painel")
_render_login()

aba_desempenho, aba_consulta = st.tabs(
    ["Desempenho da API", "Consulta em Linguagem Natural"]
)
with aba_desempenho:
    _render_desempenho()
with aba_consulta:
    _render_ask_sql()
