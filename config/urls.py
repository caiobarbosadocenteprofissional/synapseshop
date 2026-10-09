from django.urls import include, path

from api.docs import openapi_spec, redoc, swagger_ui
from api.views import health, health_pronto

# Aula 11: `/health` é liveness (o Compose reinicia o contêiner quando ela falha)
# e `/health/pronto` é readiness (200/503 conforme as dependências). Ficam na raiz,
# fora de `/api/v1`, porque são rotas de infraestrutura — não pertencem ao recurso.
# Aula 13: `/docs/` e `/docs/redoc/` são as interfaces de documentação e
# `/openapi.yaml` serve o contrato da raiz para elas e para validadores externos.
urlpatterns = [
    path("health", health, name="health"),
    path("health/pronto", health_pronto, name="health_pronto"),
    path("docs/", swagger_ui, name="swagger_ui"),
    path("docs/redoc/", redoc, name="redoc"),
    path("openapi.yaml", openapi_spec, name="openapi_spec"),
    path("api/v1/", include("api.urls")),
]
