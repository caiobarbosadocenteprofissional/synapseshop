"""Comando idempotente que cria os usuários demo (admin e user) do Aula 7.

Executado no start do container (após `migrate`) para que a coleção do
Postman funcione com os cenários de login sucesso/erro/acesso negado. As
credenciais podem ser sobrescritas via variáveis de ambiente SEED_*.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


def _env_or(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Command(BaseCommand):
    help = "Cria os usuários demo (admin e user) de forma idempotente."

    def handle(self, *args, **options):
        specs = [
            {
                "role": User.Roles.ADMIN,
                "username": _env_or("SEED_ADMIN_USERNAME", "admin"),
                "password": _env_or("SEED_ADMIN_PASSWORD", "admin"),
                "email": _env_or("SEED_ADMIN_EMAIL", "admin@synapseshop.local"),
            },
            {
                "role": User.Roles.USER,
                "username": _env_or("SEED_USER_USERNAME", "user"),
                "password": _env_or("SEED_USER_PASSWORD", "user"),
                "email": _env_or("SEED_USER_EMAIL", "user@synapseshop.local"),
            },
        ]

        created = []
        for spec in specs:
            user, was_created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "email": spec["email"],
                    "role": spec["role"],
                    "is_staff": spec["role"] == User.Roles.ADMIN,
                    "is_superuser": spec["role"] == User.Roles.ADMIN,
                },
            )
            if was_created:
                user.set_password(spec["password"])
                user.save(update_fields=["password"])
                created.append(spec["username"])

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Usuários demo criados: %s." % ", ".join(sorted(created))
                )
            )
        else:
            self.stdout.write(self.style.WARNING("Usuários demo já existiam."))