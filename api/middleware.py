"""Coleta de métricas HTTP para o dashboard da Aula 20."""

from __future__ import annotations

import logging
from time import perf_counter

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from repositories.models import ApiRequestLog
from services.log_estruturado import LoggerEstruturado

logger = logging.getLogger("synapseshop.metricas")
log = LoggerEstruturado(logger)


def _deve_registrar(path: str) -> bool:
    return path == "/health" or path.startswith("/health/") or path.startswith("/api/")


class ApiRequestLogMiddleware:
    """Registra duração e status das rotas observáveis sem afetar a resposta.

    Uma falha ao gravar a amostra é registrada no log estruturado e ignorada: a
    indisponibilidade da tabela de métricas não pode derrubar a API de negócio.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(settings, "API_METRICS_ENABLED", False) or not _deve_registrar(
            request.path
        ):
            return self.get_response(request)

        inicio = perf_counter()
        status_code = 500
        try:
            response = self.get_response(request)
            status_code = response.status_code
            return response
        finally:
            duracao_ms = (perf_counter() - inicio) * 1000
            try:
                ApiRequestLog.objects.create(
                    method=request.method or "GET",
                    endpoint=request.path[:255],
                    status_code=status_code,
                    response_time_ms=round(duracao_ms, 3),
                )
            except Exception as exc:  # pragma: no cover - caminho de degradação
                log(
                    "metricas.falha_registro",
                    endpoint=request.path[:255],
                    erro=type(exc).__name__,
                )
