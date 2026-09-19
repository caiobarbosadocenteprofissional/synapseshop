# PROMPTS-TEMPLATE.md — Template Padrão de Prompts de IA da Squad

> Padroniza a forma como o SynapseShop descreve requisitos, restrições e
> formatos de saída esperados ao acionar ferramentas de IA generativa.
> Todo uso efetivo de IA deve ser **registrado no histórico** em [`PROMPTS.md`](PROMPTS.md).

---

## 1. Estrutura obrigatória do prompt

Use o bloco abaixo como esqueleto ao escrever prompts para IA. Preencha
todos os campos; campos sem conteúdo devem ser removidos do prompt final
(para não induzir respostas vagas).

```markdown
## Contexto
- Domínio: <ex.: inventário, pedidos, pagamentos>
- Spec ativa: <arquivo da spec, ex.: specs/specs_da_aula_5.md>
- Stack e padrões vigentes: <ex.: Django/DRF, FastAPI, Docker multistage, pin de versões>

## Objetivo
<descreva O QUE deve ser feito, de forma curta e mensurável>

## Restrições (SpecDD / anti-antecipação)
- [ ] Aplicar somente o DoD da spec atual.
- [ ] Não antecipar aulas futuras (ex.: banco de dados, autenticação, mensageria, IA).
- [ ] Seguir as convenções já existentes no repositório (nomes, camadas, status codes).
- [ ] Não adicionar bibliotecas fora do escopo da spec.

## Entrada
<dados de exemplo ou referências que o agente deve considerar>

## Saída esperada (formato)
- Estrutura de arquivos/pastas: <árvore ou lista>
- Contratos da API: <método, rota, responsabilidade, status code>
- Modelos de dados (se aplicável): <campos, tipos, validações>
- Documentação: <arquivos a atualizar>

## Critérios de aceite
- [ ] <critério verificável 1>
- [ ] <critério verificável 2>
- [ ] O resultado NÃO contém código de aulas futuras.
```

---

## 2. Exemplo preenchido (referência — Aula 5)

```markdown
## Contexto
- Domínio: inventário (estoque)
- Spec ativa: specs/specs_da_aula_5.md
- Stack e padrões vigentes: FastAPI + Pydantic; Docker multistage non-root; pin de versões (`fastapi==0.141.*`, `uvicorn[standard]==0.53.*`)

## Objetivo
Criar o scaffold do microsserviço de inventário em FastAPI com modelos
Pydantic, tipagem estática nos endpoints e documentação automática em `/docs`.

## Restrições (SpecDD / anti-antecipação)
- [ ] Aplicar somente o DoD da Aula 5.
- [ ] SEM banco de dados (Aula 6) e SEM autenticação (Aula 7): estado em memória.
- [ ] Sem bibliotecas além de FastAPI/uvicorn.

## Entrada
Padrão de rotas mínimas: CRUD de itens de estoque; healthcheck em `/health`.

## Saída esperada (formato)
- Estrutura: `inventory/{Dockerfile, requirements.txt, app/{main,schemas,storage,routes}.py}`
- Contratos: GET/POST `/inventory/items`; GET/PATCH/DELETE `/inventory/items/{id}`;
  codes 200/201/204/404.
- Respostas padrão via models Pydantic (`HealthResponse`, `MessageResponse`, `InventoryItem`).

## Critérios de aceite
- [x] `/docs` acessível em http://localhost:8100/docs.
- [x] Nenhuma importação de banco ou auth.
```

---

## 3. Registro obrigatório no `PROMPTS.md`

Depois de usar a IA, adicione uma entrada no [`PROMPTS.md`](PROMPTS.md) com:

- **Data** — AAAA-MM-DD.
- **Autor(a)** — integrante que utilizou.
- **Ferramenta** — ferramenta/modelo usado.
- **Contexto** — objetivo do uso.
- **Prompt utilizado** — texto integral.
- **Resultado / Ajustes** — resultado obtido e intervenções manuais.

> Revisão humana: toda resposta gerada por IA deve ser validada por um
> integrante antes de integrar ao código (ver `docs/CHECKLIST_IA_SAFE.md`).