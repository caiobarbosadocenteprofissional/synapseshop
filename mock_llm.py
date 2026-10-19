"""``mock_llm`` — provedor de LLM FALSO, offline e grátis (Aula 14).

Por que existe: o ``llm_service`` fala com um provedor compatível com a API de
*Chat Completions* (OpenAI/DeepSeek) por HTTP. Para exercitar o fluxo completo —
``POST /api/v1/assist`` ➔ redação ➔ retry ➔ circuit breaker ➔ telemetria — sem
chave paga e sem rede, este script implementa o mínimo do contrato do provedor:
``POST /v1/chat/completions``.

A resposta é **determinística** (sem aleatoriedade): o mesmo log devolve sempre a
mesma saída, o que mantém smoke tests e demonstrações reproduzíveis. O texto é
montado a partir das palavras-chave presentes nos logs, imitando os dois modos
do assistente (``summarize`` e ``explain``), mas **não há modelo de IA algum** —
apenas geração de texto por regras.

Só usa a biblioteca padrão (``http.server``/``json``), pelo mesmo motivo do
``llm_service``: uma dependência a menos para instalar.

Uso::

    python mock_llm.py                 # escuta em 0.0.0.0:9999
    python mock_llm.py --port 9999     # porta explícita

No ``.env`` (já configurado)::

    LLM_BASE_URL=http://host.docker.internal:9999/v1
    LLM_API_KEY=mock-local
    LLM_MODEL=big-pickle-mock

``host.docker.internal`` permite que o container da API alcance este processo,
que roda no host. Rodando a API fora do Docker, use ``http://localhost:9999/v1``.
"""

import argparse
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple

# Palavras-chave que o mock reconhece nos logs, da mais específica para a mais
# genérica. Cada entrada é (rótulo do evento, regex, sugestão de causa).
_EVENTOS = (
    ("timeout", re.compile(r"(?i)\btime(d)?[\s_-]?out\b"), "Latência acima do prazo configurado."),
    ("rate limit (429)", re.compile(r"(?i)\b(429|rate[\s_-]?limit|too many requests)\b"), "O provedor/integração externa pediu para desacelerar."),
    ("indisponibilidade (5xx)", re.compile(r"(?i)\b(50[0-4]|indispon|unavailable|bad gateway)\b"), "Serviço dependente fora do ar ou reiniciando."),
    ("erro de validação (4xx)", re.compile(r"(?i)\b(40[0-9]|valid\w*|schema|malform\w*)\b"), "Payload fora do contrato; retentar não resolve."),
    ("falha de conexão", re.compile(r"(?i)\b(refused|reset|connection|conex\w*|network|rede)\b"), "Rede/DNS ou o processo destino caiu."),
    ("erro genérico", re.compile(r"(?i)\b(error|erro|exception|falha|fail\w*|traceback)\b"), "Falha não classificada; ver a stack trace."),
)

# Rótulos de domínio do SynapseShop: ajudam a montar o resumo por área.
_DOMINIOS = (
    ("pedido", re.compile(r"(?i)\bpedido(s)?\b")),
    ("pagamento", re.compile(r"(?i)\bpagamento(s)?\b")),
    ("notificação", re.compile(r"(?i)\bnotifica\w*\b")),
    ("cache/redis", re.compile(r"(?i)\b(cache|redis)\b")),
    ("mensageria", re.compile(r"(?i)\b(kafka|rabbitmq|fila|topico|t[óo]pico|dlq|broker)\b")),
    ("inventário", re.compile(r"(?i)\b(invent[áa]rio|estoque|stock)\b")),
)

_LINHAS_VAZIAS = re.compile(r"\n{2,}")


