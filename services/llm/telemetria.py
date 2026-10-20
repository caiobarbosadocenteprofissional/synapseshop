"""Contadores de telemetria da camada de IA.

Em memória porque a métrica desta aula é de processo único; vários workers
agregariam no Redis/Prometheus, evolução registrada no backlog.
"""

import threading
from typing import Any, Dict


class _Telemetria:
    """Contadores protegidos por lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.resetar()

    def resetar(self) -> None:
        with self._lock:
            self._chamadas = 0
            self._sucessos = 0
            self._erros = 0
            self._tokens_prompt = 0
            self._tokens_output = 0
            self._latencia_total_ms = 0.0
            self._custo_total_usd = 0.0
            self._por_tipo_erro: Dict[str, int] = {}

    def registrar_sucesso(
        self,
        *,
        latencia_ms: float,
        tokens_prompt: int,
        tokens_output: int,
        custo_usd: float,
    ) -> None:
        with self._lock:
            self._chamadas += 1
            self._sucessos += 1
            self._tokens_prompt += tokens_prompt
            self._tokens_output += tokens_output
            self._latencia_total_ms += latencia_ms
            self._custo_total_usd += custo_usd

    def registrar_erro(self, *, tipo_erro: str, latencia_ms: float) -> None:
        with self._lock:
            self._chamadas += 1
            self._erros += 1
            self._latencia_total_ms += latencia_ms
            self._por_tipo_erro[tipo_erro] = self._por_tipo_erro.get(tipo_erro, 0) + 1

    def metricas(self) -> Dict[str, Any]:
        with self._lock:
            chamadas = self._chamadas
            return {
                "chamadas": chamadas,
                "sucessos": self._sucessos,
                "erros": self._erros,
                "taxa_erro": round(self._erros / chamadas, 4) if chamadas else 0.0,
                "tokens_prompt": self._tokens_prompt,
                "tokens_output": self._tokens_output,
                "tokens_total": self._tokens_prompt + self._tokens_output,
                "latencia_media_ms": (
                    round(self._latencia_total_ms / chamadas, 3) if chamadas else 0.0
                ),
                "custo_total_usd": round(self._custo_total_usd, 6),
                "erros_por_tipo": dict(self._por_tipo_erro),
            }
