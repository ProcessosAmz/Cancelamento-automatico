# Registra no Agendador de Tarefas do Windows a tarefa que roda o agendador
# do cancelamento automatico a cada 5 minutos (rodar_agendador.bat).
#
# Instalar:  powershell -ExecutionPolicy Bypass -File .\instalar_tarefa_agendador.ps1
# Remover:   powershell -ExecutionPolicy Bypass -File .\instalar_tarefa_agendador.ps1 -Remover
#
# A tarefa roda com o seu usuario e so enquanto voce estiver logada no
# Windows (o computador precisa estar ligado e com sua sessao aberta, pode
# estar bloqueado). Se uma execucao ainda estiver rodando (lote grande), a
# proxima checagem e ignorada ate ela terminar.
param([switch]$Remover)

$nome = "Cancelamento automatico - agendador"
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $pasta "rodar_agendador.bat"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false
    Write-Output "Tarefa '$nome' removida."
    return
}

if (-not (Test-Path $bat)) { throw "Nao encontrei $bat" }
if (-not (Test-Path (Join-Path $pasta "venv\Scripts\python.exe"))) { throw "Nao encontrei o venv em $pasta\venv" }

$acao = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $pasta
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$config = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8)

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Confere a cada 5 min o agendamentos.json (painel Agendamento) e roda o lote no horario marcado. Log: saidas\agendador.log" `
    -Force | Out-Null

Write-Output "Tarefa '$nome' registrada: roda $bat a cada 5 minutos."
Write-Output "Log: $pasta\saidas\agendador.log"
