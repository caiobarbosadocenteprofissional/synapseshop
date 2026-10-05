"""Camada de mensageria assíncrona sobre Apache Kafka (Aulas 10 e 11).

Entrega o par produtor/consumidor do evento ``PedidoCriado`` que o transporte
AMQP da Aula 9 entregou, com as semânticas próprias do Kafka:

1. **Topologia** — tópicos ``pedidos.pedidocriado`` e ``pedidos.pedidocriado.dlq``,
   criados via ``KafkaAdminClient`` de forma idempotente (``TopicAlreadyExists``
   é ignorado), com ``KAFKA_PARTICOES`` partições e retenção configurável por
   ``KAFKA_RETENTION_MS``. A API e o worker declaram a topologia na subida, como
   no AMQP, para que subam em qualquer ordem. Na Aula 11 a topologia deixou de ser
   do evento e passou a ser **por evento** (``events/topology.py``): este módulo
   cria o par tópico/DLQ de cada evento declarado, sem conhecer os nomes.
2. **Publicação** — a **chave da mensagem é a ``idempotency_key``**. Como o
   Kafka distribui por ``hash(chave) % partições``, todos os eventos do mesmo
   pedido caem na mesma partição e portanto são consumidos em ordem; partições
   diferentes são consumidas em paralelo. A confirmação é feita com
   ``acks=all`` e ``flush`` — o produtor só devolve sucesso depois que o líder
   (e as réplicas) aceitaram o registro.
3. **Consumo com reentrega controlada** — ``enable.auto.commit=False``: o offset
   é commitado **depois** do efeito, o que dá entrega pelo menos uma vez sem
   perder evento em queda do consumidor. O contador de tentativas viaja no header
   ``x-retry-count`` e, ao esgotar ``MENSAGERIA_MAX_RETRIES``, a mensagem é
   publicada no tópico da DLQ e só então o offset é commitado.

Diferenças em relação ao AMQP que valem registro:

- **Não há *dead-letter exchange* nativa.** O roteamento da mensagem morta é
  feito pela aplicação, publicando no tópico da DLQ. O preço é não haver
  atomicidade entre "publicar na DLQ" e "commit do offset": se o processo cair
  entre as duas, a mensagem é reentregue e vai de novo para a DLQ, o que é
  inofensivo porque a leitura da DLQ é humana e a duplicata é identificável.
  Em troca, a DLQ vira um **log consultável e inspecionável**, que é o motivo de
  existir a Aula 10.
- **Não há reentrega nativa por mensagem.** Reentregar é republicar no mesmo
  tópico com o contador incrementado; é a mesma política da Aula 9, e por isso
  o backoff é feito segurando o offset (o consumidor não faz commit antes de
  republicar).
- **A retenção é o ganho real.** O tópico guarda o histórico por
  ``KAFKA_RETENTION_MS``, então um consumidor novo ou o reprocessamento por
  offset são operações ordinárias, e não uma fila que precise sobreviver a um
  broker.
"""

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from django.conf import settings

from events.topology import TopologiaEvento, topologias

logger = logging.getLogger("synapseshop.mensageria")

HEADER_TENTATIVA = "x-retry-count"
HEADER_ERRO = "x-ultimo-erro"
HEADER_EVENTO = "event_type"


class MensageriaIndisponivel(RuntimeError):
    """O broker não pôde ser alcançado ou recusou a publicação."""


def _bootstrap() -> List[str]:
    return [s.strip() for s in settings.KAFKA_BOOTSTRAP_SERVERS.split(",") if s.strip()]


def _log(nome_evento: str, **campos: Any) -> None:
    # O primeiro parâmetro não se chama `evento` de propósito: os payloads
    # carregam um campo `event_type` e a colisão seria um TypeError.
    logger.info(
        json.dumps(
            {"evento": nome_evento, **{k: v for k, v in campos.items() if v is not None}},
            ensure_ascii=False,
        )
    )


