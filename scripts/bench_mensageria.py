"""Benchmark da Camada 5: latência de ponta a ponta e throughput.

Mede o caminho real da aplicação — ``POST /api/v1/pedidos/`` publica, o
``pedido-worker`` consome e persiste — em vez de um producer/consumer avulso.
Isso importa porque a latência que o usuário enxerga inclui as três etapas:
chamada HTTP, confirmação do broker (``acks=all``) e commit do offset no worker.

Dois modos, porque medem coisas diferentes:

``--modo api``
    Produção em rajada. ``--pedidos N`` pedidos são criados e a latência de cada
    requisição é anotada. Depois o script espera os N pedidos saírem de
    ``PENDENTE`` para ``PROCESSANDO``, e essa espera é o tempo de drenagem.
    Pergunta: com a taxa de produção real, quanto o consumidor consegue acompanhar?

``--modo drenagem``
    Backlog grande e conhecido, com o worker parado durante o enchimento.
    Mede o teto de consumo, que o modo ``api`` nunca revela (lá o produtor é o
    gargalo, a ~11 req/s). Exige duas fases:

        docker compose stop pedido-worker
        python scripts/bench_mensageria.py --modo drenagem --fase preencher --pedidos 1000
        # subir o worker em outra janela, e medir a queda do backlog:
        python scripts/bench_mensageria.py --modo drenagem --fase medir --espera 300

A latência de ponta a ponta por pedido é ``criação (created_at) ate o instante
em que o consumidor gravou processado_em``: mede quando o efeito ficou visível,
e não só quando a requisição voltou. O backlog, não o log do worker, é a
origem do throughput: o log não distingue mensagem nova de reentrega.

Sobre o throttle da API (200/min por usuário): ele cortaria a coleta da métrica
em ~200 requisições, e um 429 no meio da rajada faria o script descartar os
pedidos mais lentos — justamente os que compõem a cauda dos percentis. Ele é
proteção de produto, não da Camada 5, então o script aguarda a janela expirar
uma vez e segue, sem precisar reconfigurar a API. Para medir sem essa espera,
suba o limite no mesmo comando que sobe a API:

    $env:THROTTLE_USER='5000/min'; $env:THROTTLE_ANON='5000/min'
    docker compose up -d --force-recreate api

Note que ``docker compose up`` recria os serviços de que a API depende, e
qualquer ``docker compose up <servico>`` recria a API: se o limite só existe na
variável de ambiente da sessão, ele se perde no comando seguinte.

Para comparar paralelismo, rode uma vez com 1 worker
(``docker compose up -d pedido-worker``) e outra com 3
(``docker compose up -d --scale pedido-worker=3``), mantendo o mesmo
``--pedidos``. O relatório em JSON fica em ``docs/resultados_bench_aula10.json``
(ou no caminho de ``BENCH_RESULTADO``) e é a origem dos números de
``docs/METRICAS_AULA10.md``.
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from uuid import uuid4

BASE_URL = os.environ.get("BENCH_BASE_URL", "http://localhost:8000")
ADMIN = {"username": "admin", "password": "admin"}
USER = {"username": "user", "password": "user"}
BROKER = os.environ.get("MENSAGERIA_BROKER", "kafka").strip().lower()
KAFKA_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICO = os.environ.get("KAFKA_TOPICO_PEDIDO_CRIADO", "pedidos.pedidocriado")
GRUPO = os.environ.get("KAFKA_GRUPO_CONSUMIDORES", "pedido-worker")
FILA = os.environ.get("RABBITMQ_FILA_PEDIDO_CRIADO", "pedidos.pedidocriado")
RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "guest")
ARQUIVO_RESULTADO = os.environ.get(
    "BENCH_RESULTADO", "docs/resultados_bench_aula10.json"
)


def _instante(iso):
    """Converte o ISO 8601 do Django em epoch em segundos.

    `created_at` e `processado_em` vêm com o mesmo deslocamento de fuso, então a
    subtração é direta; o `Z` final é tratado porque o DRF o usa em alguns campos.
    """
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _backlog():
    """Quantas mensagens ainda não foram processadas, medido no broker.

    Kafka: soma (fim do log - offset confirmado) por partição. É o lag do grupo,
    que é a unidade real de paralelismo da Camada 5.
    RabbitMQ: mensagens prontas na fila, pela Management API.
    """
    if BROKER == "kafka":
        try:
            from confluent_kafka import Consumer, ConsumerGroupTopicPartitions
            from confluent_kafka.admin import AdminClient

            admin = AdminClient({"bootstrap.servers": KAFKA_SERVERS})
            futuros = admin.list_consumer_group_offsets(
                [ConsumerGroupTopicPartitions(GRUPO)], request_timeout=10
            )
            confirmados = futuros[GRUPO].result(timeout=15)
            consumidor = Consumer(
                {"bootstrap.servers": KAFKA_SERVERS, "group.id": "bench-inspecao"}
            )
            try:
                total = 0
                for tp in confirmados.topic_partitions:
                    fim = consumidor.get_watermark_offsets(
                        tp, timeout=10, cached=False
                    )[1]
                    # Offset negativo (ou inexistente) = partição nunca consumida.
                    if tp.offset is None or tp.offset < 0:
                        total += fim
                    else:
                        total += max(fim - tp.offset, 0)
                return total
            finally:
                consumidor.close()
        except Exception as exc:  # noqa: BLE001
            print(f"  ..    leitura de lag falhou: {exc}")
            return None

    try:
        import base64

        credencial = base64.b64encode(
            f"{RABBITMQ_USER}:{RABBITMQ_PASSWORD}".encode()
        ).decode()
        requisicao = urllib.request.Request(
            f"{RABBITMQ_API}/api/queues/%2F/{FILA}",
            headers={"Authorization": f"Basic {credencial}"},
        )
        with urllib.request.urlopen(requisicao, timeout=15) as resposta:
            fila = json.loads(resposta.read())
        # `messages` é what's ready + unacked; os não confirmados também contam
        # como trabalho em voo.
        return (fila.get("messages") or 0) + (fila.get("messages_unacknowledged") or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"  ..    leitura da fila falhou: {exc}")
        return None


def _req(metodo, caminho, dados=None, token=None, timeout=30):
    corpo = json.dumps(dados).encode() if dados is not None else None
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    requisicao = urllib.request.Request(
        f"{BASE_URL}{caminho}", method=metodo, data=corpo, headers=cabecalhos
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            bruto = resposta.read()
            return resposta.status, (json.loads(bruto) if bruto else None)
    except urllib.error.HTTPError as exc:
        bruto = exc.read()
        try:
            return exc.code, json.loads(bruto)
        except json.JSONDecodeError:
            return exc.code, None


_JANELA_THROTTLE_ESPERADA = False


def _req_tolerante(metodo, caminho, dados=None, token=None, timeout=30):
    """Executa a chamada e absorve o 429 do throttle esperando a janela.

    A rajada do benchmark faz centenas de requisições em menos de um minuto, e o
    throttle padrão (200/min por usuário) corta no meio. A leitura e a escrita
    são parte do instrumento de medição, não do caminho medido, então o harness
    espera a janela expirar uma única vez e segue — em vez de descartar pedidos
    da amostra, que distorceria os percentis justamente nas respostas mais
    lentas.
    """
    global _JANELA_THROTTLE_ESPERADA
    status, payload = _req(metodo, caminho, dados, token, timeout)
    if status == 429 and not _JANELA_THROTTLE_ESPERADA:
        print("  ..    throttle atingido; aguardando a janela de 60s para continuar")
        time.sleep(61)
        _JANELA_THROTTLE_ESPERADA = True
        status, payload = _req(metodo, caminho, dados, token, timeout)
    return status, payload


def _percentil(valores, fracao):
    """Percentil por interpolação: mede cauda, que é onde a latência dói."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = fracao * (len(ordenados) - 1)
    baixo = int(posicao)
    alto = min(baixo + 1, len(ordenados) - 1)
    peso = posicao - baixo
    return round(ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * peso, 3)


