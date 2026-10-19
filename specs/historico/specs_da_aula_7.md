Spec: Autenticação JWT com papéis e throttling (Aula 7)

1. Objetivo

Implementar a autenticação JWT baseada em papéis (roles) e regras de throttling. O objetivo central é estabelecer segurança mínima para a API, aplicar proteção às rotas administrativas e configurar validações de acesso.

2. Contexto

Seguindo a diretriz de desenvolvimento incremental (SpecDD), esta etapa adiciona a camada de acesso seguro à infraestrutura existente, mantendo o escopo rigorosamente fechado. É terminantemente proibido antecipar lógicas de aulas futuras, como o sistema de cache-aside com Redis (Aula 8) ou mensageria com RabbitMQ/Kafka (Aulas 9–11).

3. Tarefas e Responsabilidades

Criar migrações com índices compostos, simular rollback seguro e implementar um repositório com transação e teste de tempo.

Definir os fluxos de autenticação (JWT/Session) e criar as roles "admin" e "user".

Configurar mecanismos de throttling e estabelecer a segurança mínima para a aplicação.

Aplicar permissões nos endpoints críticos da API e habilitar paginação e filtros coerentes.

Montar e atualizar a coleção do Postman contemplando cenários completos de login, sucesso, erro e acesso negado.

4. Requisitos de Entrega (Definition of Done)

[x] A autenticação JWT está totalmente funcional, possuindo pelo menos dois papéis de usuário distintos (admin e user).

[x] As proteções para as rotas administrativas estão devidamente criadas e implementadas.

[x] As regras de throttling e a segurança mínima foram configuradas nos endpoints da API.

[x] Os endpoints críticos possuem paginação e filtros coerentes habilitados.

[x] A coleção de testes no Postman foi atualizada com os cenários de sucesso, erro e acesso negado.

[x] O código gerado não contém placeholders ansiosos ou implementações de funcionalidades que só devem constar em etapas futuras.

---

## 5. Evidências de entrega (Aula 7)

- **Autenticação JWT + papéis:** `User` customizado com `role` (`admin`/`user`),
  rotas `/api/v1/auth/token/` e `/api/v1/auth/token/refresh/` com claim `role` no token e
  na resposta; usuários demo criados por `seed_demo_users` no start do container.
- **Proteção das rotas administrativas:** leitura autenticada (401 sem token) e escrita
  exclusiva `admin` (403 para `user`) via permission `IsAdminRole` em `api/views.py`.
- **Throttling e segurança mínima:** escopos `anon`, `user` e `login` (5/min nas rotas de
  token; 429 observado no 6º login, ver `docs/METRICAS_AULA7.md`).
- **Paginação e filtros:** `PageNumberPagination` (default 10, `?page_size=`) + `search`,
  `ordering` e filtros `is_active`/`category` nos itens.
- **Postman:** `docs/postman/SynapseShop_Aula7.postman_collection.json` com cenários de
  login sucesso/erro, refresh, 401, 403, CRUD admin, paginação/filtros e 429.
- **Anti-antecipação:** sem Redis, sem mensageria, sem `pytest`, sem IA e sem auth no
  `inventory` (decisões em `docs/DECISOES_TECNICAS_AULA7.md`).

> Observação: o item 1 da seção 3 ("migrações com índices compostos, rollback seguro e
> repositório transacional") é um trecho copiado da spec da Aula 6 e foi tratado como
> artefato — ver `docs/DECISOES_TECNICAS_AULA7.md` §2.