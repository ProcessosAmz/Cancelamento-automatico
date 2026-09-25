#!/usr/bin/env python3
"""
Tela simples (Streamlit) para validar os clientes trazidos pela consulta
publica do Metabase "cancelamento_automatico" - sem nenhuma acao de
cancelamento, apenas visualizacao/conferencia dos dados.

Le direto o export JSON da consulta (uma linha por id_cliente_servico, sem
agregacao), entao acompanha qualquer coluna que o Metabase estiver expondo.

Rodar com: streamlit run app_validacao.py
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acoes_cancelamento as acr
import automacao_cancelamento as ac
import hubsoft as h
import metabase_cancelamento as mb

st.set_page_config(page_title="Validacao de clientes - Metabase", layout="wide")


@st.cache_data(ttl=900, show_spinner="Baixando dados da consulta publica do Metabase...")
def carregar_metabase():
    linhas = mb.baixar_linhas_metabase()
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("Validacao de clientes")
if st.sidebar.button("Recarregar dados do Metabase"):
    carregar_metabase.clear()

df = carregar_metabase()
df["valor_fatura_proporcional"] = df.apply(ac.valor_fatura_proporcional_bruto, axis=1)
df["gera_fatura_proporcional"] = df["ids_faturas_deletar"].apply(lambda x: bool(ac.parse_ids_fatura(x)))
st.sidebar.caption(f"{len(df)} clientes/servicos retornados pela consulta")

# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
st.title("Consulta do Metabase - validacao de clientes")

col1, col2, col3 = st.columns(3)
busca_nome = col1.text_input("Buscar por nome do cliente")
planos_sel = col2.multiselect("Planos", sorted(df["plano"].dropna().unique()))
cidades_sel = col3.multiselect("Cidades", sorted(df["cidade"].dropna().unique()))

col4, col5, col6 = st.columns(3)
estados_sel = col4.multiselect("Estados", sorted(df["estado"].dropna().unique()))
so_assinado = col5.checkbox("Somente com contrato assinado")
so_elegivel_multa = col6.checkbox("Somente elegiveis a multa")

df_filtrado = df.copy()
if busca_nome:
    df_filtrado = df_filtrado[df_filtrado["cliente"].str.contains(busca_nome, case=False, na=False)]
if planos_sel:
    df_filtrado = df_filtrado[df_filtrado["plano"].isin(planos_sel)]
if cidades_sel:
    df_filtrado = df_filtrado[df_filtrado["cidade"].isin(cidades_sel)]
if estados_sel:
    df_filtrado = df_filtrado[df_filtrado["estado"].isin(estados_sel)]
if so_assinado:
    df_filtrado = df_filtrado[df_filtrado["classificacao_contrato"] == "CONTRATO ASSINADO"]
if so_elegivel_multa:
    df_filtrado = df_filtrado[df_filtrado["elegivel_multa"] == True]  # noqa: E712

df_filtrado = df_filtrado.reset_index(drop=True)
st.caption(f"{len(df_filtrado)} de {len(df)} clientes apos filtro")

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Clientes no filtro", len(df_filtrado))
m2.metric("MRR (R$)", f"{df_filtrado['valor_mensal'].sum():,.2f}")
m3.metric(
    "Sem contrato assinado",
    int((df_filtrado["classificacao_contrato"] != "CONTRATO ASSINADO").sum()) if len(df_filtrado) else 0,
)
m4.metric("Elegiveis a multa", int(df_filtrado["elegivel_multa"].sum()) if len(df_filtrado) else 0)

# ---------------------------------------------------------------------------
# Resumo por plano (75+ dias suspenso por debito)
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Clientes que atingiram 75 dias de suspensao por debito, por plano")
st.caption(
    "A consulta do Metabase ja vem filtrada apenas com quem atingiu 75+ dias suspenso "
    "por debito, entao esta contagem e sobre o total de cada plano nessa condicao "
    "(considera o filtro de nome/cidade/UF/contrato/multa acima, se algum estiver ativo)."
)
resumo_plano = (
    df_filtrado.groupby("plano")
    .agg(
        qtd_clientes=("id_cliente_servico", "count"),
        mrr_impactado=("valor_mensal", "sum"),
        elegiveis_multa=("elegivel_multa", "sum"),
        multa_estimada_total=("valor_multa_estimado", "sum"),
    )
    .sort_values("qtd_clientes", ascending=False)
    .reset_index()
    .rename(
        columns={
            "plano": "Plano",
            "qtd_clientes": "Qtd clientes (75+ dias)",
            "mrr_impactado": "MRR impactado (R$)",
            "elegiveis_multa": "Elegiveis a multa",
            "multa_estimada_total": "Multa estimada total (R$)",
        }
    )
)
st.dataframe(
    resumo_plano,
    hide_index=True,
    use_container_width=True,
    column_config={
        "MRR impactado (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Multa estimada total (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
    },
)

# ---------------------------------------------------------------------------
# Automacao de cancelamento (por plano) - MODO SIMULACAO
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Automacao de cancelamento por plano (simulacao)")
st.warning(
    "MODO SIMULACAO: o botao abaixo so calcula e mostra o que seria feito, "
    "cliente por cliente (faturas a apagar, fatura proporcional, multa, "
    "atendimento + O.S. de retirada, desautorizacao de CPE). Nenhuma chamada "
    "real e feita na API do HubSoft ainda - faltam confirmar os campos "
    "exatos de alguns endpoints (ver automacao_cancelamento.py)."
)

planos_da_tabela = resumo_plano["Plano"].tolist()
df_automacao = df_filtrado.iloc[0:0]
if not planos_da_tabela:
    st.info("Nenhum plano disponivel com os filtros atuais.")
else:
    plano_automacao = st.selectbox(
        "Escolha o plano (lista dinamica, mesma da tabela acima)",
        planos_da_tabela,
        key="plano_automacao",
    )
    # dinamico: recalcula toda vez que o filtro em cima ou o plano escolhido mudam
    df_automacao = df_filtrado[df_filtrado["plano"] == plano_automacao].reset_index(drop=True)
    st.info(f"{len(df_automacao)} cliente(s) do plano '{plano_automacao}' entrarao na simulacao.")

    if st.button(f"Rodar automacao (simulacao) - {len(df_automacao)} cliente(s)", type="primary"):
        linhas = df_automacao.to_dict("records")
        total = len(linhas)
        progresso = st.progress(0.0)
        log_area = st.container()

        def _mostra_passo(i, total, plano_execucao):
            acoes = plano_execucao["acoes"]
            elegivel = plano_execucao.get("elegivel_automacao", True)
            titulo = (
                f"[{i}/{total}] {'[INELEGIVEL] ' if not elegivel else ''}{plano_execucao['cliente']} - "
                f"{plano_execucao['plano']} (servico {plano_execucao['id_cliente_servico']})"
            )
            with log_area.status(titulo, state="error" if not elegivel else "complete", expanded=True):
                if not elegivel:
                    st.error(
                        f"Cliente NAO entraria na automacao real: {plano_execucao.get('motivo_inelegivel')}"
                    )
                st.markdown(
                    f"**1. Apagar faturas vencidas:** {acoes['apagar_faturas_vencidas']['qtd']} "
                    f"fatura(s) - IDs: {acoes['apagar_faturas_vencidas']['ids_fatura']}"
                )
                fp = acoes["gerar_fatura_proporcional"]
                if fp["aplica"]:
                    st.markdown(f"**2. Gerar fatura proporcional:** R$ {fp['valor']:,.2f} ({fp['motivo']})")
                else:
                    st.markdown(f"**2. Gerar fatura proporcional:** nao aplica ({fp['motivo']})")
                multa = acoes["cobrar_multa_rescisao"]
                if multa["aplica"]:
                    st.markdown(f"**3. Cobrar multa de rescisao:** R$ {multa['valor']:,.2f} ({multa['percentual']}%)")
                else:
                    st.markdown("**3. Cobrar multa de rescisao:** nao aplica (sem fidelidade vigente)")
                at = acoes["abrir_atendimento_retirada"]
                st.markdown(f"**4. Abrir atendimento:** tipo `{at['tipo_atendimento']}` - \"{at['descricao_abertura']}\"")
                os_ = acoes["abrir_os_retirada"]
                st.markdown(
                    f"**5. Abrir O.S. de retirada:** tipo `{os_['tipo_os']}`, tecnico/usuario responsavel "
                    f"`{os_['tecnico_responsavel']}`"
                )
                st.markdown("**6. Desautorizar CPE:** sim")
            progresso.progress(i / total)

        planos_execucao = ac.simular_lote(linhas, callback_progresso=_mostra_passo)
        resumo_execucao = ac.resume_lote(planos_execucao)
        caminho_log = ac.salvar_simulacao(
            planos_execucao, resumo_execucao, gerado_por="anaketllen@amazonett.com.br"
        )

        st.success(f"Simulacao concluida para {resumo_execucao['qtd_clientes']} clientes. Log: {caminho_log}")
        if resumo_execucao["qtd_inelegiveis"] > 0:
            st.error(
                f"{resumo_execucao['qtd_inelegiveis']} cliente(s) NAO entrariam na automacao real "
                "(ver detalhe marcado como [INELEGIVEL] em cada card acima)."
            )

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Atendimentos a abrir", resumo_execucao["qtd_atendimentos_a_abrir"])
        s2.metric("O.S. de retirada a abrir", resumo_execucao["qtd_os_a_abrir"])
        s3.metric("Faturas a apagar", resumo_execucao["qtd_faturas_a_apagar"])
        s4.metric("CPEs a desautorizar", resumo_execucao["qtd_cpe_a_desautorizar"])

        s5, s6, s7 = st.columns(3)
        s5.metric("Faturas proporcionais a gerar", resumo_execucao["qtd_faturas_proporcionais_a_gerar"])
        s6.metric("Valor faturas proporcionais (R$)", f"{resumo_execucao['valor_faturas_proporcionais']:,.2f}")
        s7.metric(
            "Multa total (R$)",
            f"{resumo_execucao['valor_multa_total']:,.2f} ({resumo_execucao['qtd_com_multa']} clientes)",
        )

    # -----------------------------------------------------------------------
    # Execucao REAL (cliente por cliente, com confirmacao)
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Execucao REAL do cancelamento (cliente por cliente)")
    st.error(
        "ATENCAO: isso executa o cancelamento DE VERDADE - cancela faturas, gera "
        "cobranca/multa, abre atendimento e O.S. reais, desautoriza CPE. Acao real "
        "e irreversivel por este programa. Processa 1 cliente por vez e espera sua "
        "confirmacao (revisar o resultado) antes de seguir pro proximo."
    )

    if "exec_real_fila" not in st.session_state:
        st.session_state.exec_real_fila = None
        st.session_state.exec_real_indice = 0

    confirmar_real = st.checkbox(
        f"Confirmo que quero executar o cancelamento REAL para os {len(df_automacao)} "
        f"cliente(s) do plano '{plano_automacao}', um por um, revisando cada resultado "
        "antes de seguir.",
        key="confirmar_real",
    )
    if st.button(
        "Rodar automacao REAL",
        type="primary",
        disabled=not confirmar_real or len(df_automacao) == 0,
    ):
        st.session_state.exec_real_fila = df_automacao.to_dict("records")
        st.session_state.exec_real_indice = 0

    if st.session_state.exec_real_fila is not None:
        fila = st.session_state.exec_real_fila
        idx = st.session_state.exec_real_indice

        if idx >= len(fila):
            st.success(f"Fila concluida - {len(fila)} cliente(s) processado(s).")
            if st.button("Fechar execucao real"):
                st.session_state.exec_real_fila = None
                st.session_state.exec_real_indice = 0
                st.rerun()
        else:
            row = fila[idx]
            plano_atual = ac.montar_plano(row)
            st.markdown(
                f"### Cliente {idx + 1}/{len(fila)}: {row['cliente']} "
                f"(servico {row['id_cliente_servico']})"
            )

            if not plano_atual["elegivel_automacao"]:
                st.warning(f"Pulando - inelegivel: {plano_atual['motivo_inelegivel']}")
                if st.button("Continuar (pular este cliente)", key=f"pular_{idx}"):
                    st.session_state.exec_real_indice += 1
                    st.rerun()
            else:
                resultado_key = f"resultado_real_{row['id_cliente_servico']}_{idx}"
                if resultado_key not in st.session_state:
                    keys = h.load_keys()
                    data_venc = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
                    ids_fatura = plano_atual["acoes"]["apagar_faturas_vencidas"]["ids_fatura"]
                    gerar_multa = plano_atual["acoes"]["cobrar_multa_rescisao"]["aplica"]
                    descricao_atendimento = plano_atual["acoes"]["abrir_atendimento_retirada"]["descricao_abertura"]
                    with st.spinner(f"Executando cancelamento real de {row['cliente']}..."):
                        status, resp, corpo = acr.cancelar_servico_completo(
                            keys,
                            id_cliente_servico=row["id_cliente_servico"],
                            id_empresa=plano_atual["id_empresa"],
                            nome_contato=row["cliente"],
                            telefone_contato=row.get("telefone_cliente") or "",
                            email_contato=row.get("email_cliente") or "",
                            ids_fatura_cancelar=ids_fatura,
                            data_vencimento=data_venc,
                            descricao_abertura_atendimento=descricao_atendimento,
                            gerar_multa=gerar_multa,
                        )
                    st.session_state[resultado_key] = (status, resp, corpo)

                status, resp, corpo = st.session_state[resultado_key]
                sucesso = isinstance(resp, dict) and resp.get("status") == "success"

                st.write(f"**HTTP {status}**")
                if sucesso:
                    st.success(resp.get("msg", "Sucesso"))
                    protocolo = resp.get("protocolo_cancelamento") or {}
                    ids_fatura_enviadas = [f["id_fatura"] for f in corpo["faturas"]]
                    st.markdown(
                        f"- **Protocolo de cancelamento:** {protocolo.get('id_protocolo_cancelamento')}\n"
                        f"- **Faturas informadas para cancelar:** {ids_fatura_enviadas}\n"
                        f"- **Multa gerada:** R$ {protocolo.get('valor_multa', '0')}\n"
                    )
                else:
                    st.error("A chamada NAO teve sucesso - revise antes de continuar.")

                with st.expander("JSON enviado (corpo da requisicao)"):
                    st.json(corpo)
                with st.expander("JSON recebido (resposta da API)", expanded=True):
                    st.json(resp)

                if st.button("OK, revisei - rodar o proximo cliente", type="primary", key=f"ok_{idx}"):
                    st.session_state.exec_real_indice += 1
                    st.rerun()

# ---------------------------------------------------------------------------
# Tabela (mesmo plano escolhido na automacao acima)
# ---------------------------------------------------------------------------
st.markdown("---")
if planos_da_tabela:
    st.subheader(f"Clientes do plano selecionado: {plano_automacao}")
else:
    st.subheader("Clientes")
renomeia = {
    "cliente": "Cliente",
    "id_cliente_servico": "ID servico",
    "tipo_pessoa": "Tipo pessoa",
    "cidade": "Cidade",
    "estado": "UF",
    "plano": "Servico/Plano",
    "valor_mensal": "Valor mensal (R$)",
    "classificacao_contrato": "Contrato",
    "data_contrato_assinado": "Data contrato assinado",
    "data_ultima_suspensao": "Ultima suspensao",
    "mes_cancelamento": "Mes cancelamento",
    "qtd_faturas_vencidas_abertas": "Faturas vencidas/abertas",
    "qtd_faturas_total": "Faturas total",
    "qtd_faturas_pagas": "Faturas pagas",
    "valor_total_vencido_aberto": "Valor vencido/aberto (R$)",
    "valor_total_pago": "Valor total pago (R$)",
    "elegivel_multa": "Elegivel a multa?",
    "percentual_multa": "% multa",
    "valor_multa_estimado": "Multa estimada (R$)",
    "valor_fatura_proporcional": "Fatura proporcional (plano/30*37) (R$)",
    "gera_fatura_proporcional": "Gera fatura proporcional? (substitui as vencidas apagadas)",
}
colunas_existentes = [c for c in renomeia if c in df_automacao.columns]
df_tabela = df_automacao[colunas_existentes].rename(columns=renomeia)

st.dataframe(
    df_tabela,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Valor mensal (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Valor vencido/aberto (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Valor total pago (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Multa estimada (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Fatura proporcional (plano/30*37) (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
    },
)

# ---------------------------------------------------------------------------
# Detalhe por cliente
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Detalhe de um cliente")

if len(df_automacao) == 0:
    st.info("Nenhum cliente no plano selecionado.")
else:
    opcoes = df_automacao["id_cliente_servico"].tolist()
    rotulos = {
        idcs: f"{row['cliente']} - {row['plano']} (servico {idcs})"
        for idcs, row in zip(opcoes, df_automacao.to_dict("records"))
    }
    escolhido = st.selectbox("Cliente/servico", opcoes, format_func=lambda idcs: rotulos[idcs])
    linha = df_automacao[df_automacao["id_cliente_servico"] == escolhido].iloc[0]

    detalhe = linha.drop(labels=["ids_faturas_deletar"], errors="ignore")
    st.table(detalhe.rename("Valor").to_frame())

    if "ids_faturas_deletar" in linha and linha["ids_faturas_deletar"]:
        st.caption(f"IDs de faturas a deletar: {linha['ids_faturas_deletar']}")
