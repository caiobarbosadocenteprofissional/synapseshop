"""Testes da política de consumo compartilhada (``services.messaging_base``).

A política é o que decide entre reentregar e matar para a DLQ. Ela é testada
com um transporte de mentira — o mesmo arranjo usado nos testes de paridade dos
dois brokers — porque o que importa aqui é a **decisão**, não o protocolo.
"""

import pytest

from services import messaging_base
from services.messaging_base import (
    HEADER_ERRO,
    HEADER_TENTATIVA,
    ResultadoPublicacao,
    esperar_reentrega,
    ler_tentativa,
    processar_evento,
    serializar_evento,
)

pytestmark = pytest.mark.unit


class TransporteFalso:
    """Transporte de mentira: registra o que a política pediu a ele."""

    def __init__(self, *, republica=True, mata=True):
        self.republicacoes = []
        self.confirmacoes = 0
        self.mortes = []
        self._republica = republica
        self._mata = mata

    def republicar(self, corpo, evento, cabecalhos):
        self.republicacoes.append(
            {"corpo": corpo, "evento": evento, "cabecalhos": cabecalhos}
        )
        return None if self._republica else "broker nao confirmou a republicacao"

    def confirmar(self):
        self.confirmacoes += 1

    def matar(self, corpo, evento, cabecalhos, erro):
        self.mortes.append(
            {"corpo": corpo, "evento": evento, "cabecalhos": cabecalhos, "erro": erro}
        )
        return self._mata


@pytest.fixture
def eventos(monkeypatch):
    """Captura os eventos de log emitidos pela política."""
    registros = []
    monkeypatch.setattr(
        messaging_base,
        "_log",
        lambda nome, **campos: registros.append((nome, campos)),
    )
    return registros


@pytest.fixture
def sem_espera(settings):
    """Zera o recuo: a política não deve custar segundos ao teste."""
    settings.MENSAGERIA_BACKOFF_BASE_MS = 0
    settings.MENSAGERIA_BACKOFF_MAX_MS = 0
    return settings


def _corpo(evento=None):
    return serializar_evento(
        evento or {"idempotency_key": "pedido:1", "event_type": "PedidoCriado"}
    )


def _processar(transporte, *, corpo=None, handler=None, tentativa=0):
    processar_evento(
        corpo=_corpo() if corpo is None else corpo,
        tentativa=tentativa,
        handler=handler or (lambda evento, tentativa: None),
        republicar=transporte.republicar,
        confirmar=transporte.confirmar,
        matar=transporte.matar,
        campos=lambda: {"transporte": "falso"},
        destino_dlq="fila.dlq",
    )


# --------------------------------------------------------------------------- #
# Peças avulsas
# --------------------------------------------------------------------------- #
def test_esperar_reentrega_cresce_exponencialmente(settings):
    settings.MENSAGERIA_BACKOFF_BASE_MS = 100
    settings.MENSAGERIA_BACKOFF_MAX_MS = 10000
    assert esperar_reentrega(1) == pytest.approx(0.1)
    assert esperar_reentrega(2) == pytest.approx(0.2)
    assert esperar_reentrega(3) == pytest.approx(0.4)


def test_esperar_reentrega_respeita_o_teto(settings):
    settings.MENSAGERIA_BACKOFF_BASE_MS = 1000
    settings.MENSAGERIA_BACKOFF_MAX_MS = 2500
    assert esperar_reentrega(10) == pytest.approx(2.5)


def test_ler_tentativa_de_mapa_amqp():
    assert ler_tentativa({HEADER_TENTATIVA: 2, "outro": "x"}) == 2


def test_ler_tentativa_de_lista_kafka():
    assert ler_tentativa([("outro", b"x"), (HEADER_TENTATIVA, "3")]) == 3


def test_ler_tentativa_de_bytes():
    assert ler_tentativa({HEADER_TENTATIVA: b"4"}) == 4


def test_ler_tentativa_de_valor_invalido():
    assert ler_tentativa({HEADER_TENTATIVA: "abc"}) == 0


def test_ler_tentativa_sem_headers():
    assert ler_tentativa(None) == 0
    assert ler_tentativa([]) == 0
    assert ler_tentativa({"outro": 1}) == 0


def test_serializar_evento_preserva_acentos():
    assert serializar_evento({"nome": "Café"}) == '{"nome": "Café"}'.encode("utf-8")


