# Backlog — Aula 14 (Assistente de IA / `llm_service`)

Pendências e melhorias futuras identificadas ao implementar a Aula 14, fora do
escopo do DoD atual (diretrize SpecDD: nada de antecipação). Cada item está
pronto para virar uma *issue* no GitHub.

> **Nota operacional:** o `gh` CLI **não está autenticado** neste ambiente
> (`gh auth status` → "not logged into any GitHub hosts"), então estas *issues*
> ainda **não** foram criadas no repositório
> `caiobarbosadocenteprofissional/synapseshop`. Rode `gh auth login` e crie-as com
> `gh issue create --title ... --body ...` (ou pela interface web).

---

## 1. Cache de respostas do LLM

**Título:** `[IA] Cache de respostas do llm_service para prompts repetidos`

**Corpo:** Deduplicar chamadas idênticas (hash de `mode` + `logs` redigidos +
`temperature` + `max_tokens`) por um TTL curto em Redis, devolvendo o mesmo
`answer`/`meta` e marcando a origem (cache hit/miss) na resposta e na telemetria.
Reduz custo por token e latência em logs que se repetem. Cuidar da chave: só
após a redação, para não cachear nem indexar dado sensível.

**Labels sugeridas:** `ia`, `custo`, `enhancement`

## 2. Guardrails de saída

**Título:** `[IA] Guardrails de validação/sanitização da resposta do LLM`

**Corpo:** Validar a saída do provedor antes de devolvê-la (por exemplo, garantir
que não reintroduza PII redigida, que respeite o formato pedido no prompt e que
não contenha instruções perigosas). Hoje confiamos apenas no prompt de sistema.

**Labels sugeridas:** `ia`, `segurança`, `enhancement`

## 3. Agregação de telemetria multi-processo

**Título:** `[IA] Agregar telemetria do llm_service entre workers`

**Corpo:** A telemetria atual é em memória, por processo. Com vários workers da
API, `GET /api/v1/assist/stats/` mostra só o recorte do processo que atendeu a
requisição. Agregar em Redis ou exportar para Prometheus/OpenTelemetry.

**Labels sugeridas:** `ia`, `observabilidade`, `enhancement`

## 4. Redação extensível e configurável

**Título:** `[IA] Tornar a redação de PII extensível por configuração`

**Corpo:** Os padrões de redação são regex fixas no código. Permitir padrões
adicionais via settings (ou listas de termos/segredos) sem alterar `services/llm.py`,
e documentar o catálogo de padrões cobertos e os limites conhecidos.

**Labels sugeridas:** `ia`, `privacidade`, `enhancement`

## 5. Circuit breaker compartilhado

**Título:** `[IA] Circuit breaker distribuído para o provedor de LLM`

**Corpo:** O circuito é por processo: vários workers mantêm estados
independentes e podem martelar um provedor já degradado. Compartilhar o estado
(Redis) tornaria a proteção global.

**Labels sugeridas:** `ia`, `resiliência`, `enhancement`

## 6. Limite de uso do assistente por usuário

**Título:** `[IA] Limite de chamadas ao assistente por usuário`

**Corpo:** O endpoint consome tokens pagos e hoje só exige autenticação. Um
throttle dedicado (por usuário/papel) limita custo e abuso, complementando o
throttle global da Aula 7.

**Labels sugeridas:** `ia`, `custo`, `segurança`, `enhancement`
