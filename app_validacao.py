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
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acoes_cancelamento as acr
import automacao_cancelamento as ac
import empresas
import hubsoft as h
import metabase_cancelamento as mb

st.set_page_config(page_title="Cancelamento automatico", layout="wide")

# Execucao real em lote: pausa entre um cliente e outro, e quantos
# cancelamentos seguidos com falha param o lote (erro geral de permissao/API)
DELAY_LOTE_SEGUNDOS = 10
MAX_FALHAS_SEGUIDAS = 3
# clientes por bloco - depois de cada bloco o lote para e espera sua aprovacao
TAMANHO_BLOCO = 5
# resultados que geram notificacao e entram no quadro "Precisa de atencao"
RESULTADOS_ATENCAO = ("FALHOU", "CANCELADO COM PENDENCIA")


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
    k_lote = f"exec_real_lote_{empresa}"

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
        # Execucao REAL em blocos (5 clientes, 10s entre cada, aprovacao entre blocos)
        # -----------------------------------------------------------------------
        st.markdown("---")
        st.subheader(f"Execucao REAL do cancelamento (blocos de {TAMANHO_BLOCO})")
        st.error(
            "ATENCAO: isso executa o cancelamento DE VERDADE - cancela faturas, gera "
            "cobranca/multa, abre atendimento e O.S. reais, desautoriza CPE. Roda "
            f"{TAMANHO_BLOCO} clientes por vez ({DELAY_LOTE_SEGUNDOS}s entre um e outro) e para "
            "pra voce conferir e aprovar o proximo bloco. Acao real e irreversivel por "
            "este programa. NAO clique em nada nesta pagina enquanto um bloco estiver "
            "rodando (isso interrompe o bloco)."
        )

        if ids_pendentes:
            st.error(
                f"Execucao REAL bloqueada na {nome}: campos fixos sem valor em empresas.py - "
                + "; ".join(f"`{k}`" for k, _ in ids_pendentes)
            )

        def _salvar_log(lote):
            with open(lote["log"], "w", encoding="utf-8") as f:
                json.dump({k: v for k, v in lote.items() if k != "fila"}, f, ensure_ascii=False, indent=2, default=str)

        def _rodar_bloco(lote):
            """Processa os proximos TAMANHO_BLOCO clientes da fila do lote."""
            keys = h.load_keys(empresa)
            fila, total = lote["fila"], len(lote["fila"])
            inicio = lote["posicao"]
            fim_bloco = min(inicio + TAMANHO_BLOCO, total)
            lote["blocos"] += 1
            progresso = st.progress(0.0)
            status_txt = st.empty()
            tabela_ao_vivo = st.empty()
            bloco = []

            for i in range(inicio, fim_bloco):
                row = fila[i]
                n = i + 1
                status_txt.info(f"[{n}/{total}] Processando {row['cliente']} (servico {row['id_cliente_servico']})...")
                plano_atual = ac.montar_plano(row, empresa)
                if not plano_atual["elegivel_automacao"]:
                    resumo = {
                        "cliente": row.get("cliente"),
                        "id_cliente_servico": row.get("id_cliente_servico"),
                        "plano": row.get("plano"),
                        "resultado": "PULADO (inelegivel)",
                        "erro": plano_atual["motivo_inelegivel"],
                    }
                    detalhe = {}
                else:
                    try:
                        r = acr.executar_cancelamento_real(keys, empresa, row, plano_atual, lote["data_vencimento"])
                        resumo, detalhe = r["resumo"], r["detalhe"]
                    except Exception as e:  # noqa: BLE001 - registra e segue pro proximo
                        resumo = {
                            "cliente": row.get("cliente"),
                            "id_cliente_servico": row.get("id_cliente_servico"),
                            "plano": row.get("plano"),
                            "resultado": "FALHOU",
                            "erro": f"excecao: {e}",
                        }
                        detalhe = {}
                resumo = {"#": n, "bloco": lote["blocos"], **resumo}
                lote["resumos"].append(resumo)
                lote["detalhes"].append({"id_cliente_servico": row.get("id_cliente_servico"), **detalhe})
                lote["posicao"] = n
                bloco.append(resumo)
                # log gravado a cada cliente (se parar no meio, mostra ate onde foi)
                _salvar_log(lote)

                tabela_ao_vivo.dataframe(pd.DataFrame(bloco), hide_index=True, use_container_width=True)
                progresso.progress((n - inicio) / (fim_bloco - inicio))

                if resumo["resultado"] in RESULTADOS_ATENCAO:
                    st.toast(
                        f"{resumo['cliente']} ({resumo['id_cliente_servico']}): {resumo['resultado']} - "
                        f"{(resumo.get('erro') or '')[:150]}",
                        icon="⚠️" if resumo["resultado"] != "FALHOU" else "🚨",
                        duration="long",
                    )

                # trava de seguranca: erro geral (permissao, token, API fora)
                lote["falhas_seguidas"] = lote["falhas_seguidas"] + 1 if resumo["resultado"] == "FALHOU" else 0
                if lote["falhas_seguidas"] >= MAX_FALHAS_SEGUIDAS:
                    lote["interrompido"] = (
                        f"Lote interrompido apos {MAX_FALHAS_SEGUIDAS} cancelamentos seguidos com "
                        f"falha (ultimo erro: {resumo.get('erro')}) - provavel erro geral "
                        "(permissao/token/API). Corrigir e rodar de novo."
                    )
                    _salvar_log(lote)
                    break

                if n < fim_bloco:
                    status_txt.info(f"[{n}/{total}] {row['cliente']}: {resumo['resultado']} - aguardando {DELAY_LOTE_SEGUNDOS}s...")
                    time.sleep(DELAY_LOTE_SEGUNDOS)

            status_txt.empty()
            tabela_ao_vivo.empty()
            progresso.empty()
            atencao = sum(r["resultado"] in RESULTADOS_ATENCAO for r in bloco)
            if lote.get("interrompido"):
                st.toast(f"Lote INTERROMPIDO no cliente {lote['posicao']}/{total} - veja o motivo na tela.", icon="🛑", duration="infinite")
            elif lote["posicao"] >= total:
                st.toast(f"Lote concluido: {total} cliente(s) processado(s).", icon="✅", duration="infinite")
            else:
                st.toast(
                    f"Bloco {lote['blocos']} concluido ({len(bloco)} clientes, {atencao} precisam de atencao) - "
                    "confira e aprove o proximo.",
                    icon="✅" if not atencao else "⚠️",
                    duration="infinite",
                )

        lote = st.session_state.get(k_lote)
        if (
            st.session_state.pop(f"rodar_proximo_{empresa}", False)
            and lote
            and not lote.get("interrompido")
            and not lote.get("encerrado")
            and lote["posicao"] < len(lote["fila"])
        ):
            _rodar_bloco(lote)
        em_andamento = bool(lote) and not lote.get("interrompido") and not lote.get("encerrado") and lote["posicao"] < len(lote["fila"])

        elegiveis = sum(ac.montar_plano(r, empresa)["elegivel_automacao"] for r in df_automacao.to_dict("records"))
        confirmar_real = st.checkbox(
            f"Confirmo que quero executar o cancelamento REAL dos {len(df_automacao)} "
            f"cliente(s) do plano '{plano_automacao}' ({elegiveis} elegivel(is); inelegiveis "
            f"sao pulados), em blocos de {TAMANHO_BLOCO} com aprovacao entre cada bloco.",
            key=f"confirmar_real_{empresa}",
        )
        if em_andamento:
            st.info("Ja existe um lote em andamento abaixo - aprove o proximo bloco ou encerre antes de iniciar outro.")
        if st.button(
            f"Iniciar lote REAL - primeiro bloco de {min(TAMANHO_BLOCO, len(df_automacao))} de {len(df_automacao)} cliente(s)",
            type="primary",
            disabled=not confirmar_real or len(df_automacao) == 0 or bool(ids_pendentes) or em_andamento,
            key=f"rodar_real_{empresa}",
        ):
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            os.makedirs(ac.SAIDAS_DIR, exist_ok=True)
            lote = {
                "empresa": empresa,
                "plano": plano_automacao,
                "executado_por": "anaketllen@amazonett.com.br",
                "iniciado_em": ts,
                "log": os.path.join(ac.SAIDAS_DIR, f"execucao_real_{empresa}_{ts}.json"),
                "data_vencimento": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                "fila": df_automacao.to_dict("records"),
                "posicao": 0,
                "blocos": 0,
                "falhas_seguidas": 0,
                "interrompido": None,
                "encerrado": None,
                "resumos": [],
                "detalhes": [],
            }
            st.session_state[k_lote] = lote
            _rodar_bloco(lote)

        lote = st.session_state.get(k_lote)
        if lote:
            total = len(lote["fila"])
            resumos = pd.DataFrame(lote["resumos"])
            falta = total - lote["posicao"]

            if lote.get("interrompido"):
                st.error(lote["interrompido"])
            elif lote.get("encerrado"):
                st.warning(lote["encerrado"])
            elif falta == 0:
                st.success(f"Lote concluido: {total} cliente(s) processado(s) do plano '{lote['plano']}'.")
            else:
                ultimo = resumos[resumos["bloco"] == lote["blocos"]] if len(resumos) else resumos
                st.markdown(
                    f"#### Bloco {lote['blocos']} concluido - confira antes de aprovar o proximo\n"
                    f"Processados {lote['posicao']} de {total} do plano '{lote['plano']}'; faltam {falta}."
                )
                st.dataframe(ultimo, hide_index=True, use_container_width=True)
                atencao_bloco = ultimo[ultimo["resultado"].isin(RESULTADOS_ATENCAO)] if len(ultimo) else ultimo
                if len(atencao_bloco):
                    st.warning(
                        f"**Neste bloco, {len(atencao_bloco)} cliente(s) precisam de atencao:**\n\n"
                        + "\n".join(
                            f"- **{r['cliente']}** ({r['id_cliente_servico']}) - {r['resultado']}: {r.get('erro') or ''}"
                            for r in atencao_bloco.to_dict("records")
                        )
                    )
                c1, c2 = st.columns(2)
                prox = min(TAMANHO_BLOCO, falta)
                aprovar = c1.button(
                    f"Aprovar e rodar os proximos {prox} ({lote['posicao'] + 1} a {lote['posicao'] + prox} de {total})",
                    type="primary",
                    key=f"aprovar_bloco_{empresa}_{lote['blocos']}",
                )
                encerrar = c2.button("Encerrar o lote aqui", key=f"encerrar_lote_{empresa}_{lote['blocos']}")
                if encerrar:
                    lote["encerrado"] = f"Lote encerrado por voce apos {lote['posicao']} de {total} cliente(s)."
                    _salvar_log(lote)
                    st.rerun()
                if aprovar:
                    # roda no inicio do proximo rerun (antes de desenhar a lista)
                    st.session_state[f"rodar_proximo_{empresa}"] = True
                    st.rerun()

            st.markdown("---")
            st.markdown(f"**Todos os processados neste lote ({len(resumos)} de {total})**")
            contagem = resumos["resultado"].value_counts().to_dict() if len(resumos) else {}
            st.markdown(" | ".join(f"**{k}:** {v}" for k, v in contagem.items()))
            if len(resumos):
                atencao = resumos[resumos["resultado"].isin(RESULTADOS_ATENCAO)]
                if len(atencao):
                    st.warning(
                        f"**Precisa de atencao: {len(atencao)} cliente(s)**\n\n"
                        + "\n".join(
                            f"- **{r['cliente']}** ({r['id_cliente_servico']}) - {r['resultado']}: {r.get('erro') or ''}"
                            for r in atencao.to_dict("records")
                        )
                    )
            st.caption(f"Log completo (corpo enviado e respostas de cada chamada): {lote['log']}")
            st.dataframe(resumos, hide_index=True, use_container_width=True)
            st.download_button(
                "Baixar lista (CSV)",
                resumos.to_csv(index=False, sep=";").encode("utf-8-sig"),
                file_name=f"cancelamento_{empresa}_{lote['iniciado_em']}.csv",
                mime="text/csv",
                key=f"baixar_lote_{empresa}",
            )
            if not (falta and not lote.get("interrompido") and not lote.get("encerrado")):
                if st.button("Limpar resultado do lote", key=f"limpar_lote_{empresa}"):
                    del st.session_state[k_lote]
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
