"""Comandos de demo (``seed_demo_users`` e ``seed_demo_catalog``) executáveis."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from repositories.models import Category, Item

pytestmark = pytest.mark.integration

User = get_user_model()


def test_seed_demo_users_cria_admin_e_user(db):
    call_command("seed_demo_users")

    admin = User.objects.get(username="admin")
    user = User.objects.get(username="user")
    assert admin.role == User.Roles.ADMIN
    assert admin.is_staff is True
    assert user.role == User.Roles.USER


def test_seed_demo_users_e_idempotente(db):
    call_command("seed_demo_users")
    call_command("seed_demo_users")
    assert User.objects.count() == 2


def test_seed_demo_catalog_popula_categorias_e_itens(db):
    call_command("seed_demo_catalog", "--categories", "2", "--count", "3")

    assert Category.objects.count() == 2
    assert Item.objects.count() == 3
    assert Item.objects.filter(is_active=True).count() >= 1