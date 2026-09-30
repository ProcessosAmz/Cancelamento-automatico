#!/usr/bin/env python3
"""
Painel "Agendamento" da tela (Streamlit): configura, por empresa, o horario,
os dias e os planos que o agendador.py roda sozinho, e mostra a ultima
execucao. A configuracao fica em agendamentos.json (ver agendamento.py).
"""
from datetime import datetime, time as dtime

import pandas as pd
import streamlit as st

import agendamento as ag


def _agendador_ligado(estado):
    bat = estado.get("batimento")
    if not bat:
        return False, None
    visto = datetime.fromisoformat(bat)
    # a tarefa do Windows checa a cada 5 min - 10 min sem sinal = desligado
    return (ag.agora() - visto).total_seconds() < 600, visto


def render(empresa, nome, planos_disponiveis):
    st.title(f"{nome} - agendamento automatico")

    estado = ag.carregar_estado()
    ligado, visto = _agendador_ligado(estado)
    if ligado:
        st.success(f"Agendador LIGADO (ultimo sinal {visto:%d/%m %H:%M:%S}).")
    else:
        st.error(
            "Agendador DESLIGADO"
            + (f" (ultimo sinal {visto:%d/%m %H:%M})" if visto else "")
            + " - sem ele nada roda no horario. Instale a tarefa do Windows (uma vez so): "
            "`powershell -ExecutionPolicy Bypass -File .\\instalar_tarefa_agendador.ps1` "
            "- ou deixe um terminal aberto com `python agendador.py`."
        )

    cfg_todas = ag.carregar_config()
    cfg = cfg_todas[empresa]

    st.subheader("Configuracao")
    ativo = st.toggle("Agendamento ativo", value=cfg["ativo"], key=f"ag_ativo_{empresa}")
    c1, c2 = st.columns(2)
    hh, mm = (int(x) for x in cfg["horario"].split(":"))
    horario = c1.time_input("Horario (Manaus)", value=dtime(hh, mm), step=300, key=f"ag_hora_{empresa}")
    dias = c2.multiselect(
        "Dias da semana",
        options=list(range(7)),
        default=cfg["dias_semana"],
        format_func=lambda d: ag.DIAS[d],
        key=f"ag_dias_{empresa}",
    )
    faltando = [p for p in cfg["planos"] if p not in planos_disponiveis]
    planos = st.multiselect(
        "Planos que vao rodar",
        options=sorted(set(planos_disponiveis) | set(cfg["planos"])),
        default=cfg["planos"],
        key=f"ag_planos_{empresa}",
    )
    if faltando:
        st.caption(f"Sem clientes hoje na consulta (continuam salvos): {', '.join(faltando)}")

    c3, c4 = st.columns(2)
    modo = c3.radio(
        "Modo",
        ["simulacao", "real"],
        index=0 if cfg["modo"] == "simulacao" else 1,
        format_func=lambda m: "Simulacao (so calcula, nada no HubSoft)" if m == "simulacao" else "REAL (cancela de verdade)",
        key=f"ag_modo_{empresa}",
    )
    limite = c4.number_input(
        "Maximo de clientes por execucao (0 = todos)",
        min_value=0, value=int(cfg["limite_clientes"]), step=1, key=f"ag_limite_{empresa}",
    )

    confirmar = True
    if modo == "real":
        st.error(
            "Modo REAL: no horario, o agendador cancela DE VERDADE os clientes desses planos "
            f"({'todos' if not limite else f'ate {limite}'} por execucao), sem aprovacao entre blocos. "
            "Voce so revisa depois, pela ultima execucao abaixo e pelo log."
        )
        confirmar = st.checkbox(
            "Confirmo que o agendador pode executar o cancelamento REAL sozinho.",
            value=cfg["modo"] == "real",
            key=f"ag_confirma_{empresa}",
        )

    if st.button("Salvar agendamento", type="primary", disabled=not confirmar, key=f"ag_salvar_{empresa}"):
        cfg_todas[empresa] = {
            "ativo": ativo,
            "horario": horario.strftime("%H:%M"),
            "dias_semana": sorted(dias),
            "planos": planos,
            "modo": modo,
            "limite_clientes": int(limite),
        }
        ag.salvar_config(cfg_todas)
        st.success("Agendamento salvo.")
        cfg = cfg_todas[empresa]

    prox = ag.proxima_execucao(cfg, ag.agora())
    if prox:
        st.info(
            f"Proxima execucao: **{ag.DIAS[prox.weekday()]} {prox:%d/%m as %H:%M}** - "
            f"{len(cfg['planos'])} plano(s), modo **{cfg['modo'].upper()}**, "
            f"{'todos os clientes' if not cfg['limite_clientes'] else 'ate ' + str(cfg['limite_clientes']) + ' clientes'}."
        )
    else:
        st.info("Nenhuma execucao agendada (desligado, sem planos ou sem dias marcados).")

    st.markdown("---")
    st.subheader("Ultima execucao automatica")
    ult = estado.get("empresas", {}).get(empresa)
    if not ult:
        st.caption("Ainda nao rodou nenhuma vez.")
        return
    cor = {"concluido": st.success, "rodando": st.info, "interrompido": st.error, "erro": st.error}.get(ult["status"], st.info)
    cor(
        f"{ult['status'].upper()} - {ult.get('iniciado', '')[:16].replace('T', ' ')} - modo {ult.get('modo')} - "
        f"planos: {', '.join(ult.get('planos') or [])}"
    )
    if ult.get("contagem"):
        st.markdown(" | ".join(f"**{k}:** {v}" for k, v in ult["contagem"].items()))
    if ult.get("interrompido"):
        st.error(ult["interrompido"])
    if ult.get("erro"):
        st.error(f"Erro: {ult['erro']}")
    if ult.get("atencao"):
        st.warning(f"**Precisa de atencao: {len(ult['atencao'])} cliente(s)**")
        st.dataframe(pd.DataFrame(ult["atencao"]), hide_index=True, use_container_width=True)
    if ult.get("log"):
        st.caption(f"Log completo: {ult['log']}")
