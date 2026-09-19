#!/usr/bin/env python3
"""
Fase 1 - passo 3: para os candidatos que ja atingiram 75 dias (proxy), busca
via REST (/api/v1/integracao/cliente?busca=codigo_cliente) se o servico tem
contrato assinado. So roda pros que atingiram 75 dias para nao gastar
milhares de chamadas REST desnecessarias.

Classificacao: "contratos" (lista) nao vazia = CONTRATO ASSINADO;
"contratos" vazia = SEM CONTRATO ASSINADO (independente de
contratos_pendentes/contratos_sem_assinatura, que so indicam que existe
alguma pendencia, nao uma assinatura valida).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
WORKERS = 10


def busca_contrato(keys, codigo_cliente, id_cliente_servico):
    status, resp = h.api_call(keys, "GET", "/api/v1/integracao/cliente",
                               params={"busca": "codigo_cliente", "termo_busca": codigo_cliente})
    if status != 200 or resp.get("status") != "success":
        return {"erro": f"HTTP {status}: {resp.get('msg')}"}
    for cli in resp.get("clientes", []):
        for s in cli.get("servicos", []):
            if str(s.get("id_cliente_servico")) == str(id_cliente_servico):
                contratos = s.get("contratos") or []
                return {
                    "tem_contrato_assinado": len(contratos) > 0,
                    "qtd_contratos": len(contratos),
                    "contratos_sem_assinatura": s.get("contratos_sem_assinatura"),
                    "contratos_pendentes": s.get("contratos_pendentes"),
                }
    return {"erro": "id_cliente_servico nao encontrado na resposta"}


def main():
    keys = h.load_keys()
    resultado = json.load(open(os.path.join(HERE, "saidas", "fase1_resultado_faixas.json"), encoding="utf-8"))
    atingiu_75 = [r for r in resultado if r["faixa_prazo"] == "1 - ATINGIU 75 DIAS"]
    print(f"[contratos] verificando {len(atingiu_75)} servicos que atingiram 75 dias")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(busca_contrato, keys, r["codigo_cliente"], r["id_cliente_servico"]): r
            for r in atingiu_75
        }
        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                r["contrato_info"] = fut.result()
            except Exception as e:
                r["contrato_info"] = {"erro": str(e)}
            done += 1
            if done % 50 == 0 or done == len(atingiu_75):
                print(f"[contratos] {done}/{len(atingiu_75)} ({time.time()-t0:.0f}s)")

    out = os.path.join(HERE, "saidas", "fase1_atingiu_75_com_contrato.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(atingiu_75, f, ensure_ascii=False, indent=2)
    print(f"[contratos] concluido -> {out}")

    erros = [r for r in atingiu_75 if "erro" in r["contrato_info"]]
    if erros:
        print(f"[contratos] AVISO: {len(erros)} com erro na consulta (ver campo contrato_info.erro)")


if __name__ == "__main__":
    main()
