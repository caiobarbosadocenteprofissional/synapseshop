from django.urls import include, path

from api.views import health, health_pronto

# Aula 11: `/health` é liveness (o Compose reinicia o contêiner quando ela falha)
# e `/health/pronto` é readiness (200/503 conforme as dependências). Ficam na raiz,
# fora de `/api/v1`, porque são rotas de infraestrutura — não pertencem ao recurso.
urlpatterns = [
    path("health", health, name="health"),
    path("health/pronto", health_pronto, name="health_pronto"),
    path("api/v1/", include("api.urls")),
]
