#!/usr/bin/env python3
"""
Le a consulta publica do Metabase "cancelamento_automatico" (link publico,
sem autenticacao). A consulta ja vem com 1 linha por id_cliente_servico
(sem duplicidade por contrato) e ja filtrada para quem atingiu 75+ dias de
suspensao por debito - confirmado em 21/09/2026 (menor "dias suspenso"
encontrado na base = 75).

Colunas de origem confirmadas na consulta (22/09/2026): cliente,
telefone_cliente, plano, cidade, estado, tipo_pessoa, valor_mensal,
classificacao_contrato, data_contrato_assinado, data_ultima_suspensao,
id_cliente_servico, mes_cancelamento, qtd_faturas_total, qtd_faturas_pagas,
qtd_faturas_vencidas_abertas, qtd_faturas_para_deletar, ids_faturas_deletar,
valor_total_vencido_aberto, valor_total_pago, elegivel_multa,
percentual_multa, valor_multa_estimado.

NAO existe mais nesta consulta: id_cliente, id_contrato, contrato,
faixa_prazo, tratamento_multa, data_habilitacao (a consulta anterior, ate
19/09/2026, tinha esses campos e podia repetir linha por contrato - ver
historico do git se precisar do parser antigo).
"""
import json
import os
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_METABASE_PUBLIC_URL = (
    "https://amazonet.hubsoft.com.br:8443/public/question/"
    "e219a17c-b395-41c9-a7c2-31697dfc1276"
)

REGRA_FAIXA = "ATINGIU 75 DIAS"
CONTRATO_ASSINADO = "CONTRATO ASSINADO"
LIMIAR_DIAS_REGRA = 75


def _metabase_url():
    if os.environ.get("METABASE_PUBLIC_URL"):
        return os.environ["METABASE_PUBLIC_URL"]
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("METABASE_PUBLIC_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return DEFAULT_METABASE_PUBLIC_URL


def baixar_linhas_metabase(timeout=90):
    """Baixa o export JSON da consulta publica (1 linha por id_cliente_servico)."""
    url = _metabase_url().rstrip("/") + ".json"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _dias_desde(data_iso):
    if not data_iso:
        return None
    dt = datetime.fromisoformat(data_iso)
    return (datetime.now() - dt).days


def mapeia_servico(row):
    """Converte 1 linha crua da consulta nova no formato de registro usado
    pela tela/acoes de cancelamento (app_cancelamento.py, acoes_cancelamento.py)."""
    dias_suspenso = _dias_desde(row.get("data_ultima_suspensao"))
    contrato_assinado = row.get("classificacao_contrato") == CONTRATO_ASSINADO
    cobra_multa = bool(row.get("elegivel_multa"))

    return {
        "id_cliente_servico": row["id_cliente_servico"],
        "cliente": row["cliente"],
        "telefone_cliente": row.get("telefone_cliente"),
        "cidade": row.get("cidade"),
        "estado": row.get("estado"),
        "tipo_pessoa": row.get("tipo_pessoa"),
        "plano": row["plano"],
        "valor_mensal": row.get("valor_mensal") or 0.0,
        "dias_suspenso": dias_suspenso,
        "faixa_prazo": REGRA_FAIXA,
        "aplica_regra_75d": dias_suspenso is not None and dias_suspenso >= LIMIAR_DIAS_REGRA,
        "cobra_multa": cobra_multa,
        "percentual_multa": row.get("percentual_multa") if cobra_multa else None,
        "valor_multa_estimado": row.get("valor_multa_estimado") if cobra_multa else 0.0,
        "contrato_assinado": contrato_assinado,
        "data_contrato_assinado": row.get("data_contrato_assinado"),
        "qtd_contratos": 1,
        "qtd_contratos_assinados": 1 if contrato_assinado else 0,
        "contratos": [{"contrato": None, "assinado": contrato_assinado}],
        "data_ultima_suspensao": row.get("data_ultima_suspensao"),
        "mes_cancelamento": row.get("mes_cancelamento"),
        "qtd_faturas_total": row.get("qtd_faturas_total"),
        "qtd_faturas_pagas": row.get("qtd_faturas_pagas"),
        "qtd_faturas_vencidas_abertas": row.get("qtd_faturas_vencidas_abertas"),
        "valor_total_vencido_aberto": row.get("valor_total_vencido_aberto"),
        "valor_total_pago": row.get("valor_total_pago"),
        "ids_faturas_deletar": row.get("ids_faturas_deletar"),
    }


def carregar_servicos_suspensos():
    linhas = baixar_linhas_metabase()
    return [mapeia_servico(r) for r in linhas]


if __name__ == "__main__":
    servicos = carregar_servicos_suspensos()
    print(f"{len(servicos)} servicos")
    print(json.dumps(servicos[0], ensure_ascii=False, indent=2, default=str))
