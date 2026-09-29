from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        # Aula 8: registra os handlers de invalidacao de cache por evento de
        # dominio em todos os processos da API.
        from services import cache_invalidation  # noqa: F401
