# Atalhos operacionais do SynapseShop para PowerShell 5.1+.
# Uso: .\tasks.ps1 <tarefa>   (sem argumento lista as tarefas)
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "build", "test", "openapi", "check", "smoke", "mensageria", "logs", "reset")]
    [string]$Tarefa = "help"
)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

function Executar {
    param([scriptblock]$Bloco)
    & $Bloco
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Push-Location -LiteralPath $Raiz
try {
    switch ($Tarefa) {
        "up" {
            Executar { docker compose up -d --build }
            Write-Host "Servicos no ar. Health: http://localhost:8000/health"
        }
        "down" {
            Executar { docker compose down }
        }
        "build" {
            Executar { docker compose build }
        }
        "test" {
            Executar { & $Python -m pytest -q }
        }
        "openapi" {
            Executar { & $Python "scripts\validar_openapi.py" }
        }
        "check" {
            Executar { & $Python -m pytest -q }
            Executar { & $Python "scripts\validar_openapi.py" }
            Executar { & $Python manage.py check }
        }
        "smoke" {
            Executar { & $Python "scripts\smoke_test_fluxo.py" }
        }
        "mensageria" {
            Executar { & $Python "scripts\smoke_test_mensageria.py" }
        }
        "logs" {
            & docker compose logs -f api pedido-worker notificacao-worker
        }
        "reset" {
            Write-Host "Isto remove containers E volumes (Postgres, Redis, Kafka e RabbitMQ)."
            $resposta = Read-Host "Digite 'sim' para continuar"
            if ($resposta -eq "sim") {
                Executar { docker compose down -v }
            } else {
                Write-Host "Cancelado."
            }
        }
        default {
            @(
                "Tarefas disponiveis:",
                "  up          sobe e constroi todos os servicos",
                "  down        derruba os containers (preserva volumes)",
                "  build       reconstroi as imagens sem subir",
                "  test        roda a suite completa com cobertura",
                "  openapi     valida o contrato contra as rotas",
                "  check       test + openapi + manage.py check",
                "  smoke       fluxo ponta a ponta pedido -> notificacao",
                "  mensageria  reentrega, DLQ e reprocessamento",
                "  logs        acompanha os logs da API e dos workers",
                "  reset       derruba tudo e apaga os volumes"
            ) | Write-Host
        }
    }
}
finally {
    Pop-Location
}
