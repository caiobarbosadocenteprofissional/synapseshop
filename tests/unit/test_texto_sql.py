"""Testes unitários da extração, schema e política SQL (Aula 21)."""

import pytest

from mock_llm import _gerar_sql
from services.texto_sql.erros import SqlInseguro
from services.texto_sql.extracao import extrair_sql
from services.texto_sql.schema import descrever_schema
from services.texto_sql.seguranca import validar_sql


@pytest.mark.parametrize(
    "resposta",
    [
        "SELECT id FROM repositories_pedido;",
        "```sql\nSELECT id FROM repositories_pedido;\n```",
        "SQL: SELECT id FROM repositories_pedido",
        "Aqui está:\nSELECT id FROM repositories_pedido\n",
    ],
)
def test_extrai_sql_de_formatos_comuns(resposta):
    assert extrair_sql(resposta).startswith("SELECT id")


def test_extrai_cte():
    sql = extrair_sql("```\nWITH x AS (SELECT id FROM repositories_user) SELECT id FROM x\n```")
    assert sql.startswith("WITH x")


@pytest.mark.parametrize("resposta", ["", "   ", "não consegui gerar"])
def test_extracao_rejeita_resposta_sem_sql(resposta):
    with pytest.raises(SqlInseguro):
        extrair_sql(resposta)


def test_schema_nao_expoe_colunas_sensiveis():
    schema = descrever_schema()
    assert "repositories_pedido" in schema
    assert "repositories_pedido.usuario_id = repositories_user.id" in schema
    assert "password" not in schema
    assert "email" not in schema


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT username FROM repositories_user LIMIT 5",
        "SELECT COUNT(*) AS total FROM repositories_pedido",
        "SELECT u.username, COUNT(p.id) AS total "
        "FROM repositories_user u JOIN repositories_pedido p "
        "ON p.usuario_id=u.id GROUP BY u.username ORDER BY total DESC LIMIT 5",
        "WITH x AS (SELECT id, total FROM repositories_pedido) "
        "SELECT id, total FROM x LIMIT 3",
        "SELECT SUM(total) AS soma FROM repositories_pedido",
    ],
)
def test_aceita_selects_de_leitura(sql):
    assert validar_sql(sql) == sql


@pytest.mark.parametrize(
    "pergunta",
    [
        "Quais usuários fizeram mais pedidos?",
        "Quais os 5 últimos usuários cadastrados?",
        "Qual a soma do valor dos últimos 3 pedidos?",
        "Pedidos por status",
        "Quais categorias têm mais itens?",
        "Pagamentos por status",
        "Quais itens foram mais vendidos?",
        "Mostre os pedidos recentes",
    ],
)
def test_mock_gera_sql_que_passa_pela_politica(pergunta):
    assert validar_sql(_gerar_sql(pergunta))


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM repositories_user",
        "UPDATE repositories_pedido SET total = 0",
        "DROP TABLE repositories_user",
        "SELECT password FROM repositories_user",
        "SELECT * FROM repositories_user",
        "SELECT id FROM information_schema.tables",
        "SELECT id FROM tabela_inexistente",
        "SELECT id FROM repositories_user; DROP TABLE repositories_user",
        "SELECT p.id FROM repositories_pedido p, tabela_inexistente s",
        "SELECT pg_sleep(10)",
        "SELECT id FROM repositories_user -- comentário",
        "SELECT p.id, p.campo_inexistente FROM repositories_pedido p",
        "SELECT DISTINCT ON (id) * FROM repositories_pedido",
        "SELECT nextval('repositories_pedido_id_seq')",
        "SELECT id FROM repositories_pedido FOR UPDATE",
        "SELECT id FROM repositories_pedido FOR KEY SHARE",
        "SELECT u FROM repositories_user u",
        "SELECT u::text FROM repositories_user u",
        "SELECT (u) FROM repositories_user u",
        "SELECT row_to_json(u) FROM repositories_user u",
        "SELECT to_jsonb(u) FROM repositories_user u",
        "SELECT json_agg(u) FROM repositories_user u",
        "SELECT array_agg(u) FROM repositories_user u",
        "SELECT hstore(u) FROM repositories_user u",
    ],
)
def test_bloqueia_sql_fora_da_politica(sql):
    with pytest.raises(SqlInseguro):
        validar_sql(sql)
