"""Valida o contrato ``openapi.yaml`` contra as rotas reais da API.

Sem dependências novas: o YAML é lido por indentação, no subconjunto que este
projeto usa (mapas de caminhos e métodos). A validação cobre o que de fato já
quebrou ou poderia quebrar em silêncio:

1. **Estrutura** — ``openapi``/``info``/``paths`` presentes e toda operação com
   ``tags``, ``summary``, ``operationId`` único e ``responses``.
2. **Referências** — todo ``$ref`` aponta para um componente declarado.
3. **Drift de rotas** — cada rota documentada existe no Django e cada rota da
   API (fora as de documentação) está documentada, com os mesmos métodos.

Uso: ``python scripts/validar_openapi.py`` (0 = válido, 1 = divergência).
"""

import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CAMINHO_OPENAPI = BASE_DIR / "openapi.yaml"
METODOS = ("get", "post", "put", "patch", "delete")
ROTAS_DE_INFRA = {"/docs", "/docs/redoc", "/openapi.yaml"}

_RE_CAMINHO = re.compile(r"^  (/\S*):\s*$")
_RE_METODO = re.compile(r"^    (get|post|put|patch|delete):\s*$")
_RE_REF = re.compile(r"\$ref:\s*'#/components/([^/']+)/([^']+)'")
_RE_COMPONENTE = re.compile(r"^    ([A-Za-z0-9_.-]+):\s*$")


class OpenAPIInvalido(RuntimeError):
    """O contrato não bate com a estrutura ou com as rotas da API."""


def ler_contrato(texto: str):
    """Extrai ``{caminho: {metodos}}`` do YAML por indentação."""
    caminhos = {}
    atual = None
    dentro_de_paths = False
    for linha in texto.splitlines():
        if linha.rstrip() == "paths:":
            dentro_de_paths = True
            continue
        if not dentro_de_paths:
            continue
        if linha and not linha.startswith(" "):
            break
        caminho = _RE_CAMINHO.match(linha)
        if caminho:
            atual = caminho.group(1)
            caminhos[atual] = set()
            continue
        metodo = _RE_METODO.match(linha)
        if metodo and atual:
            caminhos[atual].add(metodo.group(1))
    return caminhos


def componentes_declarados(texto: str):
    """Nomes ``secao/nome`` de ``components`` referenciáveis por ``$ref``."""
    declarados = set()
    secao = None
    dentro = False
    for linha in texto.splitlines():
        if linha.rstrip() == "components:":
            dentro = True
            continue
        if not dentro:
            continue
        if linha and not linha.startswith(" "):
            break
        if re.match(r"^  [A-Za-z]+:\s*$", linha):
            secao = linha.strip()[:-1]
            continue
        item = _RE_COMPONENTE.match(linha)
        if item and secao:
            declarados.add(f"{secao}/{item.group(1)}")
    return declarados


def validar_estrutura(texto: str):
    for chave in ("openapi:", "info:", "paths:"):
        if chave not in texto:
            raise OpenAPIInvalido(f"chave obrigatoria ausente: {chave[:-1]}")

    caminhos = ler_contrato(texto)
    if not caminhos:
        raise OpenAPIInvalido("nenhum caminho encontrado em paths")

    ids = re.findall(r"^\s+operationId:\s*(\S+)\s*$", texto, re.MULTILINE)
    duplicados = sorted({item for item in ids if ids.count(item) > 1})
    if duplicados:
        raise OpenAPIInvalido(f"operationId duplicado: {', '.join(duplicados)}")

    declarados = componentes_declarados(texto)
    for secao, nome in _RE_REF.findall(texto):
        if f"{secao}/{nome}" not in declarados:
            raise OpenAPIInvalido(f"$ref sem componente: {secao}/{nome}")

    for caminho, metodos in caminhos.items():
        if not metodos:
            raise OpenAPIInvalido(f"{caminho} nao declara nenhum metodo")


def _normalizar(caminho: str) -> str:
    caminho = caminho.replace("^", "").replace("$", "")
    caminho = "/" + caminho.strip("/") + "/"
    caminho = re.sub(r"\(\?P<[^>]+>[^)]+\)", "{}", caminho)
    caminho = re.sub(r"<[^>]+>", "{}", caminho)
    return re.sub(r"\{[^}]+\}", "{}", caminho)


def _metodos_do_callback(callback):
    acoes = getattr(callback, "actions", None)
    if acoes:
        return set(acoes) & set(METODOS)
    classe = getattr(callback, "cls", None)
    if classe is None:
        return {"get"}
    return {metodo for metodo in METODOS if hasattr(classe, metodo)}


def rotas_django():
    """Rotas resolvidas da API, excluindo as interfaces de documentação."""
    import django

    django.setup()
    from django.urls import URLPattern, URLResolver, get_resolver

    rotas = {}

    def percorrer(resolvedor, prefixo=""):
        for entrada in resolvedor.url_patterns:
            caminho = prefixo + str(entrada.pattern)
            if isinstance(entrada, URLResolver):
                percorrer(entrada, caminho)
            elif isinstance(entrada, URLPattern):
                if "(?P<format>" in caminho or "<drf_format_suffix" in caminho:
                    continue
                normalizado = _normalizar(caminho)
                if normalizado.rstrip("/") not in ROTAS_DE_INFRA and normalizado != "/api/v1/":
                    rotas[normalizado] = _metodos_do_callback(entrada.callback)

    percorrer(get_resolver())
    return rotas


def validar_rotas(texto: str, rotas_reais=None):
    documentadas = {
        _normalizar(caminho): metodos for caminho, metodos in ler_contrato(texto).items()
    }
    reais = rotas_django() if rotas_reais is None else rotas_reais

    so_documentadas = sorted(set(documentadas) - set(reais))
    so_reais = sorted(set(reais) - set(documentadas))
    if so_documentadas:
        raise OpenAPIInvalido(
            "documentadas mas inexistentes: " + ", ".join(so_documentadas)
        )
    if so_reais:
        raise OpenAPIInvalido(
            "existem na API mas nao documentadas: " + ", ".join(so_reais)
        )

    for caminho in sorted(reais):
        if documentadas[caminho] != reais[caminho]:
            faltando = sorted(reais[caminho] - documentadas[caminho])
            sobrando = sorted(documentadas[caminho] - reais[caminho])
            raise OpenAPIInvalido(
                f"{caminho}: metodos divergentes (faltando={faltando}, "
                f"sobrando={sobrando})"
            )


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    texto = CAMINHO_OPENAPI.read_text(encoding="utf-8")
    try:
        validar_estrutura(texto)
        rotas = rotas_django()
        validar_rotas(texto, rotas)
    except OpenAPIInvalido as exc:
        print(f"FALHA: {exc}")
        return 1
    total = sum(len(metodos) for metodos in rotas.values())
    print(f"OK: {len(rotas)} caminhos e {total} operacoes conferem com a API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
