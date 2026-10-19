from django.http import JsonResponse

from services import health as health_service


def health(request):
    """Liveness: responde enquanto o processo conseguir atender a requisição.

    É deliberadamente superficial — o Compose reinicia a API quando esta rota
    falha, então ela não pode depender de nada externo. Quem verifica as
    dependências de verdade é ``GET /health/pronto``.
    """
    return JsonResponse({"status": "ok"})


def health_pronto(request):
    """Readiness: PostgreSQL, Redis e broker respondendo? 200 ou 503.

    Distinguir as duas rotas evita o pior modo de falha do Compose: com a
    readiness atrelada ao liveness, o Redis cair faria o contêiner da API ser
    reiniciado em laço — a API não tem culpa e o reinício não conserta o Redis.
    """
    relatorio = health_service.verificar()
    status = 200 if relatorio["pronto"] else 503
    return JsonResponse(relatorio, status=status)