def _estimar_tokens(texto: str) -> int:
    """Estimativa grosseira de tokens (≈ 4 caracteres por token).

    Não precisa ser exata: o valor existe para o ``llm_service`` exercitar a
    contagem de tokens e o cálculo de custo. Determinístico de propósito.
    """
    return max(1, len(texto) // 4)


def _extrair_logs(user_content: str) -> str:
    marcador = "Logs:"
    if marcador in user_content:
        return user_content.split(marcador, 1)[1].strip()
    return user_content.strip()


def _detectar(texto: str, tabela) -> List[Tuple[str, int]]:
    encontrados = []
    for entrada in tabela:
        nome, padrao = entrada[0], entrada[1]
        total = len(padrao.findall(texto))
        if total:
            encontrados.append((nome, total))
    return encontrados


def _gerar_summarize(logs: str) -> str:
    eventos = _detectar(logs, _EVENTOS)
    dominios = _detectar(logs, _DOMINIOS)
    linhas = [ln.strip() for ln in logs.splitlines() if ln.strip()]
    topicos: List[str] = []

    for nome, total in eventos[:5]:
        sugestao = next((s for n, _, s in _EVENTOS if n == nome), "")
        topicos.append(f"{nome}: {total} ocorrência(s). {sugestao}")

    if dominios and len(topicos) < 5:
        resumo_dom = ", ".join(f"{n} ({t})" for n, t in dominios)
        topicos.append(f"Áreas citadas nos logs: {resumo_dom}.")

    if len(topicos) < 5:
        topicos.append(f"Volume analisado: {len(linhas)} linha(s) de log.")

    while len(topicos) < 5:
        topicos.append("Sem outros padrões evidentes nos logs fornecidos.")

    corpo = "\n".join(f"- {t}" for t in topicos[:5])
    return (
        "[mock offline] Resumo dos logs analisados:\n"
        f"{corpo}"
    )


def _gerar_explain(logs: str) -> str:
    eventos = _detectar(logs, _EVENTOS)
    dominios = _detectar(logs, _DOMINIOS)

    if eventos:
        principal, total = eventos[0]
        causa = next((s for n, _, s in _EVENTOS if n == principal), "")
        ocorreu = f"Foi identificado o padrão '{principal}' em {total} ocorrência(s)."
    else:
        causa = "Os logs não permitem concluir a causa; faltam detalhes do erro."
        ocorreu = "Os logs não apresentam um padrão de erro inequívoco."

    areas = ", ".join(n for n, _ in dominios) or "não identificadas"
    proximo = (
        "Coletar a stack trace completa e o identificador de correlação do caso "
        "de maior frequência; sem eles não é possível ir além do sintoma."
    )

    return (
        "[mock offline] Análise dos logs:\n"
        f"O que ocorreu: {ocorreu} Componentes envolvidos: {areas}.\n"
        f"Causa provável: {causa}\n"
        f"Próximo passo: {proximo}"
    )


def _gerar_resposta(mensagens: List[dict]) -> str:
    sistema = ""
    usuario = ""
    for msg in mensagens:
        papel = str(msg.get("role", ""))
        conteudo = str(msg.get("content", ""))
        if papel == "system":
            sistema += conteudo + "\n"
        elif papel == "user":
            usuario += conteudo + "\n"

    logs = _extrair_logs(usuario.strip())
    modo = "explain" if re.search(r"(?i)\bexpli\w*", sistema) else "summarize"
    if modo == "explain":
        return _gerar_explain(logs)
    return _gerar_summarize(logs)


def _montar_payload(modelo: str, mensagens: List[dict], resposta: str) -> Dict[str, Any]:
    entrada = "".join(str(m.get("content", "")) for m in mensagens)
    return {
        "id": f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": modelo or "big-pickle-mock",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": resposta},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": _estimar_tokens(entrada),
            "completion_tokens": _estimar_tokens(resposta),
            "total_tokens": _estimar_tokens(entrada) + _estimar_tokens(resposta),
        },
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockLLM/1.0"

    def _responder(self, status: int, corpo: Dict[str, Any]) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _erro(self, status: int, mensagem: str) -> None:
        self._responder(
            status,
            {"error": {"message": mensagem, "type": "invalid_request_error"}},
        )

    def do_GET(self) -> None:  # noqa: N802 (nome exigido por BaseHTTPRequestHandler)
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._responder(200, {"status": "ok", "mock": True})
            return
        self._erro(404, f"Rota não implementada no mock: {self.path}")

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._erro(404, f"Rota não implementada no mock: {self.path}")
            return

        tamanho = int(self.headers.get("Content-Length", 0) or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""
        try:
            dados = json.loads(bruto.decode("utf-8")) if bruto else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._erro(400, f"JSON inválido: {exc}")
            return

        mensagens = dados.get("messages")
        if not isinstance(mensagens, list) or not mensagens:
            self._erro(400, "'messages' é obrigatório e deve ser uma lista.")
            return

        resposta = _gerar_resposta(mensagens)
        payload = _montar_payload(str(dados.get("model", "")), mensagens, resposta)
        self._responder(200, payload)

    def log_message(self, formato: str, *args: Any) -> None:
        print(f"[mock_llm] {self.address_string()} - {formato % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provedor de LLM falso, offline.")
    parser.add_argument(
        "--host", default=os.environ.get("MOCK_LLM_HOST", "0.0.0.0")
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MOCK_LLM_PORT", "9999"))
    )
    args = parser.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(
        f"[mock_llm] servindo em http://{args.host}:{args.port}/v1 "
        f"(endpoint: POST /v1/chat/completions). Ctrl+C para parar.",
        flush=True,
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock_llm] encerrando.", flush=True)
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
