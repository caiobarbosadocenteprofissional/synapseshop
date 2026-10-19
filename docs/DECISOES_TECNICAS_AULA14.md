# Decisões técnicas — Aula 14 (Assistente de IA e `llm_service`)

Registro do *porquê* de cada escolha da camada de IA. O *como* está em
`services/llm.py`, `services/prompts.py`, `api/serializers.py`, `api/views.py` e
`config/settings.py`. Os números citados estão em
[`METRICAS_AULA14.md`](METRICAS_AULA14.md).

---

## 1. Provedor externo via `urllib`, sem nova dependência

**Decisão.** O transporte HTTP do `llm_service` usa apenas a biblioteca padrão
(`urllib.request`), isolado na função `_http_post_json`.

**Por quê.** A aula é sobre **resiliência**, não sobre adotar um cliente HTTP.
Um `requests`/`httpx` traria timeout e retry de fábrica, o que esconderia
justamente o que a aula pede para construir à mão. Usar a stdlib mantém uma
superfície de dependência a menos para atualizar e deixa explícitas as três
políticas (timeout, retry e circuito) que a spec exige.

**Trade-off.** `urllib` é verboso e não tem retry embutido — por isso o retry é
código nosso, testável e explícito. Isolar o transporte em um único ponto
(`_http_post_json`) é o que permite aos testes trocarem o provedor por um mock
sem tocar no resto do serviço.

## 2. Timeout por tentativa de 5 segundos (`LLM_TIMEOUT_S`)

**Decisão.** Cada requisição ao provedor tem prazo curto e configurável, com
default de 5s.

**Por quê.** Sem prazo, uma lentidão do provedor vira requisição pendurada e
esgota os workers da API. Um limite de 5s transforma "travou" em "falhou", que
é tratável (retry, circuito, erro de domínio) em vez de incontornável.

**Trade-off.** Um timeout curto pode abandonar uma resposta que viria aos 6s.
Para um assistente interativo, 5s é o teto razoável do usuário esperando; a
variável permite alongar quando a operação for offline.

## 3. Retry apenas para erros reentregáveis, com backoff exponencial e jitter

**Decisão.** Até `LLM_MAX_TENTATIVAS` (3) tentativas, com espera
`min(base·2^(n-1), teto)` e *equal jitter* (metade fixa + metade aleatória).
Só `LLMTimeout`, `LLMTaxaLimitada` (429) e `LLMIndisponivel` (5xx/rede) são
reentregues; `LLMPayloadInvalido` (4xx) não é.

**Por quê.** Repetir imediatamente em ritmo fixo sincroniza todos os clientes e
piora a sobrecarga que causou a falha; o jitter desalinha quem subiu junto.
Repetir uma requisição **malformada** só repete o erro — por isso os erros de
4xx (exceto 429) saem do conjunto reentregável.

**Trade-off.** O jitter torna o tempo de resposta não determinístico (por isso
`_dormir` é um ponto isolado, que os testes substituem). O teto do backoff
(`LLM_BACKOFF_MAX_MS`) impede que a espera exploda.

## 4. Circuit breaker com estado em memória, limites lidos das settings

**Decisão.** `CircuitBreaker` com os três estados (`closed`/`open`/`half-open`).
Após `LLM_CIRCUITO_LIMITE_FALHAS` falhas consecutivas o circuito **abre** e passa
a falhar rápido (`LLMCircuitoAberto`, 503) sem tocar o provedor; após
`LLM_CIRCUITO_RESET_SEGUNDOS` entra em **half-open** e libera uma tentativa de
prova: se voltar a falhar, reabre; se passar, fecha.

**Por quê.** Depois de N falhas, insistir só soma latência ao usuário. O limite
e o repouso são lidos de `settings` **a cada transição** (e não no `__init__`),
para que testes e operação reconfigurarem sem recriar o objeto. O estado vive em
um objeto de módulo (`_CIRCUITO`), porque é o que precisa sobreviver entre
requisições.

**Trade-off.** O estado é por processo: com vários workers, cada um tem seu
circuito. Agregar em Redis/Prometheus é evolução registrada no backlog, não
escopo agora.

