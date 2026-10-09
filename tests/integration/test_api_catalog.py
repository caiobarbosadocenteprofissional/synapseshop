"""Integração: ciclo de vida completo de categorias e itens na API.

Cada teste cobre o ciclo POST ➔ GET ➔ (atualização) ➔ DELETE com os reflexos
no banco e os status codes corretos. Os testes que provocam invalidação de
cache executam os callbacks de ``on_commit`` (via
``django_capture_on_commit_callbacks``), do mesmo modo que o servidor real
executaria depois do commit.
"""

import pytest

from repositories.models import Category, Item

pytestmark = pytest.mark.django_db


def test_sem_autenticacao_lista_categorias_401(api_client):
    assert api_client.get("/api/v1/categories/").status_code in (401, 403)


def test_usuario_comum_nao_escreve_categorias(authenticated_client):
    resposta = authenticated_client.post(
        "/api/v1/categories/", {"name": "Proibida"}, format="json"
    )
    assert resposta.status_code == 403


@pytest.mark.integration
def test_categoria_lifecycle_completo(admin_client):
    criacao = admin_client.post(
        "/api/v1/categories/", {"name": "Livros", "description": "d"}, format="json"
    )
    assert criacao.status_code == 201
    categoria_id = criacao.json()["id"]

    consulta = admin_client.get(f"/api/v1/categories/{categoria_id}/")
    assert consulta.status_code == 200
    assert consulta.json()["name"] == "Livros"

    atualizacao = admin_client.patch(
        f"/api/v1/categories/{categoria_id}/", {"name": "Livros novos"}, format="json"
    )
    assert atualizacao.status_code == 200
    assert Category.objects.get(pk=categoria_id).name == "Livros novos"

    remocao = admin_client.delete(f"/api/v1/categories/{categoria_id}/")
    assert remocao.status_code == 204
    assert not Category.objects.filter(pk=categoria_id).exists()


@pytest.mark.integration
def test_item_lifecycle_completo_com_cache(
    admin_client, categoria, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        criacao = admin_client.post(
            "/api/v1/items/",
            {"name": "Mouse", "price": "50.00", "category": categoria.pk},
            format="json",
        )
    assert criacao.status_code == 201
    item_id = criacao.json()["id"]
    assert Item.objects.filter(pk=item_id, is_active=True).exists()

    # Listagem: MISS no primeiro acesso, HIT no segundo.
    primeira = admin_client.get("/api/v1/items/")
    assert primeira.status_code == 200
    assert primeira.headers["X-Cache"] == "MISS"
    segunda = admin_client.get("/api/v1/items/")
    assert segunda.headers["X-Cache"] == "HIT"

    # Detalhe: MISS, depois HIT.
    detalhe1 = admin_client.get(f"/api/v1/items/{item_id}/")
    assert detalhe1.status_code == 200
    assert detalhe1.headers["X-Cache"] == "MISS"
    detalhe2 = admin_client.get(f"/api/v1/items/{item_id}/")
    assert detalhe2.headers["X-Cache"] == "HIT"

    # Atualização invalida o detalhe em cache (callback de on_commit executa).
    with django_capture_on_commit_callbacks(execute=True):
        admin_client.patch(
            f"/api/v1/items/{item_id}/", {"name": "Mouse novo"}, format="json"
        )
    detalhe3 = admin_client.get(f"/api/v1/items/{item_id}/")
    assert detalhe3.headers["X-Cache"] == "MISS"

    with django_capture_on_commit_callbacks(execute=True):
        remocao = admin_client.delete(f"/api/v1/items/{item_id}/")
    assert remocao.status_code == 204
    assert not Item.objects.filter(pk=item_id).exists()
    assert admin_client.get(f"/api/v1/items/{item_id}/").status_code == 404


@pytest.mark.integration
def test_filtros_de_listagem_de_itens(db, admin_client, categoria, item_factory):
    from repositories.models import Category

    _outra_categoria = Category.objects.create(
        name="Outra", description="Outra categoria de teste"
    )
    item_factory(name="Ativo", is_active=True)
    item_factory(name="Inativo", is_active=False)
    item_factory(name="De Outra", is_active=True, category=_outra_categoria)

    resposta = admin_client.get("/api/v1/items/?is_active=false")
    assert resposta.status_code == 200
    nomes = [linha["name"] for linha in resposta.json()["results"]]
    assert "Inativo" in nomes
    assert "Ativo" not in nomes

    resposta = admin_client.get(f"/api/v1/items/?category={categoria.pk}")
    assert resposta.status_code == 200
    nomes = [linha["name"] for linha in resposta.json()["results"]]
    assert {"Ativo", "Inativo"} <= set(nomes)
    assert "De Outra" not in nomes


def test_usuario_comum_nao_escreve_itens(authenticated_client, categoria):
    resposta = authenticated_client.post(
        "/api/v1/items/",
        {"name": "Proibido", "price": "1.00", "category": categoria.pk},
        format="json",
    )
    assert resposta.status_code == 403