def _resumo(valores):
    if not valores:
        return {}
    return {
        "amostras": len(valores),
        "min_ms": round(min(valores), 2),
        "p50_ms": _percentil(valores, 0.50),
        "p95_ms": _percentil(valores, 0.95),
        "p99_ms": _percentil(valores, 0.99),
        "max_ms": round(max(valores), 2),
        "media_ms": round(statistics.fmean(valores), 2),
    }


def _token(credenciais):
    status, payload = _req("POST", "/api/v1/auth/token/", credenciais)
    if status != 200 or not payload or "access" not in payload:
        raise SystemExit(f"login falhou para {credenciais['username']}: {status}")
    return payload["access"]


def _preparar_catalogo(token, marca):
    """Cria categoria e item exclusivos da execução, para não colidir com outros."""
    status, categoria = _req_tolerante(
        "POST",
        "/api/v1/categories/",
        {"name": f"Bench Cat {marca}", "description": f"benchmark {marca}"},
        token,
    )
    if status != 201:
        raise SystemExit(f"criação de categoria falhou: {status} {categoria}")
    status, item = _req_tolerante(
        "POST",
        "/api/v1/items/",
        {"name": f"Bench Item {marca}", "price": "10.00", "category": categoria["id"]},
        token,
    )
    if status != 201:
        raise SystemExit(f"criação de item falhou: {status} {item}")
    return categoria["id"], item["id"]


