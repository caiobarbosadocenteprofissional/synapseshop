"""Garante que o contrato OpenAPI não divirja das rotas reais da API."""

import pytest

from scripts.validar_openapi import (
    CAMINHO_OPENAPI,
    OpenAPIInvalido,
    validar_estrutura,
    validar_rotas,
)


@pytest.fixture(scope="module")
def contrato():
    return CAMINHO_OPENAPI.read_text(encoding="utf-8")


def test_openapi_tem_estrutura_valida(contrato):
    validar_estrutura(contrato)


def test_openapi_nao_divergiu_das_rotas(contrato):
    validar_rotas(contrato)


def test_detector_denuncia_rota_documentada_sem_rota_real():
    texto = """
openapi: 3.0.3
info:
  title: Teste
paths:
  /fantasma/:
    get:
      operationId: fantasma
components: {}
"""
    reais = {"/real/": {"get"}}
    with pytest.raises(OpenAPIInvalido, match="documentadas mas inexistentes"):
        validar_rotas(texto, reais)


def test_detector_denuncia_metodo_divergente():
    texto = """
openapi: 3.0.3
info:
  title: Teste
paths:
  /real/:
    get:
      operationId: ler
    delete:
      operationId: apagar
components: {}
"""
    reais = {"/real/": {"get"}}
    with pytest.raises(OpenAPIInvalido, match="metodos divergentes"):
        validar_rotas(texto, reais)
