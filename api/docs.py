"""Documentação navegável da API (Aula 13).

Serve o contrato ``openapi.yaml`` da raiz e duas interfaces que o consomem:

- ``/docs/``        -> Swagger UI (try-it-out)
- ``/docs/redoc/``  -> ReDoc (leitura)
- ``/openapi.yaml`` -> o próprio contrato, para clientes e validadores

As interfaces carregam Swagger UI e ReDoc de CDN (versões fixadas) para não
adicionar dependências de terceiros ao ``requirements.txt`` — a Aula 13 é sobre
documentar o contrato, não sobre instalar mais um pacote. As views são funções
Django puras, fora do DRF, então a documentação é pública mesmo com
``DEFAULT_PERMISSION_CLASSES = IsAuthenticated``.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound

SWAGGER_UI_VERSION = "5.17.14"
REDOC_VERSION = "2.1.5"

#: Caminho do contrato na raiz do projeto (``settings.BASE_DIR``). Fica fora de
#: ``docs/`` de propósito: ``.dockerignore`` exclui ``docs/`` da imagem, então o
#: contrato precisa estar na raiz para acompanhar o deploy.
OPENAPI_PATH = Path(settings.BASE_DIR) / "openapi.yaml"

_CABECALHO_SWAGGER = """<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SynapseShop API - Swagger UI</title>
  <link rel="stylesheet"
        href="https://unpkg.com/swagger-ui-dist@__VERSAO__/swagger-ui.css" />
  <style>body { margin: 0; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@__VERSAO__/swagger-ui-bundle.js"></script>
  <script>
    window.addEventListener("load", function () {
      window.ui = SwaggerUIBundle({
        url: "/openapi.yaml",
        dom_id: "#swagger-ui",
        deepLinking: true,
        displayOperationId: true,
        filter: true
      });
    });
  </script>
</body>
</html>
"""

_CABECALHO_REDOC = """<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SynapseShop API - ReDoc</title>
  <style>body { margin: 0; }</style>
</head>
<body>
  <redoc spec-url="/openapi.yaml"></redoc>
  <script src="https://unpkg.com/redoc@__VERSAO__/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


def swagger_ui(request):
    """Renderiza o Swagger UI apontando para o ``openapi.yaml`` local."""
    return HttpResponse(
        _CABECALHO_SWAGGER.replace("__VERSAO__", SWAGGER_UI_VERSION)
    )


def redoc(request):
    """Renderiza o ReDoc apontando para o ``openapi.yaml`` local."""
    return HttpResponse(_CABECALHO_REDOC.replace("__VERSAO__", REDOC_VERSION))


def openapi_spec(request):
    """Devolve o arquivo ``openapi.yaml`` como ``application/yaml``.

    É a fonte de verdade servida em runtime: as interfaces consomem esta rota e
    validadores externos podem buscá-la sem acesso ao repositório.
    """
    if not OPENAPI_PATH.exists():
        return HttpResponseNotFound(
            "openapi.yaml não encontrado na raiz do projeto."
        )
    return HttpResponse(
        OPENAPI_PATH.read_text(encoding="utf-8"),
        content_type="application/yaml; charset=utf-8",
    )