def _criar_backlog(args, token_admin, token_user, item_id, marca):
    """Fase 1 do modo ``drenagem``: enche o broker com pedidos reais.

    Rodar com o worker parado. Cada pedido é um ``PENDENTE`` legítimo cujo
    evento já está publicado e esperando: quando o worker subir, o trabalho é o
    mesmo da produção normal (transição de estado + dedupe + commit), e não uma
    simulação.
    """
    print(f"== Enchendo backlog ({args.rotulo or 'execução'}) ==")
    criados = []
    for indice in range(args.pedidos):
        chave = f"pedido-drenagem-{marca}-{indice}"
        status, pedido = _req_tolerante(
            "POST",
            "/api/v1/pedidos/",
            {"idempotency_key": chave, "itens": [{"item_id": item_id, "quantidade": 1}]},
            token_user,
        )
        if status != 201:
            print(f"  ..    pedido {indice} falhou: {status}")
            continue
        criados.append((chave, pedido["id"], pedido.get("created_at")))
    print(f"  ..    {len(criados)} pedidos criados, backlog={_backlog()}")
    with open(ARQUIVO_RESULTADO, "w", encoding="utf-8") as arquivo:
        json.dump(
            {
                "rotulo": args.rotulo,
                "marca": marca,
                "modo": "drenagem-preenchido",
                "pedidos": [{"chave": c, "id": i, "criado_em": t} for c, i, t in criados],
                "preenchido_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            arquivo,
            ensure_ascii=False,
            indent=2,
        )
        arquivo.write("\n")
    print(f"  backlog salvo em {ARQUIVO_RESULTADO}")
    return 0


def _medir_drenagem(args, token_admin):
    """Fase 2 do modo ``drenagem``: mede o tempo de esvaziamento do backlog."""
    with open(ARQUIVO_RESULTADO, encoding="utf-8") as arquivo:
        base = json.load(arquivo)
    pedidos = base.get("pedidos", [])
    if not pedidos:
        raise SystemExit(f"{ARQUIVO_RESULTADO} não tem backlog; rode --fase preencher antes")

    print(f"== Drenando backlog ({args.rotulo or 'execução'}) ==")
    inicial = _backlog()
    print(f"  ..    backlog inicial={inicial} de {len(pedidos)} pedidos")

    inicio = time.perf_counter()
    while time.perf_counter() - inicio < args.espera:
        if not _backlog():
            break
        time.sleep(0.25)
    tempo = time.perf_counter() - inicio

    latencias = []
    processados = 0
    for pedido in pedidos:
        status, dados = _req_tolerante(
            "GET", f"/api/v1/pedidos/{pedido['id']}/", token=token_admin, timeout=15
        )
        if status == 200 and dados and dados.get("processado_em") and pedido.get("criado_em"):
            processados += 1
            latencias.append(
                (_instante(dados["processado_em"]) - _instante(pedido["criado_em"])) * 1000
            )

    # O throughput usa a queda do backlog, não a contagem de pedidos
    # rastreados: o tópico pode ter mensagens de execuções anteriores, e elas
    # também foram consumidas dentro da janela medida.
    drenadas = max((inicial or 0) - (_backlog() or 0), 0)
    relatorio = {
        "rotulo": args.rotulo,
        "broker": BROKER,
        "modo": "drenagem",
        "marca": base.get("marca"),
        "pedidos_rastreados": len(pedidos),
        "backlog_inicial": inicial,
        "backlog_final": _backlog(),
        "mensagens_drenadas": drenadas,
        "pedidos_processados": processados,
        "tempo_drenagem_s": round(tempo, 3),
        "throughput_drenagem_msg_s": round(drenadas / tempo, 2) if tempo else None,
        "latencia_desde_criacao": _resumo(latencias),
        "coletado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    print(f"  ..    drenado em {tempo:.2f}s ({relatorio['throughput_drenagem_msg_s']} msg/s)")
    print("-- latência desde a criação (inclui a espera no backlog) --")
    for chave, valor in relatorio["latencia_desde_criacao"].items():
        print(f"   {chave:>10}: {valor}")

    with open(ARQUIVO_RESULTADO, "w", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
        arquivo.write("\n")
    print(f"\n  relatório em {ARQUIVO_RESULTADO}")
    return 0 if processados == len(pedidos) else 1


def main():
    parser = argparse.ArgumentParser(description="Benchmark da Camada 5 (Kafka/RabbitMQ)")
    parser.add_argument("--pedidos", type=int, default=200, help="pedidos por execução")
    parser.add_argument("--rotulo", default="", help="identifica a execução no relatório")
    parser.add_argument(
        "--modo",
        choices=("api", "drenagem"),
        default="api",
        help=(
            "api: rajada ponta a ponta medindo o sistema inteiro; "
            "drenagem: esvazia um backlog pré-preenchido para medir o teto de consumo"
        ),
    )
    parser.add_argument(
        "--fase",
        choices=("preencher", "medir"),
        default="",
        help="fase do modo drenagem (padrão: medir)",
    )
    parser.add_argument(
        "--espera",
        type=int,
        default=180,
        help="segundos máximos para o backlog drenar",
    )
    args = parser.parse_args()

    marca = uuid4().hex[:8]
    token_admin = _token(ADMIN)
    token_user = _token(USER)

    if args.modo == "drenagem" and args.fase == "preencher":
        _, item_id = _preparar_catalogo(token_admin, marca)
        return _criar_backlog(args, token_admin, token_user, item_id, marca)
    if args.modo == "drenagem":
        return _medir_drenagem(args, token_admin)

    _, item_id = _preparar_catalogo(token_admin, marca)

    print(f"== Benchmark ({args.rotulo or 'execução'}) ==")
    print(f"  pedidos={args.pedidos} item={item_id} marca={marca}")

    # --- 1. produção em rajada ------------------------------------------------
    latencia_http = []
    criados = []
    falhas = 0
    inicio = time.perf_counter()
    for indice in range(args.pedidos):
        chave = f"pedido-bench-{marca}-{indice}"
        t0 = time.perf_counter()
        status, pedido = _req_tolerante(
            "POST",
            "/api/v1/pedidos/",
            {
                "idempotency_key": chave,
                "itens": [{"item_id": item_id, "quantidade": 1}],
            },
            token_user,
        )
        latencia_http.append((time.perf_counter() - t0) * 1000)
        if status != 201 or not pedido or pedido.get("evento_publicado") is not True:
            falhas += 1
            continue
        criados.append((chave, pedido["id"], pedido.get("created_at")))
    tempo_producao = time.perf_counter() - inicio
    print(
        f"  ..    produção: {len(criados)}/{args.pedidos} criados em "
        f"{tempo_producao:.2f}s ({len(criados) / tempo_producao:.1f} req/s), "
        f"{falhas} falha(s)"
    )

    # --- 2. drenagem do backlog ----------------------------------------------
    # O sinal de "terminou" é o backlog do broker, não o polling pedido a pedido.
    # Consultar N pedidos por HTTP levava mais tempo que o worker para consumir,
    # e media o instrumento em vez do sistema — o resultado era praticamente
    # idêntico com 1 e com 3 consumidores, o que é justamente o oposto do que
    # paralelismo por partição deveria mostrar.
    #
    # Backlog zerado significa efeito persistido, porque o worker só confirma o
    # offset depois de gravar o estado (a mesma ordem que garante a entrega).
    inicio_drenagem = time.perf_counter()
    backlog = _backlog()
    while backlog and time.perf_counter() - inicio_drenagem < args.espera:
        time.sleep(0.5)
        backlog = _backlog()
    tempo_drenagem = time.perf_counter() - inicio_drenagem
    if tempo_drenagem < 1:
        # Tempo de drenagem perto de zero significa que o consumo acompanhou a
        # produção durante toda a rajada: o gargalo está na entrada, não no
        # consumidor. Dividir por esse valor não mediria throughput de consumo,
        # mediria o intervalo de polling.
        print(
            f"  ..    drenagem: backlog {backlog} já zerado quando medido "
            f"(consumo acompanhou a produção de {len(criados) / tempo_producao:.1f} req/s)"
        )
    else:
        print(
            f"  ..    drenagem: backlog {backlog} esvaziado em {tempo_drenagem:.2f}s "
            f"({len(criados) / tempo_drenagem:.1f} msg/s no consumo)"
        )

    # --- 3. latência ponta a ponta, do relógio do servidor -------------------
    # `created_at` e `processado_em` são gravados pelo backend com o mesmo
    # relógio. A diferença entre os dois é a latência real da Camada 5, e não
    # depende de quando este script conseguiu perguntar.
    latencia_total = []
    processados = 0
    for chave, pedido_id, criado_em in criados:
        status, pedido = _req_tolerante(
            "GET", f"/api/v1/pedidos/{pedido_id}/", token=token_admin, timeout=15
        )
        if status != 200 or not pedido or not pedido.get("processado_em") or not criado_em:
            continue
        processados += 1
        latencia_total.append(
            (_instante(pedido["processado_em"]) - _instante(criado_em)) * 1000
        )
    print(f"  ..    {processados}/{len(criados)} com estado PROCESSANDO lido do servidor")

    # --- 4. relatório ---------------------------------------------------------
    total = time.perf_counter() - inicio
    pendentes = len(criados) - processados
    relatorio = {
        "rotulo": args.rotulo,
        "broker": BROKER,
        "pedidos_solicitados": args.pedidos,
        "pedidos_criados": len(criados),
        "falhas_de_publicacao": falhas,
        "pedidos_processados": processados,
        "pedidos_pendentes_ao_fim": pendentes,
        "tempo_total_s": round(total, 3),
        "tempo_producao_s": round(tempo_producao, 3),
        "tempo_drenagem_s": round(tempo_drenagem, 3),
        "backlog_final": backlog,
        "throughput_total_msg_s": round(processados / total, 2) if total else None,
        # Só tem sentido se o consumidor realmente acumulou trabalho. Com taxa de
        # produção de ~11 req/s e consumo de ~100 msg/s, o worker esvazia a fila
        # durante a rajada e `tempo_drenagem` tende a 0: dividir por ele produz um
        # número enorme que não é throughput de ninguém. Nesse caso o gargalo é
        # o produtor, e o teto de consumo aparece em `--modo drenagem`.
        "throughput_consumo_msg_s": (
            round(len(criados) / tempo_drenagem, 2) if tempo_drenagem > 1.0 else None
        ),
        "latencia_http_criacao": _resumo(latencia_http),
        "latencia_ponta_a_ponta": _resumo(latencia_total),
        "coletado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    print("\n-- latência de criação (HTTP) --")
    for chave, valor in relatorio["latencia_http_criacao"].items():
        print(f"   {chave:>10}: {valor}")
    print("-- latência ponta a ponta (criacao -> PROCESSANDO) --")
    for chave, valor in relatorio["latencia_ponta_a_ponta"].items():
        print(f"   {chave:>10}: {valor}")
    print(
        f"   {'throughput':>10}: {relatorio['throughput_total_msg_s']} msg/s "
        f"(consumo {relatorio['throughput_consumo_msg_s']} msg/s)"
    )

    os.makedirs(os.path.dirname(ARQUIVO_RESULTADO) or ".", exist_ok=True)
    with open(ARQUIVO_RESULTADO, "w", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
        arquivo.write("\n")
    print(f"\n  relatório em {ARQUIVO_RESULTADO}")

    if falhas or pendentes:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
