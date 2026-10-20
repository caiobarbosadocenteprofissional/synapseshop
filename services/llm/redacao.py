"""Redação de dados sensíveis antes de qualquer saída para o provedor.

A ordem dos padrões importa: específicos primeiro, para que um número curto
(CPF) não seja capturado por um mais largo (cartão) nem um segredo por uma URL.
"""

import re
from typing import Tuple

_PADROES_REDACAO = (
    (
        "SEGREDO",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|"
            r"password|passwd|senha|authorization)\b\s*[:=]\s*[\"']?[^\s\"',;]+"
        ),
    ),
    ("BEARER", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("CNPJ", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("CARTAO", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("TELEFONE", re.compile(r"(?:\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}\b")),
)


def redigir(texto: str) -> Tuple[str, int]:
    """Substitui PII e segredos por marcadores. Devolve ``(texto, nº redações)``.

    A contagem, e não o conteúdo, é o que se registra em log: assim a política de
    privacidade é auditável ("esta requisição redigiu 3 dados") sem que o próprio
    log de auditoria vire uma nova cópia do dado sensível.
    """
    total = 0
    for marcador, padrao in _PADROES_REDACAO:
        texto, substituicoes = padrao.subn(f"[{marcador}_REDIGIDO]", texto)
        total += substituicoes
    return texto, total
