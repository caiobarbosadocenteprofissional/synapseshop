# =====================================================================
# IMAGEM ÚNICA DA CASA — estratégia de multistage build
#
# Dois serviços, uma receita: a API Django (e os dois workers, que usam a
# mesma imagem e só trocam o comando) e o microsserviço de inventário
# (FastAPI). O que muda entre eles é o **contexto de build**, o **arquivo de
# dependências** e o **comando de entrada** — e os três chegam por `ARG`.
#
# O que não muda fica aqui, com uma fonte só: build em duas etapas, instalação
# offline a partir de wheels, usuário não-root e `PYTHONUNBUFFERED`. Duas
# cópias do mesmo Dockerfile divergem: a do inventário já estava sem o
# `PYTHONDONTWRITEBYTECODE`, por exemplo.
#
# Uso:
#   docker build -t synapseshop:dev .                          # API Django
#   docker build -t synapseshop-inventory:dev ./inventory \
#       -f ../Dockerfile                                        # inventário
# O `docker-compose.yml` faz as duas coisas.
# =====================================================================
FROM python:3.12-slim AS builder

# Arquivo de dependências, relativo ao contexto de build.
ARG REQUIREMENTS=requirements.txt

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /deps

# Cache de dependências: o requirements.txt é copiado ANTES do código.
# Enquanto ele não mudar, o Docker reaproveita a camada do pip wheel
# mesmo que o código da aplicação seja alterado.
COPY ${REQUIREMENTS} .

# Gera os wheels das dependências apenas nesta etapa (builder).
# Pacotes que precisam de compilação ficam isolados aqui e não
# "vazam" ferramentas de build para a imagem final.
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# =====================================================================
# ESTÁGIO 2: runtime — imagem final enxuta que executa a aplicação.
# =====================================================================
FROM python:3.12-slim AS runtime

ARG REQUIREMENTS=requirements.txt
ARG PORT=8000
ARG APP_CMD="python manage.py migrate --noinput && python manage.py seed_demo_users && python manage.py runserver 0.0.0.0:8000"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_CMD="${APP_CMD}"

# Usuário não-root para execução segura do container.
RUN useradd --create-home appuser

WORKDIR /app

COPY ${REQUIREMENTS} ./

# Copia somente os wheels prontos do builder e instala off-line
# (sem index, sem ferramentas de build na imagem final).
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Código da aplicação (copiado por último: preserva o cache de dependências).
COPY . .

# Garante ownership adequado para o usuário não-root.
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE ${PORT}

CMD ["sh", "-c", "$APP_CMD"]
