"""Configuração de settings para a suíte de testes (Aula 12).

Herdada de ``config.settings`` e sobrescrita apenas no que precisa ser
**isolado da infraestrutura** para que ``pytest`` rode em qualquer máquina
(sem PostgreSQL, Redis ou broker):

- **banco efémero** — SQLite em memória, criado e destruído por execução. A
  suíte nunca toca o PostgreSQL de desenvolvimento;
- **cache em memória** — ``LocMemCache`` no lugar do Redis, mantendo a mesma
  API do framework de cache do Django (``cache.get``/``cache.set``);
- **mensageria desligada** — nenhum evento é publicado e nenhum broker é
  contatado. Os testes que exercitam a publicação substituem o produtor por
  um *fake* em memória;
- **hashers rápidos** — o custo de hashing de senha é irrelevante para o que
  se está testando e domina o tempo de uma suíte com muitos logins.

Rodar com o settings de desenvolvimento apontaria para ``localhost`` e a
suíte passaria a medir a disponibilidade da infraestrutura, não o código.
"""

from config.settings import *  # noqa: F401,F403
from config.settings import REST_FRAMEWORK as _REST_FRAMEWORK

DEBUG = False

# Banco efémero: uma base vazia por execução, criada e destruída pelo pytest-django.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# O cache-aside continua ligado (o código sob teste depende disso), mas o backend
# é em processo — os índices de invalidação que dependem do Redis caem no caminho
# "cliente indisponível", que também é um caminho a cobrir.
CACHE_ENABLED = True
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synapseshop-tests",
    }
}

# Nenhum evento é publicado durante os testes por padrão; os cenários de
# publicação substituem explicitamente o produtor por um fake.
MESSAGERIA_ENABLED = False

# Hashing de senha rápido: o login é exercitado em vários testes de integração.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Throttling praticamente desligado: ele é uma defesa de produção e não o foco
# desta suíte; uma taxa alta evita 429 espúrio quando um teste faz login repetido.
REST_FRAMEWORK = {
    **_REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100000/min",
        "user": "100000/min",
        "login": "100000/min",
    },
}

# Silencia os logs estruturados durante a suíte: eles poluiriam a saída do
# pytest sem agregar ao resultado dos testes.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
    "loggers": {
        "synapseshop": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
    },
}
