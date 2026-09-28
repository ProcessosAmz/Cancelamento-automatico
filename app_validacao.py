#!/usr/bin/env python3
"""
Tela (Streamlit) do cancelamento automatico, uma pagina por empresa
(Amazonet, Mania - ver empresas.py): valida os clientes trazidos pela
consulta publica do Metabase da empresa, simula e executa o cancelamento
real no HubSoft da empresa.

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
import empresas
import hubsoft as h
import metabase_cancelamento as mb

st.set_page_config(page_title="Cancelamento automatico", layout="wide")


@st.cache_data(ttl=900, show_spinner="Baixando dados da consulta publica do Metabase...")
def carregar_metabase(empresa):
    linhas = mb.baixar_linhas_metabase(empresa)
    return pd.DataFrame(linhas)


def render(empresa):
    """Tela completa (filtros, simulacao, execucao real) de UMA empresa - os
    dados, credenciais e IDs vem todos de empresas.py."""
    # ---------------------------------------------------------------------------
    # Sidebar
    # ---------------------------------------------------------------------------
    cfg = empresas.get(empresa)
    nome = cfg["nome"]
    ids_pendentes = empresas.ids_faltando(empresa)
    # estado da execucao real separado por empresa
    k_fila = f"exec_real_fila_{empresa}"
    k_indice = f"exec_real_indice_{empresa}"

    st.sidebar.title(f"Validacao de clientes - {nome}")
    if st.sidebar.button("Recarregar dados do Metabase", key=f"recarregar_{empresa}"):
        carregar_metabase.clear(empresa)

    df = carregar_metabase(empresa)
    df["valor_fatura_proporcional"] = df.apply(ac.valor_fatura_proporcional_bruto, axis=1)
    df["gera_fatura_proporcional"] = df["ids_faturas_deletar"].apply(lambda x: bool(ac.parse_ids_fatura(x)))
    st.sidebar.caption(f"{len(df)} clientes/servicos retornados pela consulta")

    # ---------------------------------------------------------------------------
    # Filtros
    # ---------------------------------------------------------------------------
    st.title(f"{nome} - consulta do Metabase / validacao de clientes")

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
            key=f"plano_automacao_{empresa}",
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
                        st.markdown(
                            f"**2. Gerar fatura proporcional:** R$ {fp['valor']:,.2f} "
                            f"({fp['motivo']}) - \"{fp['descricao']}\""
                        )
                    else:
                        st.markdown(f"**2. Gerar fatura proporcional:** nao aplica ({fp['motivo']})")
                    multa = acoes["cobrar_multa_rescisao"]
                    if multa["aplica"]:
                        st.markdown(
                            f"**3. Cobrar multa de rescisao:** R$ {multa['valor']:,.2f} "
                            f"({multa['meses_restantes']} meses restantes de fidelidade) - \"{multa['descricao']}\""
                        )
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

            planos_execucao = ac.simular_lote(linhas, callback_progresso=_mostra_passo, empresa=empresa)
            resumo_execucao = ac.resume_lote(planos_execucao)
            caminho_log = ac.salvar_simulacao(
                planos_execucao, resumo_execucao, gerado_por="anaketllen@amazonett.com.br", empresa=empresa
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

        if ids_pendentes:
            st.error(
                f"Execucao REAL bloqueada na {nome}: faltam IDs do HubSoft desta empresa "
                "em empresas.py - " + "; ".join(f"`{k}` ({d})" for k, d in ids_pendentes)
            )

        if k_fila not in st.session_state:
            st.session_state[k_fila] = None
            st.session_state[k_indice] = 0

        confirmar_real = st.checkbox(
            f"Confirmo que quero executar o cancelamento REAL para os {len(df_automacao)} "
            f"cliente(s) do plano '{plano_automacao}', um por um, revisando cada resultado "
            "antes de seguir.",
            key=f"confirmar_real_{empresa}",
        )
        if st.button(
            "Rodar automacao REAL",
            type="primary",
            disabled=not confirmar_real or len(df_automacao) == 0 or bool(ids_pendentes),
            key=f"rodar_real_{empresa}",
        ):
            st.session_state[k_fila] = df_automacao.to_dict("records")
            st.session_state[k_indice] = 0

        if st.session_state[k_fila] is not None:
            fila = st.session_state[k_fila]
            idx = st.session_state[k_indice]

            if idx >= len(fila):
                st.success(f"Fila concluida - {len(fila)} cliente(s) processado(s).")
                if st.button("Fechar execucao real", key=f"fechar_{empresa}"):
                    st.session_state[k_fila] = None
                    st.session_state[k_indice] = 0
                    st.rerun()
            else:
                row = fila[idx]
                plano_atual = ac.montar_plano(row, empresa)
                st.markdown(
                    f"### Cliente {idx + 1}/{len(fila)}: {row['cliente']} "
                    f"(servico {row['id_cliente_servico']})"
                )

                if not plano_atual["elegivel_automacao"]:
                    st.warning(f"Pulando - inelegivel: {plano_atual['motivo_inelegivel']}")
                    if st.button("Continuar (pular este cliente)", key=f"pular_{empresa}_{idx}"):
                        st.session_state[k_indice] += 1
                        st.rerun()
                else:
                    resultado_key = f"resultado_real_{empresa}_{row['id_cliente_servico']}_{idx}"
                    if resultado_key not in st.session_state:
                        keys = h.load_keys(empresa)
                        data_venc = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
                        ids_fatura = plano_atual["acoes"]["apagar_faturas_vencidas"]["ids_fatura"]
                        multa = plano_atual["acoes"]["cobrar_multa_rescisao"]
                        proporcional = plano_atual["acoes"]["gerar_fatura_proporcional"]
                        descricao_atendimento = plano_atual["acoes"]["abrir_atendimento_retirada"]["descricao_abertura"]
                        with st.spinner(f"Executando cancelamento real de {row['cliente']}..."):
                            # gerar_multa=False e gerar_proporcional=False sempre aqui:
                            # as duas saem em chamadas separadas depois, com nosso
                            # valor/descricao proprios, pra nao ficar agrupadas na
                            # mesma fatura nem usar o calculo automatico da API (que
                            # conta da ultima cobranca ate o cancelamento, nao da
                            # ultima suspensao)
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
                                gerar_multa=False,
                                gerar_proporcional=False,
                                empresa=empresa,
                            )

                            resultado_multa = None
                            resultado_proporcional = None
                            resultado_os = None
                            sucesso_cancelamento = isinstance(resp, dict) and resp.get("status") == "success"

                            if sucesso_cancelamento and cfg["os_retirada"] == "separada":
                                # Mania: atendimento + O.S. saem fora do cancelamento
                                # (ver empresas.py, os_retirada)
                                resultado_os = acr.abrir_retirada_separada(
                                    keys,
                                    empresa,
                                    id_cliente_servico=row["id_cliente_servico"],
                                    nome=row["cliente"],
                                    telefone=row.get("telefone_cliente") or "",
                                    descricao=descricao_atendimento,
                                )

                            if sucesso_cancelamento and proporcional["aplica"]:
                                status_p, resp_p = acr.gerar_fatura_proporcional(
                                    keys,
                                    id_cliente_servico=row["id_cliente_servico"],
                                    valor=proporcional["valor"],
                                    descricao=proporcional["descricao"],
                                    data_vencimento=data_venc,
                                )
                                resultado_proporcional = (status_p, resp_p)

                            if sucesso_cancelamento and multa["aplica"]:
                                status_m, resp_m = acr.gerar_fatura_multa(
                                    keys,
                                    id_cliente_servico=row["id_cliente_servico"],
                                    valor=multa["valor"],
                                    descricao=multa["descricao"],
                                    data_vencimento=data_venc,
                                )
                                resultado_multa = (status_m, resp_m)
                        st.session_state[resultado_key] = (status, resp, corpo, resultado_multa, resultado_proporcional, resultado_os)

                    status, resp, corpo, resultado_multa, resultado_proporcional, resultado_os = st.session_state[resultado_key]
                    sucesso = isinstance(resp, dict) and resp.get("status") == "success"

                    st.write(f"**HTTP {status}**")
                    if sucesso:
                        st.success(resp.get("msg", "Sucesso"))
                        protocolo = resp.get("protocolo_cancelamento") or {}
                        ids_fatura_enviadas = [f["id_fatura"] for f in corpo["faturas"]]
                        st.markdown(
                            f"- **Protocolo de cancelamento:** {protocolo.get('id_protocolo_cancelamento')}\n"
                            f"- **Faturas informadas para cancelar:** {ids_fatura_enviadas}\n"
                        )
                    else:
                        st.error("A chamada NAO teve sucesso - revise antes de continuar.")

                    if resultado_os is not None:
                        if resultado_os["ok"]:
                            st.success(
                                f"Atendimento {resultado_os.get('id_atendimento')} (protocolo "
                                f"{resultado_os.get('protocolo_atendimento')}) e O.S. "
                                f"{resultado_os.get('id_ordem_servico')} de retirada abertos - "
                                "O.S. aguardando agendamento."
                            )
                        else:
                            st.error(
                                f"Cliente CANCELADO, mas a retirada FALHOU: {resultado_os.get('erro')} - "
                                "abrir o atendimento/O.S. manualmente no painel."
                            )
                        with st.expander("JSON do atendimento + O.S. de retirada (separados)", expanded=not resultado_os["ok"]):
                            st.json({
                                "atendimento": resultado_os["atendimento"][1] if resultado_os["atendimento"] else None,
                                "ordem_servico": resultado_os["ordem_servico"][1] if resultado_os["ordem_servico"] else None,
                            })

                    if resultado_proporcional is not None:
                        status_p, resp_p = resultado_proporcional
                        sucesso_p = isinstance(resp_p, dict) and resp_p.get("status") == "success"
                        if sucesso_p:
                            st.success(f"Fatura proporcional gerada separadamente (HTTP {status_p}).")
                        else:
                            st.error(f"Fatura proporcional FALHOU (HTTP {status_p}) - revise abaixo.")
                        with st.expander("JSON da chamada de fatura proporcional (separada)", expanded=not sucesso_p):
                            st.json(resp_p)

                    if resultado_multa is not None:
                        status_m, resp_m = resultado_multa
                        sucesso_m = isinstance(resp_m, dict) and resp_m.get("status") == "success"
                        if sucesso_m:
                            st.success(f"Fatura de multa gerada separadamente (HTTP {status_m}).")
                        else:
                            st.error(f"Fatura de multa FALHOU (HTTP {status_m}) - revise abaixo.")
                        with st.expander("JSON da chamada de multa (separada)", expanded=not sucesso_m):
                            st.json(resp_m)

                    with st.expander("JSON enviado (corpo do cancelamento)"):
                        st.json(corpo)
                    with st.expander("JSON recebido (resposta do cancelamento)", expanded=True):
                        st.json(resp)

                    if st.button("OK, revisei - rodar o proximo cliente", type="primary", key=f"ok_{empresa}_{idx}"):
                        st.session_state[k_indice] += 1
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
        escolhido = st.selectbox(
            "Cliente/servico", opcoes, format_func=lambda idcs: rotulos[idcs], key=f"detalhe_{empresa}"
        )
        linha = df_automacao[df_automacao["id_cliente_servico"] == escolhido].iloc[0]

        detalhe = linha.drop(labels=["ids_faturas_deletar"], errors="ignore")
        st.table(detalhe.astype(str).rename("Valor").to_frame())

        if "ids_faturas_deletar" in linha and linha["ids_faturas_deletar"]:
            st.caption(f"IDs de faturas a deletar: {linha['ids_faturas_deletar']}")


# Filtro de empresa: cada uma usa a sua consulta do Metabase, o seu HubSoft
# (credenciais/token) e os seus IDs - ver empresas.py
empresa_sel = st.sidebar.radio(
    "Empresa",
    list(empresas.EMPRESAS),
    format_func=lambda k: empresas.get(k)["nome"],
    horizontal=True,
    key="empresa_sel",
)
st.sidebar.markdown("---")
render(empresa_sel)
