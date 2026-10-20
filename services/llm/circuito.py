"""Circuit breaker da camada de IA."""

import threading
import time
from typing import Any, Dict

from django.conf import settings


class CircuitBreaker:
    """Máquina de estados ``closed`` → ``open`` → ``half-open`` → ``closed``.

    Lê os limites de ``settings`` a cada transição (e não no ``__init__``) para
    que testes e operação possam reconfigurar sem recriar o objeto — o estado, que
    é o que precisa sobreviver às requisições, fica no objeto; a configuração fica
    nas settings.
    """

    FECHADO = "closed"
    ABERTO = "open"
    MEIO_ABERTO = "half-open"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._redefinir()

    def _redefinir(self) -> None:
        self._estado = self.FECHADO
        self._falhas = 0
        self._aberto_ate = 0.0

    def permitir(self) -> bool:
        """``False`` faz a chamada falhar rápido, sem tocar o provedor."""
        with self._lock:
            if self._estado == self.FECHADO:
                return True
            if self._estado == self.ABERTO:
                if time.monotonic() >= self._aberto_ate:
                    # Repouso vencido: libera UMA tentativa de prova.
                    self._estado = self.MEIO_ABERTO
                    return True
                return False
            return True  # half-open: a tentativa de prova está em voo

    def registrar_sucesso(self) -> None:
        with self._lock:
            self._redefinir()

    def registrar_falha(self) -> None:
        with self._lock:
            self._falhas += 1
            limite = getattr(settings, "LLM_CIRCUITO_LIMITE_FALHAS", 3)
            if self._estado == self.MEIO_ABERTO or self._falhas >= limite:
                self._estado = self.ABERTO
                self._aberto_ate = time.monotonic() + getattr(
                    settings, "LLM_CIRCUITO_RESET_SEGUNDOS", 30
                )

    def estado(self) -> Dict[str, Any]:
        with self._lock:
            return {"estado": self._estado, "falhas_consecutivas": self._falhas}
