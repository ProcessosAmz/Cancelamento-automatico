#!/usr/bin/env python3
"""
Le a consulta publica do Metabase "cancelamento_automatico" (link publico,
sem autenticacao) e agrega as linhas por id_cliente_servico - um mesmo
servico pode aparecer em mais de uma linha se tiver mais de um contrato
vinculado (ex: termo de adesao + contrato principal).

Colunas de origem confirmadas na consulta (19/09/2026): cliente, plano,
cidade, valor_mensal, dias_desde_ultima_suspensao, faixa_prazo,
tratamento_multa, classificacao_contrato, id_cliente, id_cliente_servico,
id_contrato, contrato, datas de habilitacao/suspensao/75-dias/cadastro.

Regra combinada com Ana para contrato assinado quando o servico tem mais de
um contrato: assinado se PELO MENOS UM dos contratos estiver
"CONTRATO ASSINADO".
"""
import json
import os
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_METABASE_PUBLIC_URL = (
    "https://amazonet.hubsoft.com.br:8443/public/question/"
    "944831c1-aefc-43f0-afbb-e9a69179e8aa"
)

REGRA_FAIXA = "ATINGIU 75 DIAS"
MULTA_SIM = "PODE GERAR MULTA"
CONTRATO_ASSINADO = "CONTRATO ASSINADO"


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
    """Baixa o export JSON da consulta publica (1 linha por
    id_cliente_servico_contrato)."""
    url = _metabase_url().rstrip("/") + ".json"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def agrega_por_servico(linhas):
    grupos = defaultdict(list)
    for r in linhas:
        grupos[r["id_cliente_servico"]].append(r)

    registros = []
    for idcs, rows in grupos.items():
        base = rows[0]
        contratos = [
            {
                "contrato": r.get("contrato"),
                "assinado": r.get("classificacao_contrato") == CONTRATO_ASSINADO,
            }
            for r in rows
        ]
        qtd_assinados = sum(1 for c in contratos if c["assinado"])
        registros.append(
            {
                "id_cliente": base["id_cliente"],
                "id_cliente_servico": idcs,
                "cliente": base["cliente"],
                "cidade": base.get("cidade"),
                "plano": base["plano"],
                "valor_mensal": base.get("valor_mensal") or 0.0,
                "dias_suspenso": base.get("dias_desde_ultima_suspensao"),
                "faixa_prazo": base.get("faixa_prazo"),
                "aplica_regra_75d": base.get("faixa_prazo") == REGRA_FAIXA,
                "cobra_multa": base.get("tratamento_multa") == MULTA_SIM,
                "contrato_assinado": qtd_assinados > 0,
                "qtd_contratos": len(contratos),
                "qtd_contratos_assinados": qtd_assinados,
                "contratos": contratos,
                "data_ultima_suspensao": base.get("data_ultima_suspensao"),
                "data_75_dias": base.get("data_75_dias"),
                "dias_restantes_75": base.get("dias_restantes_75"),
                "data_habilitacao": base.get("data_habilitacao"),
            }
        )
    return registros


def carregar_servicos_suspensos():
    linhas = baixar_linhas_metabase()
    return agrega_por_servico(linhas)


if __name__ == "__main__":
    servicos = carregar_servicos_suspensos()
    print(f"{len(servicos)} servicos (agregados de {len(servicos)}+ linhas de contrato)")
    print(json.dumps(servicos[0], ensure_ascii=False, indent=2))
