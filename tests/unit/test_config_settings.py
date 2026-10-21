"""Testes da leitura de configuração a partir do ambiente.

A suíte roda com ``config.settings_test``, que é uma **cópia** de
``config.settings`` (``from config.settings import *``). Verificar o que o
código de produção lê do ambiente exige, portanto, recarregar o módulo
``config.settings`` — senão o teste mediria a cópia congelada no import.

Estes testes existem porque a família da mensageria teve duas grafias e uma
delas estava com o nome trocado no código: a variável documentada era lida de
outro jeito, o valor era ignorado em silêncio e a política de reentrega ficava
congelada no default. O teste fixa o comportamento para que a troca de nome
não volte a passar despercebida.
"""

import importlib

import pytest

from config import settings as config_settings

pytestmark = pytest.mark.unit


@pytest.fixture
def settings_com_env(monkeypatch):
    """Recarrega ``config.settings`` com o ambiente do teste.

    ``None`` no dicionário significa "remove a variável do ambiente". Depois
    de cada teste o módulo é recarregado de novo, para que a suíte volte ao
    ambiente real.
    """

    def _carregar(**ambiente):
        for nome, valor in ambiente.items():
            if valor is None:
                monkeypatch.delenv(nome, raising=False)
            else:
                monkeypatch.setenv(nome, str(valor))
        return importlib.reload(config_settings)

    yield _carregar
    importlib.reload(config_settings)


def test_max_retries_lê_a_grafia_canonica(settings_com_env):
    mod = settings_com_env(MENSAGERIA_MAX_RETRIES=7, MESSAGERIA_MAX_RETRIES=None)
    assert mod.MENSAGERIA_MAX_RETRIES == 7


def test_max_retries_aceita_a_grafia_obsoleta(settings_com_env):
    """O ``.env`` de quem já tinha a grafia antiga continua funcionando."""
    mod = settings_com_env(MENSAGERIA_MAX_RETRIES=None, MESSAGERIA_MAX_RETRIES=9)
    assert mod.MENSAGERIA_MAX_RETRIES == 9


def test_grafia_canonica_tem_precedencia_sobre_a_obsoleta(settings_com_env):
    mod = settings_com_env(MENSAGERIA_MAX_RETRIES=7, MESSAGERIA_MAX_RETRIES=9)
    assert mod.MENSAGERIA_MAX_RETRIES == 7


def test_max_retries_tem_default_quando_nada_e_definido(settings_com_env):
    mod = settings_com_env(MENSAGERIA_MAX_RETRIES=None, MESSAGERIA_MAX_RETRIES=None)
    assert mod.MENSAGERIA_MAX_RETRIES == 3


def test_mensageria_enabled_lê_a_grafia_canonica(settings_com_env):
    mod = settings_com_env(MENSAGERIA_ENABLED="false", MESSAGERIA_ENABLED=None)
    assert mod.MENSAGERIA_ENABLED is False


def test_mensageria_enabled_aceita_a_grafia_obsoleta(settings_com_env):
    mod = settings_com_env(MENSAGERIA_ENABLED=None, MESSAGERIA_ENABLED="false")
    assert mod.MENSAGERIA_ENABLED is False


def test_mensageria_enabled_default_é_ativo(settings_com_env):
    mod = settings_com_env(MENSAGERIA_ENABLED=None, MESSAGERIA_ENABLED=None)
    assert mod.MENSAGERIA_ENABLED is True
