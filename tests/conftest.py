"""Fixtures globais da suíte (Aula 12).

Concentra a infraestrutura de teste que os casos reutilizam:

- **cliente HTTP** — ``APIClient`` do DRF e variações autenticadas (usuário
  comum e admin);
- **banco efémero** — a fixture ``db`` do pytest-django, ativada pelas fixtures
  que gravam registros, com SQLite em memória definido em ``settings_test``;
- **relógio fixo** — ``freezegun`` para que timestamps e TTLs sejam
  determinísticos (a suíte não depende do relógio da máquina);
- **mocks/fakes de serviços externos** — um ``FakeRedis`` para os índices de
  invalidação e *fakes* de produtor para os cenários de broker disponível e
  indisponível. Nenhum teste toca Redis, Kubernetes ou broker de verdade.
"""

from collections import defaultdict
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache as django_cache
from freezegun import freeze_time
from rest_framework.test import APIClient


# --------------------------------------------------------------------------- #
# Isolamento entre testes
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _limpa_cache():
    """Zera o cache em memória antes e depois de cada teste.

    O ``LocMemCache`` é por processo e vazaria estado (contadores de métricas,
    respostas cacheadas, throttling) de um teste para o outro.
    """
    django_cache.clear()
    yield
    django_cache.clear()


# --------------------------------------------------------------------------- #
# Aplicação de teste e cliente HTTP
# --------------------------------------------------------------------------- #
@pytest.fixture
def api_client():
    """Cliente HTTP sem autenticação."""
    return APIClient()


@pytest.fixture
def user_model():
    return get_user_model()


# --------------------------------------------------------------------------- #
# Usuários e clientes autenticados
# --------------------------------------------------------------------------- #
@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="admin",
        email="admin@synapseshop.com",
        password="admin123",
        role=User.Roles.ADMIN,
    )


@pytest.fixture
def usuario(db):
    User = get_user_model()
    return User.objects.create_user(
        username="cliente",
        email="cliente@synapseshop.com",
        password="pass123",
        role=User.Roles.USER,
    )


@pytest.fixture
def outro_usuario(db):
    User = get_user_model()
    return User.objects.create_user(
        username="outro",
        email="outro@synapseshop.com",
        password="pass123",
        role=User.Roles.USER,
    )


@pytest.fixture
def authenticated_client(api_client, usuario):
    api_client.force_authenticate(user=usuario)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


def _autenticar(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def client_for():
    """Fábrica de clientes autenticados: ``client_for(usuario)``."""
    return _autenticar


# --------------------------------------------------------------------------- #
# Relógio fixo
# --------------------------------------------------------------------------- #
@pytest.fixture
def freezer():
    """Congela o relógio em 2026-10-07T12:00:00 para resultados determinísticos."""
    with freeze_time("2026-10-07 12:00:00") as frozen:
        yield frozen


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #
@pytest.fixture
def categoria(db):
    from repositories.models import Category

    return Category.objects.create(name="Eletrônicos", description="Categoria de teste")


@pytest.fixture
def item(db, categoria):
    from repositories.models import Item

    return Item.objects.create(
        name="Fone Bluetooth",
        description="Fone de teste",
        price=Decimal("199.90"),
        category=categoria,
        is_active=True,
    )


@pytest.fixture
def item_factory(db, categoria):
    from repositories.models import Item

    contador = {"n": 0}

    def criar(**kwargs):
        contador["n"] += 1
        defaults = {
            "name": f"Item {contador['n']}",
            "price": Decimal("10.00"),
            "category": categoria,
            "is_active": True,
        }
        defaults.update(kwargs)
        return Item.objects.create(**defaults)

    return criar


# --------------------------------------------------------------------------- #
# Pedidos
# --------------------------------------------------------------------------- #
@pytest.fixture
def pedido(db, usuario, item):
    from repositories.models import Pedido, PedidoItem

    pedido = Pedido.objects.create(
        usuario=usuario,
        total=item.price * 2,
        idempotency_key="pedido-fixture-1",
        correlation_id="11111111-1111-1111-1111-111111111111",
    )
    PedidoItem.objects.create(
        pedido=pedido,
        item=item,
        quantidade=2,
        preco_unitario=item.price,
    )
    return pedido


# --------------------------------------------------------------------------- #
# Fakes de serviços externos
# --------------------------------------------------------------------------- #
class FakeRedis:
    """Cliente Redis em memória para os índices de invalidação do cache.

    Reproduz só a superfície usada por ``services.cache`` (``INCR``, ``SADD``,
    ``SMEMBERS``, ``SREM`` e ``DELETE``), o que permite exercitar a
    invalidação sem um Redis real.
    """

    def __init__(self):
        self.sets = defaultdict(set)
        self.counters = defaultdict(int)
        self.deletados = []

    def incr(self, chave):
        self.counters[chave] += 1
        return self.counters[chave]

    def sadd(self, chave, valor):
        self.sets[chave].add(valor)
        return 1

    def smembers(self, chave):
        return set(self.sets.get(chave, set()))

    def srem(self, chave, valor):
        self.sets.get(chave, set()).discard(valor)

    def delete(self, chave):
        self.deletados.append(chave)
        self.sets.pop(chave, None)
        self.counters.pop(chave, None)


@pytest.fixture
def fake_redis(monkeypatch):
    """Substitui o cliente Redis do cache por ``FakeRedis`` (só quando ativo)."""
    from services import cache as cache_service

    fake = FakeRedis()
    monkeypatch.setattr(
        cache_service,
        "_redis",
        lambda: fake if cache_service.cache_ativo() else None,
    )
    return fake


class FakeProdutorEvento:
    """Produtor de eventos em memória: registra o que foi "publicado"."""

    publicados = []

    def __init__(self, topologia, client_id="synapseshop-api"):
        self.topologia = topologia
        self.client_id = client_id

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def publicar(self, evento, idempotency_key, **kwargs):
        FakeProdutorEvento.publicados.append(
            {"evento": evento, "idempotency_key": idempotency_key, "topologia": self.topologia}
        )
        return (0, 0)


class ProdutorEventoIndisponivel:
    """Produtor que simula o broker fora do ar."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def publicar(self, *args, **kwargs):
        from services.messaging import MensageriaIndisponivel

        raise MensageriaIndisponivel("broker indisponivel (fake)")


@pytest.fixture
def broker_disponivel(monkeypatch, settings):
    """Liga a mensageria e troca o produtor por um fake em memória."""
    settings.MESSAGERIA_ENABLED = True
    FakeProdutorEvento.publicados = []
    monkeypatch.setattr("services.publicacao.ProdutorEvento", FakeProdutorEvento)
    return FakeProdutorEvento.publicados


@pytest.fixture
def broker_indisponivel(monkeypatch, settings):
    """Liga a mensageria e faz toda publicação falhar (broker fora do ar)."""
    settings.MESSAGERIA_ENABLED = True
    monkeypatch.setattr(
        "services.publicacao.ProdutorEvento", ProdutorEventoIndisponivel
    )
    return ProdutorEventoIndisponivel


@pytest.fixture
def sem_cache(settings):
    """Desliga o cache-aside (kill-switch ``CACHE_ENABLED=false``)."""
    settings.CACHE_ENABLED = False
    return settings
