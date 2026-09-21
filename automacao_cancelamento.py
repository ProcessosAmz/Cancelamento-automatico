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


def parse_ids_fatura(raw):
    """ids_faturas_deletar vem do Metabase como array do Postgres em texto,
    ex: '{10096702,10225474}'."""
    if not raw:
        return []
    limpo = str(raw).strip("{}")
    if not limpo:
        return []
    return [int(x) for x in limpo.split(",") if x.strip()]


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


def montar_plano(row):
    """Monta (SEM EXECUTAR) o plano de acoes de cancelamento para um
    cliente/servico, a partir de uma linha ja trazida pelo Metabase."""
    tem_fidelidade = bool(row.get("elegivel_multa"))
    fatura_proporcional = calcula_fatura_proporcional(row)
    ids_faturas_deletar = parse_ids_fatura(row.get("ids_faturas_deletar"))

    return {
        "id_cliente_servico": row.get("id_cliente_servico"),
        "cliente": row.get("cliente"),
        "plano": row.get("plano"),
        "cidade": row.get("cidade"),
        "estado": row.get("estado"),
        "valor_mensal": row.get("valor_mensal"),
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
            },
            "cobrar_multa_rescisao": {
                "aplica": tem_fidelidade,
                "percentual": row.get("percentual_multa") if tem_fidelidade else None,
                "valor": row.get("valor_multa_estimado") if tem_fidelidade else 0.0,
            },
            "abrir_atendimento_retirada": {
                "tipo_atendimento": TIPO_ATENDIMENTO_RETIRADA,
                "descricao_abertura": DESCRICAO_RETIRADA,
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
