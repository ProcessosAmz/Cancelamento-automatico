#!/usr/bin/env python3
"""
Monta o plano de execucao do cancelamento automatico por 75+ dias de debito,
por cliente/servico - AINDA EM MODO SIMULACAO: so calcula e descreve o que
seria feito, nao chama nenhuma rota de escrita da API.

Regra da fatura proporcional (combinada com Ana, confirmada com exemplo real
em 21/09/2026): sempre que existem faturas vencidas a apagar
(ids_faturas_deletar), gera uma fatura substituta no valor de
valor_mensal/30*37 (cobranca proporcional aos ~37 dias de carencia/aviso
previo) no lugar delas - independente de quantas faturas o servico ja tem
pagas no historico. A multa de rescisao (planos com fidelidade vigente) ja
vem calculada pelo proprio Metabase em
elegivel_multa/percentual_multa/valor_multa_estimado - nao recalculamos
aqui, e e independente da fatura proporcional (ex: cliente com 58 faturas
pagas, fidelidade ja encerrada -> gera fatura proporcional, mas sem multa).

Acoes que fariam parte da execucao real (endpoints no HubSoft, mesmo
HUBSOFT_BASE_URL de hubsoft.py):
  1. POST /api/v1/integracao/atendimento
     - CONFIRMADO (ja usado em acoes_cancelamento.py). Falta confirmar o
       campo para "tipo de atendimento" = RETIRADA DE EQUIPAMENTOS.
  2. POST /api/v1/integracao/ordem_servico/abrir_os?id_atendimento=<id>
     - CONFIRMADO que a rota existe e id_atendimento e obrigatorio (erro de
       validacao). Faltam os campos de tipo de O.S., descricao de abertura,
       descricao de servico e tecnico (FILA_AMZ_AGENDAMENTO).
  3. .../api/v1/cliente/financeiro/fatura/apagar_massivo
     - Rota existe (mesmo host, base /api/v1/cliente/ e nao /integracao/).
       Falta confirmar metodo (POST/DELETE) e o campo com a lista de
       ids_fatura no corpo.
  4. Gerar a fatura proporcional nova - endpoint ainda nao identificado.
  5. Desautorizar CPE - endpoint/parametro ainda nao identificado.

Enquanto os itens 1 (campo extra), 2, 3, 4 e 5 nao estiverem confirmados,
`executar_lote_real` nao deve ser implementada. Use `montar_plano_lote` para
gerar a previa (simulacao) que a tela mostra.
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SAIDAS_DIR = os.path.join(HERE, "saidas")

FATURA_PROPORCIONAL_DIAS = 37
FATURA_PROPORCIONAL_BASE_DIAS = 30

TIPO_ATENDIMENTO_RETIRADA = "RETIRADA DE EQUIPAMENTOS"
DESCRICAO_RETIRADA = "RETIRAR EQUIPAMENTO EM COMODATO."
TIPO_OS_RETIRADA = "RETIRADA DE EQUIPAMENTOS"
FILA_AGENDAMENTO = "FILA_AMZ_AGENDAMENTO"

# Combinado com Ana em 25/09/2026: qual empresa/filial usar no cancelamento
# (campo "empresa" do endpoint de cancelamento). Desde 25/09/2026 a propria
# consulta do Metabase ja traz "id_empresa" pronto (bate com esse
# mapeamento: AM=114/FILIAL MAO, PA=30/FILIAL STM) - usamos o valor da
# consulta diretamente (ver montar_plano). Mantido aqui so de referencia.
ID_EMPRESA_POR_ESTADO = {
    "AM": 114,  # AMAZONET TELECOMUNICACOES LTDA (FILIAL MAO)
    "PA": 30,  # AMAZONET TELECOM (FILIAL STM)
}


def parse_ids_fatura(raw):
    """ids_faturas_deletar vem do Metabase como array do Postgres em texto,
    ex: '{6275826,6275826}'. Pode vir None, string vazia, NaN do pandas
    (quando o valor e nulo no JSON e a coluna do DataFrame vira float - NaN
    e "truthy" em Python, entao precisa de um cheque a parte), ou com o
    literal 'NULL' dentro do array (ex: '{6275826,NULL}' - de um join sem
    match na consulta) - ignoramos esses itens. A consulta tambem pode
    repetir o mesmo id_fatura mais de uma vez (uma fatura pode ter varias
    cobrancas) - removemos duplicatas aqui, preservando a ordem."""
    if not raw or (isinstance(raw, float) and raw != raw):
        return []
    limpo = str(raw).strip("{}")
    if not limpo:
        return []
    vistos = []
    for x in limpo.split(","):
        x = x.strip()
        if not x or x.upper() == "NULL":
            continue
        n = int(x)
        if n not in vistos:
            vistos.append(n)
    return vistos


def valor_fatura_proporcional_bruto(row):
    """Valor da regra plano/30*37, calculado sempre - usado so pra mostrar
    na tabela o quanto SERIA, mesmo quando nao ha fatura vencida a
    substituir (e portanto a fatura proporcional nao se aplica)."""
    valor_mensal = row.get("valor_mensal") or 0.0
    return round(valor_mensal / FATURA_PROPORCIONAL_BASE_DIAS * FATURA_PROPORCIONAL_DIAS, 2)


def calcula_fatura_proporcional(row):
    """None se nao ha nenhuma fatura vencida a apagar (regra combinada: a
    fatura proporcional so existe pra substituir as faturas vencidas que
    serao apagadas - nao depende de quantas faturas o servico ja pagou)."""
    if not parse_ids_fatura(row.get("ids_faturas_deletar")):
        return None
    return valor_fatura_proporcional_bruto(row)


def dias_suspenso_por_debito(data_ultima_suspensao):
    """Dias corridos desde a ultima suspensao por debito ate hoje."""
    if not data_ultima_suspensao:
        return None
    dt = datetime.fromisoformat(data_ultima_suspensao)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return (datetime.now() - dt).days


def descricao_abertura_atendimento(dias_em_suspensao):
    """Texto padrao (confirmado com a Ana em 25/09/2026) pra descricao de
    abertura do atendimento de cancelamento - usa dias_em_suspensao (dias
    corridos desde a ultima suspensao por debito ate hoje - o cancelamento
    real acontece ao bater 75 dias, mas como a automacao roda em lotes
    periodicos, alguns clientes já passam desse numero quando processados)."""
    return (
        f"O serviço estava com status Suspenso por Débito há {dias_em_suspensao} dias, "
        "por esse motivo foi cancelado automaticamente pelo sistema, de acordo "
        "com as configurações atuais."
    )


def plano_tem_fidelidade(plano):
    """Planos com 'SEM FIDELIDADE' no nome NUNCA cobram multa de rescisao,
    mesmo que a consulta do Metabase (elegivel_multa) diga que sim -
    combinado com a Ana em 25/09/2026 apos achar 4 clientes SEM FIDELIDADE
    com elegivel_multa=True (provavelmente erro na consulta)."""
    return "SEM FIDELIDADE" not in (plano or "").upper()


TOTAL_CICLOS_FIDELIDADE = 13


def meses_restantes_fidelidade(qtd_faturas_pagas):
    """Meses restantes de fidelidade = 13 menos o total de faturas ja pagas
    (combinado com a Ana em 26/09/2026). Nunca negativo - fidelidade ja
    cumprida vira 0."""
    return max(0, TOTAL_CICLOS_FIDELIDADE - int(qtd_faturas_pagas or 0))


def descricao_multa_rescisao(qtd_faturas_pagas):
    """Texto padrao (combinado com a Ana em 26/09/2026) pra descricao da
    fatura de multa - inclui a quantidade de meses restantes de fidelidade."""
    meses = meses_restantes_fidelidade(qtd_faturas_pagas)
    return f"Multa proporcional aos {meses} meses restantes de fidelidade"


def descricao_fatura_proporcional(plano):
    """Texto padrao (combinado com a Ana em 26/09/2026) pra descricao da
    fatura proporcional - usa os FATURA_PROPORCIONAL_DIAS fixos (37), nao os
    dias calculados automaticamente pela API (que conta da ultima cobranca
    ate o dia do cancelamento, nao da ultima suspensao - nao e o dado real
    que queremos cobrar)."""
    return (
        f"Cancelamento - Proporcional referente à {FATURA_PROPORCIONAL_DIAS} "
        f"dia(s) de utilização do serviço - {plano}"
    )


def montar_plano(row):
    """Monta (SEM EXECUTAR) o plano de acoes de cancelamento para um
    cliente/servico, a partir de uma linha ja trazida pelo Metabase."""
    aplica_multa = bool(row.get("elegivel_multa")) and plano_tem_fidelidade(row.get("plano"))
    fatura_proporcional = calcula_fatura_proporcional(row)
    ids_faturas_deletar = parse_ids_fatura(row.get("ids_faturas_deletar"))
    dias_suspenso = dias_suspenso_por_debito(row.get("data_ultima_suspensao"))

    # desde 25/09/2026 a propria consulta do Metabase ja traz id_empresa
    # pronto (bate com AM=114/FILIAL MAO, PA=30/FILIAL STM) - usamos direto.
    id_empresa = row.get("id_empresa")
    erro_empresa = None if id_empresa is not None else (
        f"Sem id_empresa na consulta pro estado '{row.get('estado')}' - confirmar "
        "manualmente antes de incluir esse cliente na automacao"
    )

    return {
        "id_cliente_servico": row.get("id_cliente_servico"),
        "cliente": row.get("cliente"),
        "plano": row.get("plano"),
        "cidade": row.get("cidade"),
        "estado": row.get("estado"),
        "valor_mensal": row.get("valor_mensal"),
        "email_cliente": row.get("email_cliente"),
        "id_empresa": id_empresa,
        "elegivel_automacao": id_empresa is not None,
        "motivo_inelegivel": erro_empresa,
        "dias_suspenso": dias_suspenso,
        "dias_habilitado_ate_suspensao": row.get("dias_habilitado_ate_suspensao"),
        "acoes": {
            "apagar_faturas_vencidas": {
                "qtd": len(ids_faturas_deletar),
                "ids_fatura": ids_faturas_deletar,
            },
            "gerar_fatura_proporcional": {
                "aplica": fatura_proporcional is not None,
                "motivo": (
                    f"substitui as {len(ids_faturas_deletar)} fatura(s) vencida(s) apagada(s)"
                    if fatura_proporcional is not None
                    else "nao ha fatura vencida a substituir"
                ),
                "valor": fatura_proporcional,
                "descricao": descricao_fatura_proporcional(row.get("plano")) if fatura_proporcional is not None else None,
            },
            "cobrar_multa_rescisao": {
                "aplica": aplica_multa,
                "percentual": row.get("percentual_multa") if aplica_multa else None,
                "valor": row.get("valor_multa_estimado") if aplica_multa else 0.0,
                "meses_restantes": meses_restantes_fidelidade(row.get("qtd_faturas_pagas")) if aplica_multa else None,
                "descricao": descricao_multa_rescisao(row.get("qtd_faturas_pagas")) if aplica_multa else None,
            },
            "abrir_atendimento_retirada": {
                "tipo_atendimento": TIPO_ATENDIMENTO_RETIRADA,
                "descricao_abertura": descricao_abertura_atendimento(dias_suspenso),
            },
            "abrir_os_retirada": {
                "tipo_os": TIPO_OS_RETIRADA,
                "descricao_abertura": DESCRICAO_RETIRADA,
                "descricao_servico": DESCRICAO_RETIRADA,
                "tecnico_responsavel": FILA_AGENDAMENTO,
                "usuario_responsavel": FILA_AGENDAMENTO,
            },
            "desautorizar_cpe": {"aplica": True},
        },
    }


def montar_plano_lote(linhas):
    """linhas: lista de dicts (linhas cruas do metabase_cancelamento).
    Retorna a lista de planos de acao, um por cliente/servico."""
    return [montar_plano(row) for row in linhas]


def simular_lote(linhas, callback_progresso=None):
    """Roda o MESMO loop cliente-por-cliente que a execucao real vai usar
    depois (so que aqui cada passo e so calculado/descrito, nada e chamado
    na API). callback_progresso(indice, total, plano) e chamado a cada
    cliente processado - pra tela poder desenhar o passo a passo em tempo
    real, como um log de execucao."""
    planos = []
    total = len(linhas)
    for i, row in enumerate(linhas, start=1):
        plano = montar_plano(row)
        planos.append(plano)
        if callback_progresso:
            callback_progresso(i, total, plano)
    return planos


def resume_lote(planos):
    """Totais agregados de um lote de planos, para mostrar na tela antes de
    qualquer execucao real."""
    return {
        "qtd_clientes": len(planos),
        "qtd_inelegiveis": sum(1 for p in planos if not p.get("elegivel_automacao", True)),
        "qtd_atendimentos_a_abrir": len(planos),
        "qtd_os_a_abrir": len(planos),
        "qtd_faturas_a_apagar": sum(p["acoes"]["apagar_faturas_vencidas"]["qtd"] for p in planos),
        "qtd_faturas_proporcionais_a_gerar": sum(
            1 for p in planos if p["acoes"]["gerar_fatura_proporcional"]["aplica"]
        ),
        "valor_faturas_proporcionais": round(
            sum(
                p["acoes"]["gerar_fatura_proporcional"]["valor"] or 0.0
                for p in planos
                if p["acoes"]["gerar_fatura_proporcional"]["aplica"]
            ),
            2,
        ),
        "qtd_com_multa": sum(1 for p in planos if p["acoes"]["cobrar_multa_rescisao"]["aplica"]),
        "valor_multa_total": round(
            sum(p["acoes"]["cobrar_multa_rescisao"]["valor"] or 0.0 for p in planos), 2
        ),
        "qtd_cpe_a_desautorizar": sum(1 for p in planos if p["acoes"]["desautorizar_cpe"]["aplica"]),
    }


def salvar_simulacao(planos, resumo, gerado_por):
    os.makedirs(SAIDAS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(SAIDAS_DIR, f"simulacao_automacao_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"gerado_por": gerado_por, "gerado_em": ts, "resumo": resumo, "planos": planos},
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    return path


def executar_lote_real(*args, **kwargs):
    raise NotImplementedError(
        "Execucao real ainda nao implementada: faltam confirmar os campos de "
        "abrir_os, o endpoint de desautorizar CPE, o endpoint de gerar fatura "
        "proporcional e o metodo/corpo de apagar_massivo (ver docstring deste "
        "arquivo). Use montar_plano_lote para a simulacao."
    )
