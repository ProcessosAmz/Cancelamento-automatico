#!/usr/bin/env python3
"""
Conta, por id_cliente_servico, quantas faturas PAGAS com valor > 0 o servico
teve numa janela de tempo. Isso nao existe na consulta publica do Metabase,
entao busca na API HubSoft (GraphQL faturasByDataPagamento).

Cacheado em saidas/faturas_pagas_cache.json porque paginar a base inteira de
faturas pagas e caro (~1,5 milhao de faturas pagas so nos ultimos 24 meses,
ao redor de 1500 paginas de 1000 itens).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "saidas", "faturas_pagas_cache.json")
PAGE_SIZE = 1000
JANELA_MESES_PADRAO = 24


def _janela(meses):
    hoje = date.today()
    de = hoje - timedelta(days=meses * 30)
    return de.isoformat(), hoje.isoformat()


def _total(keys, de, ate):
    q = (
        '{ faturasByDataPagamento(data_pagamento: {de: "%s", ate: "%s"}, first: 1) '
        "{ paginatorInfo { total } } }"
    ) % (de, ate)
    data = h.gql_call(keys, q)
    return data["faturasByDataPagamento"]["paginatorInfo"]["total"]


def _pagina(keys, de, ate, page):
    q = (
        '{ faturasByDataPagamento(data_pagamento: {de: "%s", ate: "%s"}, first: %d, page: %d) '
        "{ data { id_cliente_servico valor } } }"
    ) % (de, ate, PAGE_SIZE, page)
    data = h.gql_call(keys, q)
    return data["faturasByDataPagamento"]["data"]


def calcular(ids_cliente_servico, janela_meses=JANELA_MESES_PADRAO, workers=10, progresso=None):
    """Retorna {id_cliente_servico(str): qtd_faturas_pagas_com_valor} para os
    ids pedidos, paginando faturasByDataPagamento na janela informada."""
    keys = h.load_keys()
    de, ate = _janela(janela_meses)
    ids_set = {str(i) for i in ids_cliente_servico}

    total = _total(keys, de, ate)
    paginas = (total + PAGE_SIZE - 1) // PAGE_SIZE

    contagem = {i: 0 for i in ids_set}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_pagina, keys, de, ate, p): p for p in range(1, paginas + 1)}
        done = 0
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"[faturas_pagas] ERRO pagina {p}: {e}", file=sys.stderr)
                rows = []
            for row in rows:
                idcs = str(row["id_cliente_servico"])
                if idcs in ids_set and (row.get("valor") or 0) > 0:
                    contagem[idcs] += 1
            done += 1
            if progresso:
                progresso(done, paginas)
            elif done % 100 == 0 or done == paginas:
                print(f"[faturas_pagas] {done}/{paginas} paginas ({time.time()-t0:.0f}s)")

    resultado = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "janela_meses": janela_meses,
        "de": de,
        "ate": ate,
        "contagem": contagem,
    }
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False)
    return contagem


def carregar_cache():
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    from metabase_cancelamento import carregar_servicos_suspensos

    servicos = carregar_servicos_suspensos()
    ids = [s["id_cliente_servico"] for s in servicos]
    print(f"[faturas_pagas] calculando para {len(ids)} servicos")
    calcular(ids)
    print(f"[faturas_pagas] concluido -> {CACHE_PATH}")
