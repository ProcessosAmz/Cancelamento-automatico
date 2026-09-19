#!/usr/bin/env python3
"""
Painel de cancelamento automatico (Streamlit).

Fontes de dados:
  1) Consulta publica do Metabase "cancelamento_automatico" - cliente, plano,
     dias suspenso por debito, se cobra multa, se atingiu a regra de 75 dias,
     se o contrato esta assinado (leitura publica, sem autenticacao).
  2) API HubSoft (GraphQL) - contagem de faturas pagas com valor > 0 nos
     ultimos 24 meses por servico (nao existe essa coluna no Metabase).

Fluxo: filtra/seleciona clientes (por plano, regra de 75 dias, contrato
assinado, busca por nome), revisa a previa e, so depois de confirmar
explicitamente, roda o cancelamento - o que abre um atendimento REAL na fila
do SAC do HubSoft (POST /atendimento) pedindo o cancelamento de cada
selecionado. Fica um log de auditoria em saidas/execucao_cancelamento_*.json.

Rodar com: streamlit run app_cancelamento.py
"""
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acoes_cancelamento as ac
import faturas_pagas as fp
import metabase_cancelamento as mb

HERE = os.path.dirname(os.path.abspath(__file__))
JANELA_FATURAS_MESES = 24
CACHE_FATURAS_MAX_IDADE_H = 6

st.set_page_config(page_title="Cancelamento automatico - Suspensos por debito", layout="wide")


@st.cache_data(ttl=900, show_spinner="Baixando dados da consulta publica do Metabase...")
def carregar_metabase():
    servicos = mb.carregar_servicos_suspensos()
    return pd.DataFrame(servicos)


