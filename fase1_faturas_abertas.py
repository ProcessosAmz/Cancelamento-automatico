#!/usr/bin/env python3
"""
Fase 1 - passo 2: para cada cliente_servico candidato (Suspenso por Debito,
ja sem os PJ/link dedicado excluidos), busca a data_vencimento da fatura em
aberto (nao paga) mais antiga - proxy de inicio da inadimplencia, ja que a
API nao expoe "data_ultima_suspensao" (confirmado via gql-schema).

faturasByDataVencimento exige o argumento obrigatorio data_vencimento
(DateRange {de, ate}), que o comando generico "gql-list" do hubsoft.py nao
suporta (so first/page/orderBy) - por isso pagina aqui na mao, no mesmo
padrao de analise_servico.py (ThreadPoolExecutor + paginatorInfo.total
calculado com o "first" que sera de fato usado).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_FATURAS_ABERTAS = os.path.join(HERE, "saidas", "faturas_abertas_min_vencimento.json")

PAGE_SIZE = 1000
WORKERS = 8

# janela de busca: 24 meses cobre folgadamente qualquer suspensao ainda
# ativa hoje sem varrer as 3.65M faturas inteiras da base.
DATA_DE = "2024-09-19"
DATA_ATE = "2026-09-19"


def total_faturas(keys):
    q = (
        '{ faturasByDataVencimento(data_vencimento: {de: "%s", ate: "%s"}, first: 1) '
        "{ paginatorInfo { total } } }"
    ) % (DATA_DE, DATA_ATE)
    data = h.gql_call(keys, q)
    return data["faturasByDataVencimento"]["paginatorInfo"]["total"]


def fetch_page(keys, page):
    q = (
        '{ faturasByDataVencimento(data_vencimento: {de: "%s", ate: "%s"}, first: %d, page: %d) '
        "{ data { id_cliente_servico data_vencimento data_pagamento } } }"
    ) % (DATA_DE, DATA_ATE, PAGE_SIZE, page)
    data = h.gql_call(keys, q)
    return data["faturasByDataVencimento"]["data"]


def main():
    keys = h.load_keys()
    candidatos = json.load(open(os.path.join(HERE, "saidas", "candidatos_pos_exclusao.json"), encoding="utf-8"))
    ids_candidatos = set(str(c["id_cliente_servico"]) for c in candidatos)
    print(f"[faturas] candidatos a casar: {len(ids_candidatos)}")

    total = total_faturas(keys)
    paginas = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"[faturas] janela {DATA_DE}..{DATA_ATE}: total={total} paginas={paginas}")

    # menor data_vencimento entre as faturas EM ABERTO (data_pagamento nula)
    # de cada id_cliente_servico candidato
    min_vencimento_aberta = {}
    qtd_faturas_no_periodo = {}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_page, keys, p): p for p in range(1, paginas + 1)}
        done = 0
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"[faturas] ERRO pagina {p}: {e}", file=sys.stderr)
                continue
            for row in rows:
                idcs = str(row["id_cliente_servico"])
                if idcs not in ids_candidatos:
                    continue
                qtd_faturas_no_periodo[idcs] = qtd_faturas_no_periodo.get(idcs, 0) + 1
                if row["data_pagamento"] is None:
                    venc = row["data_vencimento"]
                    if idcs not in min_vencimento_aberta or venc < min_vencimento_aberta[idcs]:
                        min_vencimento_aberta[idcs] = venc
            done += 1
            if done % 50 == 0 or done == paginas:
                dt = time.time() - t0
                print(f"[faturas] {done}/{paginas} paginas ({dt:.0f}s) - {len(min_vencimento_aberta)} candidatos com fatura em aberto ate agora")

    with open(OUT_FATURAS_ABERTAS, "w", encoding="utf-8") as f:
        json.dump(
            {"min_vencimento_aberta": min_vencimento_aberta, "qtd_faturas_no_periodo": qtd_faturas_no_periodo},
            f, ensure_ascii=False, indent=2,
        )
    print(f"[faturas] concluido -> {OUT_FATURAS_ABERTAS}")
    print(f"[faturas] candidatos SEM fatura em aberto na janela: {len(ids_candidatos) - len(min_vencimento_aberta)}")


if __name__ == "__main__":
    main()
