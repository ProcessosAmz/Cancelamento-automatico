#!/usr/bin/env python3
"""
Agendador do cancelamento automatico: fica ligado, confere a cada minuto o
agendamentos.json (editado no painel "Agendamento" da tela) e, no horario
marcado, roda o lote da empresa com os planos escolhidos.

Rodar (deixar a janela aberta):   python agendador.py
Uma checagem so (pra cron / Agendador de Tarefas do Windows):
                                  python agendador.py --uma-vez

Cada execucao grava o log em saidas/ (execucao_real_* ou simulacao_*) e a
ultima execucao de cada empresa em saidas/agendador_estado.json, que a tela
mostra.
"""
import argparse
import sys
import time
import traceback

import agendamento as ag
import empresas
import execucao_lote
import metabase_cancelamento as mb

EXECUTADO_POR = "anaketllen@amazonett.com.br"
INTERVALO_SEGUNDOS = 60


def log(msg):
    print(f"{ag.agora():%d/%m %H:%M:%S} {msg}", flush=True)


def selecionar_linhas(empresa, cfg_empresa):
    """Linhas do Metabase dos planos escolhidos, ate o limite de clientes."""
    planos = set(cfg_empresa["planos"])
    linhas = [r for r in mb.baixar_linhas_metabase(empresa) if r.get("plano") in planos]
    limite = int(cfg_empresa.get("limite_clientes") or 0)
    return linhas[:limite] if limite > 0 else linhas


def executar_empresa(empresa, cfg_empresa, estado):
    momento = ag.agora()
    registro = {"data": momento.date().isoformat(), "iniciado": momento.isoformat(),
                "modo": cfg_empresa["modo"], "planos": cfg_empresa["planos"], "status": "rodando"}
    estado["empresas"][empresa] = registro
    ag.salvar_estado(estado)
    try:
        linhas = selecionar_linhas(empresa, cfg_empresa)
        log(f"{empresa}: {len(linhas)} cliente(s) nos planos {cfg_empresa['planos']} - modo {cfg_empresa['modo']}")
        res = execucao_lote.rodar_lote(
            empresa, linhas, EXECUTADO_POR, modo=cfg_empresa["modo"], aviso=log,
        )
        registro.update(status="interrompido" if res["interrompido"] else "concluido", **res)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - registra e segue (load_keys usa sys.exit)
        registro.update(status="erro", erro=f"{e}", traceback=traceback.format_exc())
        log(f"{empresa}: ERRO {e}")
    registro["terminado"] = ag.agora().isoformat()
    estado["empresas"][empresa] = registro
    ag.salvar_estado(estado)
    log(f"{empresa}: {registro['status']} - {registro.get('contagem')}")


def checar_uma_vez():
    cfg = ag.carregar_config()
    estado = ag.carregar_estado()
    estado["batimento"] = ag.agora().isoformat()
    ag.salvar_estado(estado)
    for empresa in empresas.EMPRESAS:
        ultima = (estado["empresas"].get(empresa) or {}).get("data")
        if ag.deve_rodar(cfg[empresa], ultima, ag.agora()):
            executar_empresa(empresa, cfg[empresa], estado)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uma-vez", action="store_true", help="faz uma checagem e sai")
    args = p.parse_args()
    if args.uma_vez:
        checar_uma_vez()
        return
    log("agendador ligado - conferindo agendamentos.json a cada minuto (Ctrl+C pra parar)")
    while True:
        try:
            checar_uma_vez()
        except Exception as e:  # noqa: BLE001 - nao derruba o agendador
            log(f"erro na checagem: {e}")
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    sys.exit(main())