def carregar_faturas_pagas(ids, forcar=False):
    cache = None if forcar else fp.carregar_cache()
    if cache and cache.get("janela_meses") == JANELA_FATURAS_MESES:
        gerado = datetime.strptime(cache["gerado_em"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        idade_h = (datetime.now(timezone.utc) - gerado).total_seconds() / 3600
        if idade_h < CACHE_FATURAS_MAX_IDADE_H:
            return cache["contagem"], cache["gerado_em"]

    barra = st.progress(0.0, text="Contando faturas pagas na API HubSoft (pode levar alguns minutos)...")

    def _cb(done, total):
        barra.progress(min(done / total, 1.0), text=f"Contando faturas pagas... pagina {done}/{total}")

    contagem = fp.calcular(ids, janela_meses=JANELA_FATURAS_MESES, progresso=_cb)
    barra.empty()
    return contagem, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Sidebar / dados
# ---------------------------------------------------------------------------
st.sidebar.title("Cancelamento automatico")
if st.sidebar.button("Recarregar dados do Metabase"):
    carregar_metabase.clear()

df = carregar_metabase()
st.sidebar.caption(f"{len(df)} servicos suspensos por debito (Metabase)")

forcar_faturas = st.sidebar.button(f"Recalcular faturas pagas ({JANELA_FATURAS_MESES}m) - lento")
contagem_faturas, gerado_em = carregar_faturas_pagas(df["id_cliente_servico"].tolist(), forcar=forcar_faturas)
st.sidebar.caption(f"Faturas pagas calculadas em: {gerado_em}")

df["faturas_pagas"] = (
    df["id_cliente_servico"].astype(str).map(contagem_faturas).fillna(0).astype(int)
)

if "selecionados" not in st.session_state:
    st.session_state.selecionados = set()

# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
st.title("Clientes suspensos por debito - selecao para cancelamento")

planos_disponiveis = sorted(df["plano"].unique())
planos_sel = st.multiselect("Planos", planos_disponiveis, default=[])

col1, col2, col3 = st.columns(3)
so_regra = col1.checkbox("Somente quem atingiu 75 dias (regra)", value=True)
so_assinado = col2.checkbox("Somente com contrato assinado", value=False)
busca_nome = col3.text_input("Buscar por nome do cliente")

df_filtrado = df.copy()
if planos_sel:
    df_filtrado = df_filtrado[df_filtrado["plano"].isin(planos_sel)]
if so_regra:
    df_filtrado = df_filtrado[df_filtrado["aplica_regra_75d"]]
if so_assinado:
    df_filtrado = df_filtrado[df_filtrado["contrato_assinado"]]
if busca_nome:
    df_filtrado = df_filtrado[df_filtrado["cliente"].str.contains(busca_nome, case=False, na=False)]

df_filtrado = df_filtrado.reset_index(drop=True)
st.caption(f"{len(df_filtrado)} servicos apos filtro (de {len(df)} suspensos por debito no total)")

# ---------------------------------------------------------------------------
# Tabela de selecao (checkbox por linha, cumulativa entre filtros diferentes)
# ---------------------------------------------------------------------------
ids_visiveis = df_filtrado["id_cliente_servico"].tolist()

bcol1, bcol2, bcol3 = st.columns(3)
if bcol1.button("Selecionar todos os filtrados"):
    st.session_state.selecionados |= set(ids_visiveis)
    st.rerun()
if bcol2.button("Desmarcar filtrados"):
    st.session_state.selecionados -= set(ids_visiveis)
    st.rerun()
if bcol3.button("Limpar toda a selecao"):
    st.session_state.selecionados = set()
    st.rerun()

df_tabela = df_filtrado.copy()
df_tabela.insert(0, "Selecionar", df_tabela["id_cliente_servico"].isin(st.session_state.selecionados))

renomeia = {
    "cliente": "Cliente",
    "cidade": "Cidade",
    "plano": "Servico/Plano",
    "valor_mensal": "Valor mensal (R$)",
    "dias_suspenso": "Dias suspenso por debito",
    "faturas_pagas": f"Faturas pagas ({JANELA_FATURAS_MESES}m)",
    "cobra_multa": "Cobra multa?",
    "contrato_assinado": "Contrato assinado?",
    "aplica_regra_75d": "Aplica a regra (75d)?",
    "faixa_prazo": "Faixa de prazo",
}
df_tabela = df_tabela[["Selecionar"] + list(renomeia.keys())].rename(columns=renomeia)

# key muda quando o conjunto de filtros muda, para o editor sempre nascer
# com o estado de selecao correto (evita ficar preso a uma tabela antiga)
filtro_assinatura = (tuple(sorted(planos_sel)), so_regra, so_assinado, busca_nome)
key_tabela = f"tabela_{hash(filtro_assinatura)}"

editado = st.data_editor(
    df_tabela,
    hide_index=True,
    use_container_width=True,
    disabled=[c for c in df_tabela.columns if c != "Selecionar"],
    column_config={"Valor mensal (R$)": st.column_config.NumberColumn(format="R$ %.2f")},
    key=key_tabela,
)

marcados_na_tela = set(
    id_ for id_, marcado in zip(ids_visiveis, editado["Selecionar"].tolist()) if marcado
)
st.session_state.selecionados = (st.session_state.selecionados - set(ids_visiveis)) | marcados_na_tela

# ---------------------------------------------------------------------------
# Resumo da selecao
# ---------------------------------------------------------------------------
df_sel = df[df["id_cliente_servico"].isin(st.session_state.selecionados)]

st.markdown("---")
st.subheader(f"Selecionados: {len(df_sel)}")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Clientes selecionados", len(df_sel))
m2.metric("MRR total impactado", f"R$ {df_sel['valor_mensal'].sum():,.2f}")
m3.metric("Sem contrato assinado", int((~df_sel["contrato_assinado"]).sum()) if len(df_sel) else 0)
m4.metric("Cobram multa", int(df_sel["cobra_multa"].sum()) if len(df_sel) else 0)

if len(df_sel) and (~df_sel["contrato_assinado"]).any():
    st.warning(
        "Atencao: alguns selecionados NAO tem contrato assinado - revise antes de "
        "confirmar (a multa pode nao ter base contratual)."
    )
    st.dataframe(
        df_sel[~df_sel["contrato_assinado"]][["cliente", "plano", "valor_mensal"]],
        hide_index=True,
    )

# ---------------------------------------------------------------------------
# Execucao (acao real)
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Executar cancelamento (abre atendimento REAL no SAC do HubSoft)")

if len(df_sel) == 0:
    st.info("Selecione pelo menos um cliente na tabela acima.")
else:
    with st.expander(f"Pre-visualizar os {len(df_sel)} atendimentos que serao abertos"):
        for _, row in df_sel.iterrows():
            st.markdown(f"**{row['cliente']}** ({row['plano']}) - {ac.montar_descricao(row)}")

    confirmado = st.checkbox(
        f"Confirmo que revisei a lista acima e quero abrir {len(df_sel)} atendimentos "
        "REAIS de cancelamento no HubSoft agora (essa acao nao pode ser desfeita por aqui)."
    )
    if st.button("Rodar cancelamento agora", type="primary", disabled=not confirmado):
        barra = st.progress(0.0)
        status_area = st.empty()
        linhas = df_sel.to_dict("records")

        def _cb(done, total):
            status_area.text(f"Abrindo atendimento {done}/{total}: {linhas[done-1]['cliente']}")
            barra.progress(done / total)

        resultados, log_path = ac.executar_lote(
            linhas, executado_por="anaketllen@amazonett.com.br", callback_progresso=_cb
        )

        ok = sum(1 for r in resultados if r["ok"])
        st.success(f"Concluido: {ok}/{len(resultados)} atendimentos abertos com sucesso.")
        st.caption(f"Log de auditoria: {log_path}")
        st.dataframe(
            pd.DataFrame(resultados)[["cliente", "plano", "ok", "http_status", "erro"]],
            hide_index=True,
        )
        st.session_state.selecionados = set()
