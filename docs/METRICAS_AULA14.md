# Métricas da Aula 14 — `llm_service` e assistente de IA

A Aula 14 não tem um *benchmark* de carga: o que se mede é a **telemetria que a
própria camada de IA recolhe** e expõe em `GET /api/v1/assist/stats/`. Como o
provedor de LLM é externo e pago, os ensaios reproduzíveis usam um provedor
substituído por *mock* — os tokens e o custo são determinísticos; a latência é a
do ambiente local, não a do provedor real.

## Ambiente

| Item | Valor |
| --- | --- |
| API | Django + DRF |
| Serviço | `services/llm.py` (transporte `urllib`, sem dependência nova) |
| Provedor | compatível com Chat Completions (`LLM_BASE_URL`, `LLM_MODEL=gpt-4o-mini`) |
| Timeout por tentativa | `LLM_TIMEOUT_S=5` |
| Retry | `LLM_MAX_TENTATIVAS=3`, backoff `250 ms` → teto `5000 ms`, com jitter |
| Circuito | abre após `3` falhas; repouso `30 s` |
| Teto de saída | `LLM_MAX_TOKENS_LIMITE=1024` |

## Exemplo de chamada (provedor mockado)

Entrada: `mode=summarize` com uma linha contendo e-mail e CPF.

Resposta do endpoint:

```json
{
  "answer": "Resumo: falha de checkout para cliente.",
  "meta": {
    "tokens_prompt": 120,
    "tokens_output": 80,
    "tentativas": 1,
    "latencia_ms": 0.01,
    "custo_estimado_usd": 6.6e-05,
    "redacoes": 2,
    "modelo": "gpt-4o-mini"
  }
}
```

A telemetria acumulada (`GET /api/v1/assist/stats/`) após essa chamada:

```json
{
  "chamadas": 1,
  "sucessos": 1,
  "erros": 0,
  "taxa_erro": 0.0,
  "tokens_prompt": 120,
  "tokens_output": 80,
  "tokens_total": 200,
  "latencia_media_ms": 0.01,
  "custo_total_usd": 6.6e-05,
  "erros_por_tipo": {},
  "circuito": {"estado": "closed", "falhas_consecutivas": 0}
}
```

As duas redações do exemplo são o e-mail (`joao@example.com`) e o CPF
(`111.222.333-44`) — nenhum dos dois aparece no `answer` nem nos logs, apenas a
contagem `redacoes: 2`.

## O que a telemetria recolhe

| Campo | Significado |
| --- | --- |
| `chamadas` | Total de invocações que chegaram ao serviço (sucesso + erro). |
| `sucessos` / `erros` | Desfecho de cada chamada. |
| `taxa_erro` | `erros / chamadas` (0.0 sem chamadas). |
| `tokens_prompt` / `tokens_output` / `tokens_total` | Consumo relatado pelo provedor. |
| `latencia_media_ms` | Média de latência ponta a ponta, **incluindo** esperas de retry. |
| `custo_total_usd` | Custo estimado acumulado (ver fórmula). |
| `erros_por_tipo` | Contagem por classe de erro (`LLMTimeout`, `LLMTaxaLimitada`, …). |
| `circuito` | Estado (`closed`/`open`/`half-open`) e falhas consecutivas. |

## Fórmula do custo estimado

O provedor pode não devolver preço; o custo é estimado a partir dos tokens e de
preços configuráveis por milhão de tokens:

```
custo = tokens_prompt / 1_000_000 · LLM_PRECO_PROMPT_USD_MILHAO
      + tokens_output / 1_000_000 · LLM_PRECO_OUTPUT_USD_MILHAO
```

Com `LLM_PRECO_PROMPT_USD_MILHAO=0.15` e `LLM_PRECO_OUTPUT_USD_MILHAO=0.60`, o
exemplo acima dá `120/1e6·0.15 + 80/1e6·0.60 = 6.6e-05` USD. Com os preços no
default `0`, os **tokens seguem contados** e o custo sai `0.0` — falta de preço
não vira falta de métrica.

## Como ler a latência

`latencia_media_ms` mede o tempo total da chamada de `assistir()`, então ela
**inclui as esperas do backoff** quando há retry. Numa chamada que passou no
primeiro disparo, é só o custo do provedor; numa que precisou de duas tentativas
com 429, soma a espera entre elas (250 ms base, com jitter). Isso é intencional:
a métrica reflete o que o **usuário** esperou, não o tempo "limpo" do provedor.
Nos ensaios com provedor mockado a latência é ~0 (não há rede), por isso o valor
não serve como estimativa do provedor real.

## Evidência de teste

A camada é exercitada por testes unitários e de integração com o provedor sempre
substituído por *mock* (nenhum teste toca a Internet):

| Arquivo | Foco |
| --- | --- |
| `tests/unit/test_services_llm.py` | Mapeamento de falhas (429/5xx/4xx/timeout/rede), retry, backoff, circuito (abre/half-open/fecha), telemetria e custo. |
| `tests/unit/test_services_redacao.py` | Redação de cada tipo de PII/segredo, redação antes do envio e ausência do dado no log. |
| `tests/integration/test_api_assist.py` | Contrato HTTP: 401, 400 de validação, 200, 429, 502, 503, 504 e métricas admin. |

Total: **64 testes** cobrindo a Aula 14. `services/llm.py` e
`services/prompts.py` ficam em **100%** de cobertura; a suíte completa passa de
99% e satisfaz o `fail_under=85` do `.coveragerc`.

## Limites conhecidos desta medição

- **Provedor mockado.** Tokens e custo são determinísticos por construção; não há
  medição de latência do provedor real nem das tarifas vigentes.
- **Custo é estimativa.** Só é tão bom quanto os preços em `LLM_PRECO_*`; o
  default `0` desliga a conversão para dólar, não a contagem de tokens.
- **Telemetria por processo.** Os contadores vivem em memória; com vários workers,
  cada um reporta o seu recorte. Agregação externa é item de backlog.
- **Redação é heurística.** A contagem confirma que a política rodou; não prova
  que todo formato concebível de dado sensível foi coberto.
