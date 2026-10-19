"""Impede que a documentação acumule links locais quebrados."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _arquivos_markdown():
    arquivos = [RAIZ / "README.md"]
    arquivos.extend(sorted((RAIZ / "docs").rglob("*.md")))
    return arquivos


def _destinos(texto):
    for bruto in LINK.findall(texto):
        destino = bruto.split("#", 1)[0].strip()
        if not destino or "://" in destino or destino.startswith(("mailto:", "#")):
            continue
        yield destino


def test_links_locais_da_documentacao_existem():
    quebrados = []
    for arquivo in _arquivos_markdown():
        for destino in _destinos(arquivo.read_text(encoding="utf-8")):
            alvo = (arquivo.parent / destino).resolve()
            if not alvo.exists():
                quebrados.append(f"{arquivo.relative_to(RAIZ)} -> {destino}")
    assert not quebrados, "links quebrados:\n" + "\n".join(quebrados)
