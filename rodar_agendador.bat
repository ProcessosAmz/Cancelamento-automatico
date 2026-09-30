@echo off
REM Uma checagem do agendador do cancelamento automatico (chamado pelo
REM Agendador de Tarefas do Windows a cada 5 minutos - ver
REM instalar_tarefa_agendador.ps1). Se for o horario marcado no painel
REM "Agendamento", roda o lote; senao so registra que esta vivo e sai.
REM Saida gravada em saidas\agendador.log.
cd /d "%~dp0"
if not exist saidas mkdir saidas
set PYTHONIOENCODING=utf-8
"%~dp0venv\Scripts\python.exe" "%~dp0agendador.py" --uma-vez >> "%~dp0saidas\agendador.log" 2>&1