def _erro_do_broker(exc: Exception) -> str:
    """Extrai a mensagem legível de uma falha de broker, sem o ruído do traceback."""
    erro = getattr(exc, "args", None)
    if isinstance(erro, (list, tuple)) and erro:
        erro = erro[0]
    if isinstance(erro, KafkaError):
        return f"{erro.name()}: {erro.str()}"
    return str(exc)[:500]


def declarar_topologia() -> None:
    """Cria os tópicos de todos os eventos se ainda não existirem. Idempotente.

    A criação é feita pelo mesmo código que publica e consome, e não por um
    contêiner de inicialização: o broker sobe, a API e os workers chamam esta
    função na subida e todos seguem funcionando, sem depender da ordem de start.

    A assinatura de partições e retenção é a mesma para todo evento — a diferença
    está nos nomes, que vêm de ``events/topology.py``.
    """
    cliente = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
    topicos = []
    for topologia in topologias():
        topicos.append(
            NewTopic(
                topologia.topico,
                num_partitions=settings.KAFKA_PARTICOES,
                replication_factor=settings.KAFKA_REPLICAS,
                config={
                    "retention.ms": str(settings.KAFKA_RETENTION_MS),
                    "cleanup.policy": settings.KAFKA_CLEANUP_POLICY,
                },
            )
        )
        topicos.append(
            NewTopic(
                topologia.dlq,
                num_partitions=1,
                replication_factor=settings.KAFKA_REPLICAS,
                config={
                    # A DLQ é a evidência da falha: precisa sobreviver mais que o
                    # tópico de trabalho, senão o diagnóstico se perde com o tempo.
                    "retention.ms": str(settings.KAFKA_RETENTION_MS * 4),
                    "cleanup.policy": settings.KAFKA_CLEANUP_POLICY,
                },
            )
        )
    # `create_topics` devolve o nome do tópico como chave, então a contagem de
    # partições tem de vir do `NewTopic` — que é o objeto que a define.
    particoes_por_topico = {topico.topic: topico.num_partitions for topico in topicos}
    for nome, futuro in cliente.create_topics(topicos, request_timeout=15).items():
        try:
            futuro.result()
            _log(
                "kafka.topico.criado",
                topico=nome,
                particoes=particoes_por_topico.get(nome),
            )
        except KafkaException as exc:
            if exc.args and isinstance(exc.args[0], KafkaError):
                if exc.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS:
                    continue
            raise MensageriaIndisponivel(
                f"nao foi possivel criar o topico {topico}: {_erro_do_broker(exc)}"
            ) from exc


