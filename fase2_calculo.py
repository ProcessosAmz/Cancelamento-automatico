#!/usr/bin/env python3
"""
Fase 2 - simulacao de cancelamento por 75 dias de debito (SO LEITURA, nao
executa nenhuma acao real). Roda so para os candidatos que ja atingiram 75
dias na Fase 1 (saidas/fase1_atingiu_75_com_contrato.json).

Formulas confirmadas por Ana:
  a) Proporcional por dias utilizados: valor_proporcional = (valor_mensal/30) * 37
     (37 dias FIXOS, nao variavel por cliente)
  b) Multa de rescisao (regra real da automacao nativa "Cancelamento
     Automatico de Servicos Suspensos" do HubSoft, tela de configuracao):
       multa_base = R$ 300,00
       fator(mes) = 1.00 - 0.03*mes   para mes = 1..12
       multa = multa_base * fator(mes)   se mes_cancelamento in 1..12
       multa = 0                          se mes_cancelamento > 12 ou sem
                                           vigencia de fidelidade (vigencia_meses
                                           nula/zero -> plano sem fidelidade)
     "mes_cancelamento" = numero de meses corridos desde data_inicio_contrato
     ate hoje (proxy razoavel p/ "mes em que o cancelamento aconteceria" -
     nao temos uma data de execucao real ja que isso ainda nao foi
     executado). Se data_inicio_contrato nao existir, usa data_habilitacao
     como fallback.
"""
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
WORKERS = 10
HOJE = datetime.strptime("2026-09-19", "%Y-%m-%d").date()

DIAS_PROPORCIONAL = 37  # fixo, confirmado por Ana
MULTA_BASE = 300.0


def parse_data_br_ou_iso(s):
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def meses_corridos(data_inicio, data_fim):
    if not data_inicio:
        return None
    total_meses = (data_fim.year - data_inicio.year) * 12 + (data_fim.month - data_inicio.month)
    if data_fim.day < data_inicio.day:
        total_meses -= 1
    return max(total_meses, 0)


def calcula_multa(mes_cancelamento, vigencia_meses):
    if not vigencia_meses or vigencia_meses <= 0:
        return 0.0, "sem fidelidade (vigencia_meses nula/zero)"
    if mes_cancelamento is None:
        return None, "sem data_inicio_contrato/data_habilitacao para calcular o mes"
    mes = min(mes_cancelamento, 12)
    if mes < 1:
        mes = 1
    if mes_cancelamento > 12:
        return 0.0, f"mes_cancelamento={mes_cancelamento} > 12, fidelidade ja encerrada"
    fator = 1.00 - 0.03 * mes
    return round(MULTA_BASE * fator, 2), f"mes={mes} fator={fator:.2f}"


def busca_dados_contrato(keys, codigo_cliente, id_cliente_servico):
    status, resp = h.api_call(keys, "GET", "/api/v1/integracao/cliente",
                               params={"busca": "codigo_cliente", "termo_busca": codigo_cliente})
    if status != 200 or resp.get("status") != "success":
        return {"erro": f"HTTP {status}: {resp.get('msg')}"}
    for cli in resp.get("clientes", []):
        for s in cli.get("servicos", []):
            if str(s.get("id_cliente_servico")) == str(id_cliente_servico):
                return {
                    "data_inicio_contrato": s.get("data_inicio_contrato"),
                    "data_fim_contrato": s.get("data_fim_contrato"),
                    "data_habilitacao": s.get("data_habilitacao"),
                    "vigencia_meses": s.get("vigencia_meses"),
                }
    return {"erro": "id_cliente_servico nao encontrado na resposta"}


def main():
    keys = h.load_keys()
    atingiu75 = json.load(open(os.path.join(HERE, "saidas", "fase1_atingiu_75_com_contrato.json"), encoding="utf-8"))
    print(f"[fase2] calculando para {len(atingiu75)} servicos que atingiram 75 dias")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(busca_dados_contrato, keys, r["codigo_cliente"], r["id_cliente_servico"]): r
            for r in atingiu75
        }
        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                r["dados_contrato"] = fut.result()
            except Exception as e:
                r["dados_contrato"] = {"erro": str(e)}
            done += 1
            if done % 100 == 0 or done == len(atingiu75):
                print(f"[fase2] {done}/{len(atingiu75)} ({time.time()-t0:.0f}s)")

    resultado = []
    for r in atingiu75:
        dc = r["dados_contrato"]
        valor_proporcional = round((r["valor"] / 30) * DIAS_PROPORCIONAL, 2)

        if "erro" in dc:
            resultado.append({**r, "valor_proporcional": valor_proporcional,
                               "multa": None, "multa_obs": dc["erro"], "total_a_cobrar": None})
            continue

        data_inicio = parse_data_br_ou_iso(dc.get("data_inicio_contrato")) or parse_data_br_ou_iso(dc.get("data_habilitacao"))
        mes_cancel = meses_corridos(data_inicio, HOJE)
        multa, obs = calcula_multa(mes_cancel, dc.get("vigencia_meses"))
        total = None if multa is None else round(valor_proporcional + multa, 2)

        resultado.append({
            **r,
            "data_inicio_contrato": dc.get("data_inicio_contrato"),
            "vigencia_meses": dc.get("vigencia_meses"),
            "mes_cancelamento_estimado": mes_cancel,
            "valor_proporcional": valor_proporcional,
            "multa": multa,
            "multa_obs": obs,
            "total_a_cobrar": total,
        })

    out = os.path.join(HERE, "saidas", "fase2_resultado.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"[fase2] concluido -> {out}")

    com_erro = [r for r in resultado if r.get("multa") is None]
    print(f"[fase2] {len(com_erro)} sem multa calculavel (ver 'multa_obs')")
    total_proporcional = sum(r["valor_proporcional"] for r in resultado)
    total_multa = sum(r["multa"] for r in resultado if r["multa"] is not None)
    print(f"[fase2] soma valor_proporcional: R$ {total_proporcional:,.2f}")
    print(f"[fase2] soma multa: R$ {total_multa:,.2f}")
    print(f"[fase2] total a cobrar (soma das duas): R$ {total_proporcional + total_multa:,.2f}")


if __name__ == "__main__":
    main()
