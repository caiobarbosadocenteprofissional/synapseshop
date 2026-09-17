# Checklist "IA-Safe" — Revisão de Código Gerado por IA

> Guia obrigatório para revisar qualquer código sugerido por assistentes virtuais antes de
> integrá-lo ao **SynapseShop**. Aplicável a partir da Aula 4 (Django REST Framework).
> Vincule cada revisão às entradas correspondentes no `PROMPTS.md`.

## 1. Escopo (SpecDD / anti-antecipação)
- [ ] O código se limita ao que está no DoD da spec da aula atual.
- [ ] Nenhuma biblioteca fora do escopo foi importada (ex.: JWT, Redis, FastAPI, mensageria).
- [ ] Nenhum *placeholder* ou configuração de infraestrutura de aulas futuras foi incluído.

## 2. Imports e dependências
- [ ] Todos os imports são utilizados (sem imports mortos).
- [ ] As dependências adicionadas estão fixadas no `requirements.txt`.
- [ ] Nenhum pacote foi instalado sem constar em `requirements.txt`.

## 3. Modelagem e tipos
- [ ] Valores monetários usam `DecimalField` (`max_digits`/`decimal_places`), nunca `FloatField`.
- [ ] Campos obrigatórios/opcionais (`blank`, `null`, `default`) fazem sentido no domínio.
- [ ] Relacionamentos têm `on_delete` e `related_name` explícitos.
- [ ] `makemigrations` foi executado e a migração foi revisada antes de aplicar.

## 4. Serialização e validação
- [ ] Campos sensíveis/somente-leitura estão em `read_only_fields`.
- [ ] Validações de payload retornam erro de campo (HTTP 400), sem `raise` genérico.
- [ ] Campos calculados (ex.: `category_name`) não são graváveis.

## 5. Views, rotas e HTTP
- [ ] Rotas expostas sob o prefixo versionado `/api/v1/`.
- [ ] Os status codes seguem o padrão: 200 OK, 201 Created, 204 No Content, 400 Bad Request, 404 Not Found.
- [ ] `DELETE` responde 204; recurso inexistente responde 404; payload inválido responde 400.

## 6. Segurança e configuração
- [ ] Nenhum segredo/credencial *hardcoded* no repositório (uso de variáveis de ambiente com defaults de dev).
- [ ] `DEBUG` e `ALLOWED_HOSTS` são adequados ao ambiente de desenvolvimento.
- [ ] Sem exposição de dados internos em respostas de erro.

## 7. Verificação antes do merge
- [ ] `python manage.py check` sem erros.
- [ ] Fluxo CRUD testado manualmente (Postman/curl) com os status esperados.
- [ ] O prompt usado e as intervenções manuais foram registrados no `PROMPTS.md`.
