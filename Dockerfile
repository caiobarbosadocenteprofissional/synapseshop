# =====================================================================
# ESTRATÉGIA DE MULTISTAGEBUILD
# ESTÁGIO 1: builder — compila e prepara as dependências isoladamente.
# =====================================================================
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /deps

# Cache de dependências: o requirements.txt é copiado ANTES do código.
# Enquanto ele não mudar, o Docker reaproveita a camada do pip wheel
# mesmo que o código da aplicação seja alterado.
COPY requirements.txt .

# Gera os wheels das dependências apenas nesta etapa (builder).
# Pacotes que precisam de compilação ficam isolados aqui e não
# "vazam" ferramentas de build para a imagem final.
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# =====================================================================
# ESTÁGIO 2: runtime — imagem final enxuta que executa a aplicação.
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

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo_users && python manage.py runserver 0.0.0.0:8000"]