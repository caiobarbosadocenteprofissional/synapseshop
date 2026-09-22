# =====================================================================
# ESTRATÉGIA DE MULTISTAGE BUILD
# ESTÁGIO 1: builder — compila e prepara as dependências isoladamente.
# =====================================================================
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /deps

# Cache de dependências: o requirements.txt é copiado ANTES do código.
COPY requirements.txt .

RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# =====================================================================
# ESTÁGIO 2: runtime — imagem final enxuta que executa o FastAPI.
# =====================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Usuário não-root para execução segura do container.
RUN useradd --create-home appuser

WORKDIR /app

COPY requirements.txt ./

# Copia somente os wheels prontos do builder e instala off-line.
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Código da aplicação (copiado por último: preserva o cache).
COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8100

# No start, aplica as migrações de schema do Alembic (versionamento do
# banco PostgreSQL — Aula 6) e sobe o FastAPI na porta 8100.
CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8100"]