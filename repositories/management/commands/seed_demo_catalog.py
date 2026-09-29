"""Comando idempotente que popula o catálogo de itens do SynapseShop (Aula 8).

Existindo para dar volume realista às medições de desempenho exigidas pelo DoD
da Aula 8 (latência média, p95 e RPS antes e depois da introdução do cache),
uma vez que o catálogo real do MVP ainda é Reduced. Não é exigido pelo fluxo
de negócio: apenas cria dados de demonstração de forma repetível.

Uso típico dentro do contêiner da API:

    python manage.py seed_demo_catalog --categories 5 --count 300
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from repositories.models import Category, Item

CATEGORY_NAMES = [
    "Audio",
    "Computadores",
    "Dispositivos Movelis",
    "Gamers",
    "Smart TV",
    "Smartphones",
    "Tablets",
]

ITEM_ADJECTIVES = [
    "Pro",
    "Max",
    "Plus",
    "Air",
    "Mini",
    "Ultra",
    "Studio",
    "Lite",
]

ITEM_CATEGORIES = {
    "Audio": ["Fone Bluetooth", "Caixa de Som", "Headset Gamer"],
    "Computadores": ["Notebook", "Desktop", "Mini PC"],
    "Dispositivos Movelis": ["Powerbank", "Carregador Turbo", "Cabo USB-C"],
    "Gamers": ["Controle Sem Fio", "Mouse Gamer", "Teclado Mecanico"],
    "Smart TV": ["Smart TV", "Chromecast", "Projetor"],
    "Smartphones": ["Smartphone", "Capa Proteetora", "SuporteVeiculo"],
    "Tablets": ["Tablet", "Caneta Digitizadora", "Capa para Tablet"],
}


class Command(BaseCommand):
    help = "Popula o catálogo (categorias e itens) de forma idempotente (Aula 8)."

    def add_arguments(self, parser):
        parser.add_argument("--categories", type=int, default=5)
        parser.add_argument("--count", type=int, default=300)

    @transaction.atomic
    def handle(self, *args, **options):
        categories_qty = max(1, options["categories"])
        items_qty = max(1, options["count"])

        categories = []
        for index in range(categories_qty):
            name = CATEGORY_NAMES[index % len(CATEGORY_NAMES)]
            category, _ = Category.objects.get_or_create(
                name=name,
                defaults={"description": f"Categoria {name} (seed demo)"},
            )
            categories.append(category)
        self.stdout.write(f"Categorias disponíveis: {len(categories)}")

        created_items = 0
        for index in range(items_qty):
            category = categories[index % len(categories)]
            base = ITEM_CATEGORIES.get(category.name, ["Produto"])[index % 3]
            variant = ITEM_ADJECTIVES[(index // 3) % len(ITEM_ADJECTIVES)]
            name = f"{base} {variant} {index + 1:04d}"
            price = Decimal("99.90") + Decimal(index) * Decimal("7.50")
            _, created = Item.objects.get_or_create(
                name=name,
                defaults={
                    "description": f"Produto de demonstracao {index + 1}",
                    "price": price,
                    "category": category,
                    "is_active": index % 10 != 0,
                },
            )
            if created:
                created_items += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Itens criados: {created_items} (total no catalogo: "
                f"{Item.objects.count()})."
            )
        )
