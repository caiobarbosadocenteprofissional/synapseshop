"""Erros de domínio do Texto-para-SQL (Aula 21)."""


class TextoSqlErro(Exception):
    """Erro tratável pelo endpoint, com status HTTP sugerido."""

    status_http = 400


class SqlInseguro(TextoSqlErro):
    """A instrução gerada viola a política de leitura/allow-list."""

    status_http = 400


class SqlInvalido(TextoSqlErro):
    """A instrução é de leitura, mas não pôde ser executada pelo banco."""

    status_http = 422
