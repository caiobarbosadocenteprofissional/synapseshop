import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-synapseshop-change-me"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "repositories",
    "api",
]

# Modelo de usuário customizado com papéis (admin/user) da Aula 7.
AUTH_USER_MODEL = "repositories.User"

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Aula 7: PostgreSQL como camada de dados única do MVP (Camada 5 da arquitetura-alvo).
# O Compose já injeta POSTGRES_* no serviço `api` e o liga ao `postgres` via
# `depends_on: service_healthy`; fora do Docker o default é localhost, igual ao `inventory`.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "synapseshop"),
        "USER": os.environ.get("POSTGRES_USER", "synapseshop"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "synapseshop"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Aula 8: cache-aside com Redis (Camada 5 — Dados da arquitetura-alvo).
# O Compose provisiona o serviço `redis` e injeta REDIS_URL; `CACHE_ENABLED`
# permite desligar o cache sem mexer no código (A/B de desempenho).
# IGNORE_EXCEPTIONS mantém a API no PostgreSQL quando o Redis estiver fora do ar.
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
CACHE_TTL_LISTA = int(os.environ.get("CACHE_TTL_LISTA", "60"))
CACHE_TTL_DETALHE = int(os.environ.get("CACHE_TTL_DETALHE", "300"))

if CACHE_ENABLED:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
            "KEY_PREFIX": "synapseshop",
            "TIMEOUT": CACHE_TTL_LISTA,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": True,
                "SOCKET_CONNECT_TIMEOUT": 2,
                "SOCKET_TIMEOUT": 2,
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "synapseshop-cache-off",
        }
    }

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    # Aula 7: autenticação por JWT (Bearer) com usuários autenticados por padrão.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Throttling mínimo: escopos "anon" (convidados), "user" (autenticados)
    # e "login" (proteção contra força bruta nas rotas de token).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("THROTTLE_ANON", "20/min"),
        "user": os.environ.get("THROTTLE_USER", "200/min"),
        "login": os.environ.get("THROTTLE_LOGIN", "5/min"),
    },
    # Paginação coerente nos endpoints críticos.
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "PAGE_SIZE_QUERY_PARAM": "page_size",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_TOKEN_MINUTES", "60"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_TOKEN_DAYS", "7"))
    ),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# Aula 9: mensageria assíncrona com RabbitMQ (Camada 5 — Dados & Mensageria).
# O Compose provisiona o serviço `rabbitmq` e injeta RABBITMQ_*; o mesmo bloco
# é lido pela API (produtor) e pelo `pedido-worker` (consumidor).
# MENSAGERIA_ENABLED é o kill-switch: com `false` o pedido é gravado e nenhum
# evento é publicado, o que permite medir o custo da sincronia ponta a ponta.
MESSAGERIA_ENABLED = os.environ.get("MESSAGERIA_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")
RABBITMQ_EXCHANGE = os.environ.get("RABBITMQ_EXCHANGE", "pedidos.events")
RABBITMQ_FILA_PEDIDO_CRIADO = os.environ.get(
    "RABBITMQ_FILA_PEDIDO_CRIADO", "pedidos.pedidocriado"
)
RABBITMQ_FILA_PEDIDO_CRIADO_DLQ = os.environ.get(
    "RABBITMQ_FILA_PEDIDO_CRIADO_DLQ", "pedidos.pedidocriado.dlq"
)
RABBITMQ_DLX = os.environ.get("RABBITMQ_DLX", "pedidos.dlx")
RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO = os.environ.get(
    "RABBITMQ_ROUTING_KEY_PEDIDO_CRIADO", "pedido.criado"
)
RABBITMQ_PREFETCH = int(os.environ.get("RABBITMQ_PREFETCH", "1"))

# Política de reentrega do consumidor: attempts = 1 + MAX_RETRIES. Depois de
# esgotar as tentativas a mensagem é morta (nack sem requeue) e o broker a
# encaminha para a DLQ através da dead-letter exchange.
MENSAGERIA_MAX_RETRIES = int(os.environ.get("MENSAGERIA_MAX_RETRIES", "3"))
MENSAGERIA_BACKOFF_BASE_MS = int(os.environ.get("MENSAGERIA_BACKOFF_BASE_MS", "250"))
MENSAGERIA_BACKOFF_MAX_MS = int(os.environ.get("MENSAGERIA_BACKOFF_MAX_MS", "5000"))

# Prazo de validade da chave de deduplicação (idempotência do consumidor).
IDEMPOTENCIA_TTL_SEGUNDOS = int(os.environ.get("IDEMPOTENCIA_TTL_SEGUNDOS", "86400"))

# Ganchos de teste para simular erro forçado e validar reentrega + DLQ sem
# alterar o código: padrões (fnmatch) de idempotency_key que o worker rejeita.
# Vazio em operação normal. Ex.: PEDIDO_WORKER_FALHA_IDEM_KEYS=pedido-dlq-*
PEDIDO_WORKER_FALHA_IDEM_KEYS = [
    padrao.strip()
    for padrao in os.environ.get("PEDIDO_WORKER_FALHA_IDEM_KEYS", "").split(",")
    if padrao.strip()
]

# Aula 8: logs estruturados (JSON) do ciclo de vida do cache e dos eventos de
# domínio. As mensagens já são JSON em services/, por isso o formatador é
# "%(message)s".
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "estruturado": {"format": "%(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "estruturado",
        },
    },
    "loggers": {
        "synapseshop": {
            "handlers": ["console"],
            "level": os.environ.get("LOG_LEVEL_SYNAPSESHOP", "INFO"),
            "propagate": False,
        },
    },
}
