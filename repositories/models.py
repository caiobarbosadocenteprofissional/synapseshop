from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models


class User(AbstractUser):
    """Usuário customizado com papéis distintos (Aula 7 — JWT por roles).

    Oferece os papéis ``admin`` e ``user``. Usuários ``admin`` também são
    marcados como ``is_staff``/``is_superuser`` via o papel nas rotas da API.
    """

    class Roles(models.TextChoices):
        ADMIN = "admin", "Admin"
        USER = "user", "User"

    role = models.CharField(
        max_length=10,
        choices=Roles.choices,
        default=Roles.USER,
    )

    class Meta:
        ordering = ["username"]


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Item(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="items",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Pedido(models.Model):
    """Pedido do cliente (Aula 9 —mensageria).

    A API principal grava o pedido em ``PENDENTE`` e publica o evento
    ``PedidoCriado``; o ``worker`` consumidor avança o estado para
    ``PROCESSANDO``. Apenas os estados necessários a esta aula existem —
    pagamento, notificação e conclusão são escopo das aulas seguintes.
    """

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        PROCESSANDO = "PROCESSANDO", "Processando"
        FALHA = "FALHA", "Falha"

    usuario = models.ForeignKey(
        "repositories.User",
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    idempotency_key = models.CharField(max_length=64, unique=True)
    processado_em = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["usuario", "-created_at"], name="idx_pedido_usuario"),
            models.Index(fields=["status"], name="idx_pedido_status"),
        ]

    def __str__(self):
        return f"Pedido {self.pk} ({self.status})"


class PedidoItem(models.Model):
    """Linha do pedido, com o preço congelado no momento da criação."""

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="itens_pedido",
    )
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preco_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "item"], name="uq_pedido_item_unico"
            )
        ]

    def __str__(self):
        return f"{self.quantidade}x {self.item_id} (pedido {self.pedido_id})"


class EventoProcessado(models.Model):
    """Chave de deduplicação de eventos, com prazo de validade (Aula 9).

    Gravada pelo consumidor **após** o processamento bem-sucedido: é o que
    impede que uma reentrega do mesmo ``PedidoCriado`` seja aplicada duas vezes.
    O Redis é o caminho rápido (chave com TTL); esta tabela é a fonte durável,
    necessária porque o cache é volátil (``allkeys-lru``) e configurado com
    ``IGNORE_EXCEPTIONS``.
    """

    evento = models.CharField(max_length=60)
    idempotency_key = models.CharField(max_length=64)
    processado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-processado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["evento", "idempotency_key"],
                name="uq_evento_processado_idem",
            )
        ]

    def __str__(self):
        return f"{self.evento}:{self.idempotency_key}"