## 5. Erros de domínio carregam o status HTTP

**Decisão.** Cada erro do serviço tem um atributo `status_http`:
`LLMConfiguracaoAusente`/`LLMCircuitoAberto` → 503, `LLMTimeout` → 504,
`LLMTaxaLimitada` → 429, `LLMIndisponivel` → 502, `LLMPayloadInvalido` → 400.

**Por quê.** A view não deveria traduzir tipos de exceção em códigos: mapear
"provedor caiu" → 502 é uma decisão da camada de IA, junto da exceção. A view
fica fina (valida e delega) e o contrato HTTP fica no lugar onde o erro nasce.

## 6. Redação **antes** de enviar e antes de logar; só a contagem é registrada

**Decisão.** `redigir()` substitui e-mail, CPF/CNPJ, cartão, telefone, segredos
e `Bearer` por marcadores, e devolve `(texto, nº de redações)`. O texto redigido
é o que vai ao provedor e aos prompts; o log de auditoria guarda apenas a
**contagem** (`redacoes`), nunca o valor.

**Por quê.** O prompt é o último ponto do dado dentro de casa: a política de
privacidade tem de ser garantida **nossa**, não confiada ao provedor. Registrar
só a contagem torna a política auditável ("esta requisição redigiu 2 dados") sem
que o log de auditoria vire uma nova cópia do dado sensível.

**Trade-off.** Regex de PII é heurística: pode redigir a mais (falso positivo) ou
deixar escapar um formato não previsto. Redigir a mais é seguro; formatos novos
são um item de evolução (guardrails), não uma garantia de regex.

## 7. Telemetria em memória exposta por endpoint admin

**Decisão.** Contadores de latência, erros (por tipo), tokens e custo estimado,
em `_Telemetria` protegida por lock, lidos em `GET /api/v1/assist/stats/` e
zerados em `POST` (ambos admin-only).

**Por quê.** É o análogo de `/api/v1/cache/stats/`: transforma a camada de IA em
algo observável em vez de afirmado. O custo é **estimado** a partir de tokens e
de preços configuráveis (`LLM_PRECO_*_USD_MILHAO`, 0 = sem preço conhecido),
porque o provedor pode não devolver custo.

**Trade-off.** Em memória = métrica de processo único. Multi-worker exigiria
agregação externa (backlog).

## 8. A ausência de `LLM_API_KEY` é um kill-switch

**Decisão.** Sem `LLM_API_KEY`, `assistir()` levanta `LLMConfiguracaoAusente`
(503) e **nada** é enviado ao provedor. A imagem sobe normalmente sem a chave.

**Por quê.** A IA é opcional na stack: o projeto não pode deixar de subir por não
ter uma chave. Faltar chave é "desabilitado", não "quebrado", e o 503 comunica
isso sem vazar detalhes.

## 9. Prompt em módulo próprio, com dois modos

**Decisão.** `services/prompts.py` guarda os prompts de sistema (`summarize` e
`explain`), a normalização da entrada (`str` ou lista) e a montagem das
mensagens.

**Por quê.** O prompt é uma decisão de produto, não um detalhe de implementação:
define idioma, formato e limite de especulação, e é o artefato que a equipe
revisa quando a resposta sai errada. Versioná-lo à parte o torna revisável.

## 10. `max_tokens` limitado pelo servidor

**Decisão.** O serializer limita `max_tokens` a `LLM_MAX_TOKENS_LIMITE` (1024):
pedir mais devolve 400.

**Por quê.** O custo é por token; o cliente não pode escolher gastar sem teto. O
teto é do servidor mesmo que o pedido venha do cliente.

## 11. Escopo: sem cache de respostas nem guardrails adicionais

**Decisão.** Não há cache de respostas do LLM nem validação/sanitização de saída
(guardrails) nesta aula.

**Por quê.** Ambos são evoluções legítimas, mas fora do DoD da Aula 14, que pede
resiliência, redação de entrada e telemetria. Registrá-los como pendência é mais
honesto do que antecipá-los sob a diretriz SpecDD.
