Aqui estÃ¡ a especificaÃ§Ã£o completa para a **Aula 13** do projeto **SynapseShop**, elaborada estritamente de acordo com a metodologia **SpecDD (Specification-Driven Development)** e com base nos requisitos pedagÃ³gicos do plano de curso.

---

# Spec: DocumentaÃ§Ã£o Completa da API com OpenAPI/Swagger e Postman/Insomnia (Aula 13)

## 1. Objetivo

Padronizar, enriquecer e publicar a documentaÃ§Ã£o tÃ©cnica da API do SynapseShop com a especificaÃ§Ã£o OpeatuAPI/Swagger, assegurando convenÃ§Ãµes RESTful, esquemas de erro padronizados e a disponibilizaÃ§Ã£o de coleÃ§Ãµes para Postman/Insomnia com ambientes (*environments*) configurados.

## 2. Contexto

Na sequÃªncia do desenvolvimento de testes automatizados, a Aula 13 foca-se na documentaÃ§Ã£o interativa e na padronizaÃ§Ã£o rigorosa dos contratos das interfaces da API. Respeitando a diretriz de desenvolvimento incremental (SpecDD), a equipa deve focar-se exclusivamente na documentaÃ§Ã£o dos contratos de API existentes, sem antecipar implementaÃ§Ãµes de inteligÃªncia artificial, mensageria avanÃ§ada ou dashboards analÃ­ticos previstos para aulas posteriores.

## 3. Tarefas e Responsabilidades

* **EvoluÃ§Ã£o do Ficheiro OpenAPI (`openapi.yaml` / `openapi.json`):**
* Atualizar o contrato OpenAPI com tÃ­tulos, descriÃ§Ãµes detalhadas, tags, exemplos de pedido (*requestBody*) e resposta (*responses*).


* Definir o esquema padrÃ£o de erros (`ErrorSchema`) baseado em boas prÃ¡ticas ou na norma RFC 7807 (`problem+json`).




* **PadronizaÃ§Ã£o de ConvenÃ§Ãµes e CabeÃ§alhos:**
* Estandardizar a nomenclatura de rotas, paginaÃ§Ã£o (`page`, `limit`, `nextCursor`), filtros (`?status=`), ordenaÃ§Ã£o (`sort=createdAt:desc`) e status codes (2xx, 4xx, 5xx).


* Mapear os cabeÃ§alhos obrigatÃ³rios da aplicaÃ§Ã£o (`Authorization`, `Idempotency-Key`, `X-Trace-Id`) nos componentes da especificaÃ§Ã£o.




* **ValidaÃ§Ã£o EstÃ¡tica e Linter:**
* Executar a validaÃ§Ã£o estÃ¡tica do ficheiro OpenAPI atravÃ©s de ferramentas de linting (como Spectral ou Redocly CLI) para corrigir eventuais avisos ou inconsistÃªncias.




* **DisponibilizaÃ§Ã£o de DocumentaÃ§Ã£o e Artefactos de Teste:**
* Configurar a disponibilizaÃ§Ã£o interativa da documentaÃ§Ã£o da API (Swagger UI e ReDoc).


* Exportar as coleÃ§Ãµes atualizadas para o Postman ou Insomnia, incluindo *environments* com variÃ¡veis globais (`baseURL`, `token`, etc.) e exemplos operacionais.




* **Versionamento e Checklist do Integrador:**
* Criar a pasta `docs/` para guardar os ficheiros de documentaÃ§Ã£o e registar o histÃ³rico de alteraÃ§Ãµes no ficheiro `CHANGELOG.md`.


* Adicionar a Checklist do Integrador Externo no `README.md` ou na pasta `docs/`, contemplando URLs de ambiente, estratÃ©gias de autenticaÃ§Ã£o, limites de utilizaÃ§Ã£o (*rate limits*) e polÃ­tica de alteraÃ§Ãµes de versÃ£o.


* Atualizar o ficheiro `PROMPTS.md` com os prompts de IA utilizados no refinamento do contrato OpenAPI e na criaÃ§Ã£o de exemplos.





## 4. Requisitos de Entrega (Definition of Done)

* [x] O ficheiro de especificaÃ§Ã£o OpenAPI (`openapi.yaml` ou `openapi.json`) foi atualizado e contempla esquemas completos de resposta e de erro padronizados (`ErrorSchema` / RFC 7807).


* [x] Os endpoints da API estÃ£o estandardizados com suporte documentado para paginaÃ§Ã£o, filtros, ordenaÃ§Ã£o e cabeÃ§alhos obrigatÃ³rios (`Authorization`, `Idempotency-Key`, `X-Trace-Id`).


* [x] A validaÃ§Ã£o estÃ¡tica (linting com Spectral ou Redocly CLI) foi executada e nÃ£o apresenta erros no contrato OpenAPI.


* [x] As interfaces interativas Swagger UI e ReDoc estÃ£o funcionais e acessÃ­veis a partir da aplicaÃ§Ã£o.


* [x] A coleÃ§Ã£o do Postman ou Insomnia foi exportada e disponibilizada com *environments* e exemplos de requisiÃ§Ã£o para cenÃ¡rios de sucesso e erro.


* [x] A documentaÃ§Ã£o do projeto foi versionada na pasta `docs/` e o histÃ³rico de alteraÃ§Ãµes foi atualizado no ficheiro `CHANGELOG.md`.


* [x] A Checklist do Integrador Externo foi incluÃ­da no `README.md` ou na pasta `docs/`, contendo as instruÃ§Ãµes necessÃ¡rias para consumo da API por terceiros.


* [x] O ficheiro `PROMPTS.md` foi atualizado com o histÃ³rico de interaÃ§Ãµes com a IA generativa durante a elaboraÃ§Ã£o do contrato OpenAPI e artefactos de documentaÃ§Ã£o.


* [x] O projeto continua a ser executado perfeitamente via `docker-compose up`, sem introduzir dependÃªncias ou cÃ³digo de etapas futuras fora do escopo da Aula 13.