def test_resultado_publicacao_tem_desfecho_normalizado():
    resultado = ResultadoPublicacao(confirmado=True, identificador="3:17", particao=3, offset=17)
    assert resultado.confirmado is True
    assert resultado.identificador == "3:17"
    assert (resultado.particao, resultado.offset) == (3, 17)


# --------------------------------------------------------------------------- #
# A decisão da política
# --------------------------------------------------------------------------- #
def test_efeito_e_aplicado_antes_da_confirmacao(sem_espera, eventos):
    """A ordem é a garantia: o efeito vem antes do *ack*/*commit*."""
    ordem = []
    transporte = TransporteFalso()
    transporte.confirmar = lambda: ordem.append("confirmado")
    _processar(transporte, handler=lambda evento, tentativa: ordem.append("efeito"))

    assert ordem == ["efeito", "confirmado"]


def test_sucesso_confirma_e_registra(sem_espera, eventos):
    transporte = TransporteFalso()
    _processar(transporte)

    assert transporte.confirmacoes == 1
    assert transporte.republicacoes == []
    assert transporte.mortes == []
    nome, campos = eventos[-1]
    assert nome == "mensageria.consumido"
    assert campos["idempotency_key"] == "pedido:1"
    assert campos["resultado"] == "ok"
    assert campos["transporte"] == "falso"


def test_falha_reentrega_com_tentativa_incrementada(sem_espera, eventos):
    transporte = TransporteFalso()

    def falha(evento, tentativa):
        raise RuntimeError("boom")

    _processar(transporte, handler=falha)

    assert transporte.confirmacoes == 1
    assert transporte.mortes == []
    cabecalhos = transporte.republicacoes[0]["cabecalhos"]
    assert cabecalhos[HEADER_TENTATIVA] == 1
    assert cabecalhos[HEADER_ERRO] == "boom"
    nome, campos = eventos[-1]
    assert nome == "mensageria.reentrega"
    assert campos["proxima_tentativa"] == 1
    assert campos["tentativa"] == 0


def test_republicacao_nao_confirmada_nao_confirma_a_original(sem_espera, eventos):
    transporte = TransporteFalso(republica=False)

    def falha(evento, tentativa):
        raise RuntimeError("boom")

    _processar(transporte, handler=falha)

    assert transporte.confirmacoes == 0
    nome, campos = eventos[-1]
    assert nome == "mensageria.reentrega.falhou"
    assert "nao confirmou" in campos["erro"]


def test_tentativas_esgotadas_matem_para_a_dlq(sem_espera, eventos, settings):
    settings.MENSAGERIA_MAX_RETRIES = 3
    transporte = TransporteFalso()

    def falha(evento, tentativa):
        raise RuntimeError("boom")

    _processar(transporte, handler=falha, tentativa=3)

    assert transporte.republicacoes == []
    assert transporte.mortes[0]["erro"] == "boom"
    assert transporte.mortes[0]["cabecalhos"][HEADER_TENTATIVA] == 3
    nome, campos = eventos[-1]
    assert nome == "mensageria.dlq"
    assert campos["dlq"] == "fila.dlq"


def test_dlq_nao_confirmada_nao_confirma_a_original(sem_espera, eventos, settings):
    settings.MENSAGERIA_MAX_RETRIES = 3
    transporte = TransporteFalso(mata=False)

    def falha(evento, tentativa):
        raise RuntimeError("boom")

    _processar(transporte, handler=falha, tentativa=3)

    assert transporte.confirmacoes == 0
    nome, _campos = eventos[-1]
    assert nome == "mensageria.dlq.falhou"


def test_corpo_invalido_vai_direto_para_a_dlq(sem_espera, eventos):
    transporte = TransporteFalso()
    _processar(transporte, corpo=b"{isto nao e json")

    assert transporte.republicacoes == []
    assert transporte.mortes[0]["corpo"] == b"{isto nao e json"
    assert "corpo invalido" in transporte.mortes[0]["erro"]
    nome, _campos = eventos[-1]
    assert nome == "mensageria.dlq"


def test_corpo_invalido_nao_e_reentregado(sem_espera, eventos):
    transporte = TransporteFalso()
    _processar(transporte, corpo=b"{isto nao e json")

    assert transporte.republicacoes == []
    assert transporte.confirmacoes == 0
