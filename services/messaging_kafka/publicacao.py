"""Publicação no Kafka: o produtor de eventos e a republicação com retenção."""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from confluent_kafka import KafkaException, Producer
from django.conf import settings

from events.topology import TopologiaEvento
from services.messaging_base import (
    HEADER_TENTATIVA,
    MensageriaIndisponivel,
    ResultadoPublicacao,
    _log,
    serializar_evento,
)
from services.messaging_kafka.topicos import _erro_do_broker, declarar_topologia

HEADER_EVENTO = "event_type"


class ProdutorEvento:
    """Publica eventos de domínio no tópico do evento que lhe foi entregue.

    A chave da mensagem é a ``idempotency_key``, o que dá ordenação por pedido.
    A topologia é declarada na construção para que a API também publique antes do
    worker existir. Quem usa esta classe não diz qual evento publica — diz o
    que faz com a topologia, e é o mesmo caminho para ``PedidoCriado``,
    ``PagamentoProcessado`` e ``NotificacaoEnviada``.
    """

    def __init__(self, topologia: TopologiaEvento, client_id: str = "synapseshop-api") -> None:
        self._topologia = topologia
        self._client_id = client_id
        self._produtor: Optional[Producer] = None

    @property
    def topico(self) -> str:
        return self._topologia.topico

    @property
    def topologia(self) -> TopologiaEvento:
        return self._topologia

    def __enter__(self) -> "ProdutorEvento":
        self.conectar()
        return self

    def __exit__(self, *_excecao) -> None:
        self.fechar()

    def conectar(self) -> None:
        try:
            self._produtor = Producer(
                {
                    "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                    "acks": settings.KAFKA_PRODUCER_ACKS,
                    "linger.ms": settings.KAFKA_PRODUCER_LINGER_MS,
                    "client.id": self._client_id,
                }
            )
            declarar_topologia()
        except Exception as exc:  # noqa: BLE001 - erro de broker vira erro de dominio
            self.fechar()
            raise MensageriaIndisponivel(_erro_do_broker(exc)) from exc

    def fechar(self) -> None:
        if self._produtor is not None:
            try:
                self._produtor.flush(5)
            except Exception:  # noqa: BLE001 - encerramento é best effort
                pass
        self._produtor = None

    def publicar(
        self,
        evento: Dict[str, Any],
        idempotency_key: str,
        topico: Optional[str] = None,
        cabecalhos: Optional[Dict[str, str]] = None,
    ) -> ResultadoPublicacao:
        """Publica o evento e devolve o desfecho normalizado da entrega.

        ``topico`` e ``cabecalhos`` existem para a reentrega e para a DLQ, que
        escrevem no mesmo tópico com contador de tentativa e último erro.
        """
        destino = topico or self._topologia.topico
        corpo = serializar_evento(evento)
        cabecalhos = {
            HEADER_TENTATIVA: 0,
            HEADER_EVENTO: str(evento.get("event_type") or ""),
            "event_id": str(evento.get("event_id") or ""),
            **(cabecalhos or {}),
        }
        # O cliente Kafka exige header em str/bytes: o contador de tentativa é
        # inteiro na memória e vira texto na borda, num ponto só.
        cabecalhos = {str(nome): str(valor) for nome, valor in cabecalhos.items()}
        entrega: List[Tuple[Optional[int], Optional[int]]] = []
        erro: List[Exception] = []

        def confirmado(err, msg) -> None:
            if err is not None:
                erro.append(KafkaException(err))
                return
            entrega.append((msg.partition(), msg.offset()))

        iniciado = time.perf_counter()
        try:
            self._produtor.produce(
                topic=destino,
                key=idempotency_key.encode("utf-8"),
                value=corpo,
                headers=cabecalhos,
                on_delivery=confirmado,
            )
            # flush espera as confirmações pendentes: sem ele, publicar seria
            # apenas enfileirar no cliente e a API mentiria sobre o desfecho.
            restantes = self._produtor.flush(10)
        except BufferError as exc:
            raise MensageriaIndisponivel("fila de envio do produtor cheia") from exc
        except Exception as exc:  # noqa: BLE001
            raise MensageriaIndisponivel(_erro_do_broker(exc)) from exc

        duracao_ms = round((time.perf_counter() - iniciado) * 1000, 3)
        if erro:
            raise MensageriaIndisponivel(_erro_do_broker(erro[0]))
        if restantes or not entrega:
            raise MensageriaIndisponivel(
                f"broker nao confirmou a publicacao em {destino} "
                f"({restantes} pendente(s))"
            )

        particao, offset = entrega[0]
        _log(
            "mensageria.publicado",
            event_type=evento.get("event_type"),
            idempotency_key=idempotency_key,
            correlation_id=evento.get("correlation_id"),
            topico=destino,
            particao=particao,
            offset=offset,
            bytes=len(corpo),
            duracao_ms=duracao_ms,
        )
        return ResultadoPublicacao(
            confirmado=True,
            identificador=f"{particao}:{offset}",
            particao=particao,
            offset=offset,
        )


def publicar_retencao(
    *,
    corpo,
    chave,
    cabecalhos,
    client_id: str,
    destino: str,
) -> Optional[Tuple[int, int]]:
    """Republica o corpo original com headers novos, para reentrega ou DLQ.

    O corpo vai como veio — os bytes que o broker entregou — porque a DLQ é a
    evidência da falha: um corpo ilegível precisa chegar inteiro à fila de
    inspeção, e não um substituto que hide a causa.

    Um produtor dedicado é criado por chamada: o consumidor segura um
    ``Consumer`` de uma partição por vez, e misturar os papéis no mesmo objeto
    tornaria a reconexão do consumidor dependente da publicação.
    """
    if not isinstance(corpo, (bytes, str)):
        corpo = json.dumps(
            {"erro": "evento sem corpo reenviável"}, ensure_ascii=False
        ).encode("utf-8")
    if isinstance(corpo, str):
        corpo = corpo.encode("utf-8")
    cabecalhos = {str(nome): str(valor) for nome, valor in (cabecalhos or {}).items()}
    chave = str(chave) if chave else str(uuid.uuid4())

    entrega: List[Tuple[Optional[int], Optional[int]]] = []
    erro: List[Exception] = []

    def confirmado(err, msg) -> None:
        if err is not None:
            erro.append(KafkaException(err))
            return
        entrega.append((msg.partition(), msg.offset()))

    produtor = Producer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "acks": settings.KAFKA_PRODUCER_ACKS,
            "client.id": client_id,
        }
    )
    try:
        produtor.produce(
            topic=destino,
            key=chave.encode("utf-8"),
            value=corpo,
            headers=cabecalhos,
            on_delivery=confirmado,
        )
        restantes = produtor.flush(10)
    except Exception as exc:  # noqa: BLE001
        _log("kafka.republicacao.erro", topico=destino, erro=_erro_do_broker(exc))
        return None
    finally:
        try:
            produtor.flush(1)
        except Exception:  # noqa: BLE001
            pass
    if erro:
        _log("kafka.republicacao.erro", topico=destino, erro=_erro_do_broker(erro[0]))
        return None
    if restantes or not entrega:
        return None
    return entrega[0]
