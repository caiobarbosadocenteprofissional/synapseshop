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
    """Pedido do cliente (Aulas 9 a 11 — pedido, pagamento e notificação).

    A API principal grava o pedido em ``PENDENTE`` e publica o evento
    ``PedidoCriado``; o ``worker`` consumidor avança o estado para
    ``PROCESSANDO``. Na Aula 11 o estado chega a ``PAGO`` (pagamento aprovado) ou
    ``CANCELADO`` (pagamento recusado), e a notificação do pagamento é gravada
    pelo ``notificacao-worker``. ``FALHA`` continua reservado para falha de
    processamento, que é um problema da infraestrutura e não do negócio.
    """

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        PROCESSANDO = "PROCESSANDO", "Processando"
        PAGO = "PAGO", "Pago"
        CANCELADO = "CANCELADO", "Cancelado"
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
    # Identificador que atravessa toda a cadeia (criação ➔ pagamento ➔
    # notificação) e permite correlacionar os logs dos três processos. É gerado
    # na criação do pedido; sem ele, cada evento teria um `correlation_id` novo
    # e não haveria como ligar "este pagamento" a "este pedido" nos logs.
    correlation_id = models.CharField(max_length=36, blank=True, default="")
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


class Pagamento(models.Model):
    """Pagamento simulado de um pedido (Aula 11 — fluxo do núcleo).

    A simulação acontece na API (não existe gateway externo): o endpoint recebe
    o desfecho desejado e o servidor o persiste como se fosse a resposta de um
    adquirente. O que importa para o fluxo é o **contrato** — um pagamento por
    pedido, com estado e valor congelados — e o evento ``PagamentoProcessado``
    que ele publica para a notificação.

    ``OneToOne`` e não ``ForeignKey``: a idempotência do pagamento é
    **estrutural**. Não existe segunda tentativa porque não existe segundo
    pagamento — repetir o pedido devolve o mesmo registro, sem novo evento.
    """

    class Status(models.TextChoices):
        APROVADO = "APROVADO", "Aprovado"
        RECUSADO = "RECUSADO", "Recusado"

    class Formas(models.TextChoices):
        CARTAO_CREDITO = "cartao_credito", "Cartão de crédito"
        CARTAO_DEBITO = "cartao_debito", "Cartão de débito"
        PIX = "pix", "Pix"
        BOLETO = "boleto", "Boleto"

    pedido = models.OneToOneField(
        Pedido,
        on_delete=models.CASCADE,
        related_name="pagamento",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.APROVADO,
    )
    # Valor congelado no momento do pagamento: o preço do pedido pode mudar no
    # catálogo depois, e o histórico financeiro não pode.
    valor = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    forma_pagamento = models.CharField(
        max_length=20,
        choices=Formas.choices,
        default=Formas.CARTAO_CREDITO,
    )
    # Referência da transação simulada. É única porque um pagamento ocupa o
    # lugar de uma transação real e duas transações não compartilham referência.
    referencia = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"], name="idx_pagamento_status")]

    def __str__(self):
        return f"Pagamento {self.pk} ({self.status})"

    @property
    def aprovado(self) -> bool:
        return self.status == self.Status.APROVADO


class Notificacao(models.Model):
    """Notificação enviada ao cliente sobre o pagamento (Aula 11).

    É gravada pelo ``notificacao-worker``, no lado consumidor do evento
    ``PagamentoProcessado``. O envio em si é simulado — o que se prova aqui é a
    etapa da cadeia, não a entrega de e-mail — e a linha no banco é a evidência
    de que o evento foi consumido.

    ``evento_origem`` guarda o ``event_id`` do evento que originou a
    notificação, com índice único: é uma segunda defesa contra notificação
    duplicada, independente da chave de deduplicação (que expira por TTL).
    """

    class Canais(models.TextChoices):
        EMAIL = "EMAIL", "E-mail"
        SMS = "SMS", "SMS"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.PROTECT,
        related_name="notificacoes",
    )
    pagamento = models.ForeignKey(
        Pagamento,
        on_delete=models.PROTECT,
        related_name="notificacoes",
    )
    destinatario = models.CharField(max_length=180)
    canal = models.CharField(
        max_length=10,
        choices=Canais.choices,
        default=Canais.EMAIL,
    )
    assunto = models.CharField(max_length=160)
    conteudo = models.TextField()
    evento_origem = models.CharField(max_length=36, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["canal", "-created_at"], name="idx_notificacao_canal")
        ]

    def __str__(self):
        return f"{self.canal} para {self.destinatario} (pedido {self.pedido_id})"


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
