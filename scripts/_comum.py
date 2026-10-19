"""Utilidades compartilhadas pelos scripts operacionais (somente stdlib).

Concentra o cliente HTTP, o relatório PASS/FAIL/SKIP e a leitura da DLQ que os
smoke tests e benchmarks repetiam. Os scripts continuam executáveis de forma
independente: ``python scripts/<nome>.py`` adiciona ``scripts/`` ao ``sys.path``
e o import abaixo resolve.
"""

import base64
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL_PADRAO = "http://localhost:8000"
ADMIN = {"username": "admin", "password": "admin"}
USER = {"username": "user", "password": "user"}

_BASE_URL = BASE_URL_PADRAO


def configurar_base(url):
    """Define a URL base usada por ``pedir`` e devolve o valor normalizado."""
    global _BASE_URL
    _BASE_URL = (url or BASE_URL_PADRAO).rstrip("/")
    return _BASE_URL


def pedir(metodo, caminho, dados=None, token=None, timeout=30, base=None):
    """Executa a chamada HTTP e devolve ``(status, payload, headers)``.

    Erros HTTP não são exceções: viram o próprio status, porque os smoke tests
    verificam códigos como 400/401/403/429. Falhas de rede continuam subindo.
    Passe ``base=""`` para usar uma URL absoluta em ``caminho``.
    """
    corpo = json.dumps(dados).encode() if dados is not None else None
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    raiz = _BASE_URL if base is None else base
    requisicao = urllib.request.Request(
        f"{raiz}{caminho}", method=metodo, data=corpo, headers=cabecalhos
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            bruto = resposta.read()
            return (
                resposta.status,
                (json.loads(bruto) if bruto else None),
                dict(resposta.headers),
            )
    except urllib.error.HTTPError as exc:
        bruto = exc.read()
        try:
            payload = json.loads(bruto)
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload, dict(exc.headers)


def header(cabecalhos, nome):
    """Lê um header sem depender da grafia: HTTP não diferencia maiúsculas."""
    if not cabecalhos:
        return None
    alvo = nome.lower()
    for chave, valor in cabecalhos.items():
        if chave.lower() == alvo:
            return valor
    return None


def aguardar(consulta, tentativas=30, intervalo=0.5):
    """Repete ``consulta`` até devolver um valor verdadeiro (ou esgotar)."""
    for _ in range(tentativas):
        resultado = consulta()
        if resultado:
            return resultado
        time.sleep(intervalo)
    return None


def basic_auth(usuario, senha):
    """Header ``Authorization: Basic`` para a Management API do RabbitMQ."""
    credencial = base64.b64encode(f"{usuario}:{senha}".encode()).decode()
    return f"Basic {credencial}"


def management(url, usuario, senha, metodo="GET", dados=None, timeout=15):
    """Chama a Management API do RabbitMQ e devolve o JSON da resposta."""
    cabecalhos = {"Authorization": basic_auth(usuario, senha)}
    corpo = None
    if dados is not None:
        corpo = json.dumps(dados).encode()
        cabecalhos["Content-Type"] = "application/json"
    requisicao = urllib.request.Request(
        url, method=metodo, data=corpo, headers=cabecalhos
    )
    with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
        bruto = resposta.read()
    return json.loads(bruto) if bruto else None


def contar_mortas_dlq(
    broker,
    *,
    kafka_servers="localhost:9092",
    topico="",
    fila="",
    rabbit_api="http://localhost:15672",
    usuario="guest",
    senha="guest",
    grupo="smoke-contagem",
):
    """Quantas mensagens há na DLQ do broker ativo (``None`` se indisponível)."""
    if broker == "kafka":
        try:
            from confluent_kafka import Consumer, TopicPartition

            consumidor = Consumer(
                {"bootstrap.servers": kafka_servers, "group.id": grupo}
            )
            try:
                metadata = consumidor.list_topics(topico, timeout=15)
                if topico not in metadata.topics:
                    return 0
                total = 0
                for particao in metadata.topics[topico].partitions:
                    inicio, fim = consumidor.get_watermark_offsets(
                        TopicPartition(topico, particao), timeout=10, cached=False
                    )
                    total += max(fim - inicio, 0)
                return total
            finally:
                consumidor.close()
        except Exception as exc:  # noqa: BLE001
            print(f"  ..    contagem da DLQ falhou: {exc}")
            return None

    try:
        info = management(f"{rabbit_api}/api/queues/%2F/{fila}", usuario, senha)
        return (info or {}).get("messages")
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    contagem da DLQ falhou: {exc}")
        return None


class Relatorio:
    """Contadores e saída padronizada de PASS/FAIL/SKIP dos smoke tests."""

    def __init__(self, titulo=""):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        if titulo:
            print(titulo)

    def check(self, nome, condicao, extra=""):
        if condicao:
            self.passed += 1
            print(f"  PASS  {nome} {extra}")
        else:
            self.failed += 1
            print(f"  FAIL  {nome} {extra}")
        return bool(condicao)

    def skip(self, nome, motivo):
        self.skipped += 1
        print(f"  SKIP  {nome}")
        print(f"        {motivo}")

    def resultado(self, estilo="completo"):
        if estilo == "curto":
            print(f"\n{self.passed} passed, {self.failed} failed")
        else:
            print(
                f"\n== Resultado: {self.passed} PASS / "
                f"{self.failed} FAIL / {self.skipped} SKIP =="
            )
        return 1 if self.failed else 0