class ProdutorEvento:
    """Publica eventos de domínio no tópico do evento que lhe foi entregue.

    A chave da mensagem é a ``idempotency_key``, o que dá ordenação por pedido.
    A topologia é declarada na construção para que a API também publique antes de
    o worker existir. Quem usa esta classe não diz qual evento publica — diz o
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
    ) -> Tuple[Optional[int], Optional[int]]:
        """Publica o evento e devolve ``(particao, offset)`` da entrega.

        ``topico`` e ``cabecalhos`` existem para a reentrega e para a DLQ, que
        escrevem no mesmo tópico com contador de tentativa e último erro.
        """
        destino = topico or self._topologia.topico
        corpo = json.dumps(evento, ensure_ascii=False).encode("utf-8")
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
        return particao, offset


def _esperar_reentrega(tentativa: int) -> float:
    """Recuo exponencial limitado por ``MENSAGERIA_BACKOFF_MAX_MS``."""
    atraso_ms = min(
        settings.MENSAGERIA_BACKOFF_BASE_MS * (2 ** (tentativa - 1)),
        settings.MENSAGERIA_BACKOFF_MAX_MS,
    )
    return atraso_ms / 1000.0


def _tempo_de_fila(msg: Message) -> Optional[float]:
    """Tempo entre a gravação no log e o consumo, em ms.

    O timestamp do broker e o instante da leitura caem no mesmo host (o
    contêiner do worker), então a subtração mede a espera na particao — que na
    Aula 9 ficou misturada no total, por nao haver equivalente no AMQP.
    """
    try:
        # A API devolve (tipo, instante_em_ms); o instante é o segundo elemento.
        marca = msg.timestamp()[1]
    except Exception:  # noqa: BLE001 - alguns formatos de log nao tem timestamp
        return None
    if marca is None or marca < 0:
        return None
    return round((time.time() * 1000.0 - marca), 3)


class ConsumidorEvento:
    """Consome um evento com offset manual, reentrega e DLQ.

    O handler recebe o dicionário do evento e o número da tentativa. Ele deve
    ser **idempotente**: a garantia aqui é de entrega pelo menos uma vez, não de
    processamento exatamente uma vez.

    Grupo, tópico e DLQ vêm da topologia do evento, não de settings soltas: é o
    que permite que ``pedido-worker`` e ``notificacao-worker`` usem a mesma
    classe sem que um possa ler o evento do outro.
    """

    def __init__(
        self,
        handler: Callable[[Dict[str, Any], int], None],
        topologia: TopologiaEvento,
        client_id: str = "synapseshop-worker",
    ) -> None:
        self._handler = handler
        self._topologia = topologia
        self._client_id = client_id
        self._consumidor: Optional[Consumer] = None
        self._parado = False
        self._particoes: List[int] = []
        self._ultimo_evento = time.monotonic()

    def parar(self) -> None:
        self._parado = True

    @property
    def particoes(self) -> List[int]:
        """Partições atribuídas a este consumidor dentro do grupo."""
        return list(self._particoes)

    @property
    def topologia(self) -> TopologiaEvento:
        return self._topologia

    def executar(self) -> None:
        """Consome em laço até ``parar()`` ou o broker cair.

        O consumidor é reconstruído só quando a conexão realmente cai; o laço
        interno apenas bombeia eventos, para que uma mensagem em processamento
        não seja interrompida por um tique do laço externo.
        """
        while not self._parado:
            consumidor = None
            try:
                # O broker roda com auto-criação desligada: quem garante a
                # topologia é a aplicação. Declarar aqui permite subir o worker
                # antes da API (e vice-versa) sem estado inicial compartilhado.
                declarar_topologia()
                consumidor = Consumer(
                    {
                        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                        "group.id": self._topologia.grupo,
                        "enable.auto.commit": False,
                        "auto.offset.reset": settings.KAFKA_AUTO_OFFSET_RESET,
                        "session.timeout.ms": settings.KAFKA_SESSION_TIMEOUT_MS,
                        "max.poll.interval.ms": settings.KAFKA_MAX_POLL_INTERVAL_MS,
                        "client.id": f"{self._client_id}-{uuid.uuid4().hex[:6]}",
                    }
                )
                consumidor.subscribe(
                    [self._topologia.topico],
                    on_assign=self._ao_atribuir,
                    on_revoke=self._ao_revogar,
                )
                self._consumidor = consumidor
                self._ultimo_evento = time.monotonic()
                while not self._parado:
                    msg = consumidor.poll(settings.KAFKA_POLL_TIMEOUT_S)
                    if msg is None:
                        self._registrar_ociosidade()
                        continue
                    if msg.error():
                        # _PARTITION_EOF é notificação de fim de log, não falha:
                        # tratá-la como erro derrubaria o consumidor no idle.
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        raise KafkaException(msg.error())
                    self._ultimo_evento = time.monotonic()
                    self._ao_receber(msg)
            except KeyboardInterrupt:
                _log("mensageria.consumidor.interrompido")
            except Exception as exc:  # noqa: BLE001 - reconecta com backoff
                _log(
                    "mensageria.consumidor.falha",
                    erro=_erro_do_broker(exc),
                    broker="kafka",
                    topico=self._topologia.topico,
                    grupo=self._topologia.grupo,
                )
                time.sleep(2)
            finally:
                self._fechar(consumidor)

    def _registrar_ociosidade(self) -> None:
        """Batimento do consumidor ocioso.

        "O worker está vivo" não aparece em log nenhum quando não há tráfego, e
        essa é exatamente a situação em que se duvida do worker. O registro sai
        no nível ``info`` — é evidência de operação, não alarme — e só quando o
        silêncio já dura mais que ``MENSAGERIA_HEARTBEAT_S``.
        """
        if settings.MENSAGERIA_HEARTBEAT_S <= 0:
            return
        silencio = time.monotonic() - self._ultimo_evento
        if silencio < settings.MENSAGERIA_HEARTBEAT_S:
            return
        self._ultimo_evento = time.monotonic()
        _log(
            "mensageria.consumidor.ocioso",
            topico=self._topologia.topico,
            grupo=self._topologia.grupo,
            cliente=self._client_id,
            particoes=self._particoes,
            silencio_s=round(silencio, 1),
        )

    def _fechar(self, consumidor) -> None:
        if consumidor is not None:
            try:
                consumidor.close()
            except Exception:  # noqa: BLE001
                pass
        if consumidor is self._consumidor:
            self._consumidor = None
        self._particoes = []

    def _ao_atribuir(self, consumidor, particoes) -> None:
        self._particoes = [p.partition for p in particoes]
        _log(
            "kafka.consumidor.particoes",
            grupo=self._topologia.grupo,
            topico=self._topologia.topico,
            cliente=consumidor.memberid() if hasattr(consumidor, "memberid") else None,
            particoes=self._particoes,
            total_particoes=settings.KAFKA_PARTICOES,
        )

    def _ao_revogar(self, _consumidor, particoes) -> None:
        _log(
            "kafka.consumidor.rebalanceamento",
            grupo=self._topologia.grupo,
            topico=self._topologia.topico,
            particoes_revogadas=[p.partition for p in particoes],
        )
        self._particoes = []

    def _confirma(self, msg: Message, contexto: str) -> None:
        """Faz commit do offset somente depois do efeito."""
        try:
            self._consumidor.commit(message=msg, asynchronous=False)
        except Exception as exc:  # noqa: BLE001
            _log("kafka.commit.falhou", erro=_erro_do_broker(exc), contexto=contexto)

    def _tentativa(self, cabecalhos) -> int:
        """Lê ``x-retry-count`` dos headers, tolerando bytes e texto."""
        if not cabecalhos:
            return 0
        for nome, valor in cabecalhos:
            if nome != HEADER_TENTATIVA:
                continue
            if isinstance(valor, bytes):
                valor = valor.decode("utf-8", "replace")
            try:
                return int(valor or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def _ao_receber(self, msg: Message) -> None:
        cabecalhos = list(msg.headers() or [])
        tentativa = self._tentativa(cabecalhos)
        inicio = time.perf_counter()
        tempo_fila_ms = _tempo_de_fila(msg)
        try:
            evento = json.loads(msg.value().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            # Corpo ilegível não tem como ser reprocessado: vai direto para a DLQ.
            self._matar(msg, cabecalhos, None, None, tentativa,
                        f"corpo invalido: {exc}", inicio, tempo_fila_ms)
            return

        chave = evento.get("idempotency_key") if isinstance(evento, dict) else None
        try:
            self._handler(evento, tentativa)
        except Exception as exc:  # noqa: BLE001 - política de falha do consumidor
            self._reentregar(msg, cabecalhos, evento, chave, exc, tentativa, inicio, tempo_fila_ms)
            return

        self._confirma(msg, "ok")
        _log(
            "mensageria.consumido",
            correlation_id=evento.get("correlation_id") if isinstance(evento, dict) else None,
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            tentativa=tentativa,
            resultado="ok",
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    def _reentregar(self, msg, cabecalhos, evento, chave, exc, tentativa, inicio, tempo_fila_ms) -> None:
        """Republica com tentativa+1 e recuo exponencial, ou mata para a DLQ."""
        if tentativa >= settings.MENSAGERIA_MAX_RETRIES:
            self._matar(msg, cabecalhos, evento, chave, tentativa, str(exc), inicio, tempo_fila_ms)
            return

        proxima = tentativa + 1
        espera = _esperar_reentrega(proxima)
        republished = self._publicar_retencao(
            evento,
            chave,
            {HEADER_TENTATIVA: proxima, HEADER_ERRO: str(exc)[:500]},
        )
        if republished is None:
            # Sem confirmar a republicação, o offset não é commitado: a
            # mensagem volta a ser entregue em vez de ser perdida.
            _log(
                "mensageria.reentrega.falhou",
                idempotency_key=chave,
                tentativa=tentativa,
                topico=msg.topic(),
                particao=msg.partition(),
                offset=msg.offset(),
                erro="broker nao confirmou a republicacao; offset nao commitado",
            )
            time.sleep(espera)
            return

        time.sleep(espera)
        self._confirma(msg, f"reentrega:{proxima}")
        _log(
            "mensageria.reentrega",
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            tentativa=tentativa,
            proxima_tentativa=proxima,
            espera_ms=round(espera * 1000, 3),
            erro=str(exc)[:500],
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    def _matar(self, msg, cabecalhos, evento, chave, tentativa, erro, inicio, tempo_fila_ms) -> None:
        """Esgotou as tentativas: publica na DLQ e então confirma o offset."""
        cabecalhos_dlq = {
            HEADER_TENTATIVA: tentativa,
            HEADER_ERRO: str(erro)[:500],
            "x-tópico-origem": msg.topic(),
            "x-particao-origem": str(msg.partition()),
            "x-offset-origem": str(msg.offset()),
            "x-morto-em": str(int(time.time() * 1000)),
        }
        publicada = self._publicar_retencao(
            evento,
            chave,
            cabecalhos_dlq,
            topico=self._topologia.dlq,
        )
        if publicada is None:
            _log(
                "mensageria.dlq.falhou",
                idempotency_key=chave,
                tentativa=tentativa,
                erro="broker nao confirmou a publicacao na DLQ; offset nao commitado",
            )
            return
        self._confirma(msg, "dlq")
        _log(
            "mensageria.dlq",
            idempotency_key=chave,
            topico=msg.topic(),
            particao=msg.partition(),
            offset=msg.offset(),
            dlq=self._topologia.dlq,
            tentativa=tentativa,
            erro=str(erro)[:500],
            tempo_fila_ms=tempo_fila_ms,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    def _publicar_retencao(self, evento, chave, cabecalhos, topico=None) -> Optional[Tuple[int, int]]:
            """Republica o mesmo corpo com novos headers, para reentrega ou DLQ.

            Um produtor dedicado é criado por chamada: o consumidor segura um
            ``Consumer`` de uma partição por vez, e misturar os papéis no mesmo
            objeto tornaria a reconexão do consumidor dependente da publicação.
            """
            destino = topico or self._topologia.topico
            cabecalhos = {str(nome): str(valor) for nome, valor in (cabecalhos or {}).items()}
            if not isinstance(evento, dict) or not chave:
                # Sem corpo reenviável (JSON inválido), a DLQ recebe o registro bruto
                # para que a mensagem morta continue inspecionável.
                valor = evento if isinstance(evento, (bytes, str)) else json.dumps(
                    {"erro": "evento sem corpo reenviável"}, ensure_ascii=False
                )
                valor = valor.encode("utf-8") if isinstance(valor, str) else valor
                chave = chave or str(uuid.uuid4())
            else:
                valor = json.dumps(evento, ensure_ascii=False).encode("utf-8")

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
                    "client.id": self._client_id,
                }
            )
            try:
                produtor.produce(
                    topic=destino,
                    key=str(chave).encode("utf-8"),
                    value=valor,
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
