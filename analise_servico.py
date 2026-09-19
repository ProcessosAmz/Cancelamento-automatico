#!/usr/bin/env python3
"""
Analise pontual: servicos (cliente_servico) com status "Aguardando Assinatura
de Contrato" ou "Aguardando Agendamento" que nao possuem nenhuma ordem de
servico em aberto, ou cuja(s) ordem(ns) de servico estao como
cancelamento/inviabilidade.

Usa a API GraphQL do HubSoft (/graphql/v1), que permite listar clientes e
ordens de servico em bloco (a API REST de integracao nao permite).

Roda em duas passadas:
  1) pagina TODOS os clientes, extrai os cliente_servico com status alvo.
  2) pagina TODAS as ordens de servico, casando por id_cliente_servico.

Resultados salvos em JSON para nao perder o trabalho se precisar re-rodar
so a parte de analise.
"""
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET_STATUS = {"Aguardando Assinatura de Contrato", "Aguardando Agendamento"}
OUT_ALVO = os.path.join(HERE, "saidas", "analise_servicos_alvo.json")
OUT_OS = os.path.join(HERE, "saidas", "analise_os_por_servico.json")
OUT_FINAL = os.path.join(HERE, "saidas", "analise_resultado.json")

MAX_WORKERS = 8
PAGE_SIZE = 1000


def gql(keys, query, tentativas=4):
    for i in range(tentativas):
        try:
            status, resp = h.api_call(keys, "POST", "/graphql/v1", body={"query": query})
        except Exception as e:
            if i == tentativas - 1:
                raise
            time.sleep(1.5 * (i + 1))
            continue
        if status == 429:
            time.sleep(3 * (i + 1))
            continue
        if "errors" in resp:
            raise RuntimeError(json.dumps(resp["errors"], ensure_ascii=False))
        return resp["data"]
    raise RuntimeError("falhou apos varias tentativas")


def total_pages(keys, field):
    # NAO usar o "lastPage" de uma consulta com first=1 (ele reflete o
    # paginamento daquela propria consulta, ou seja, vira igual ao total).
    # Calculamos o numero real de paginas a partir do total e do PAGE_SIZE
    # que vamos de fato usar.
    data = gql(keys, "{ %s(first: 1) { paginatorInfo { total } } }" % field)
    total = data[field]["paginatorInfo"]["total"]
    last_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
    return last_page, total


def fetch_clientes_page(keys, page):
    q = (
        "{ clientes(first: %d, page: %d) { data { codigo_cliente nome_razaosocial "
        "servicos { id_cliente_servico servico_status { descricao } } } } }"
    ) % (PAGE_SIZE, page)
    data = gql(keys, q)
    out = []
    for cli in data["clientes"]["data"]:
        for s in cli["servicos"]:
            desc = s["servico_status"]["descricao"]
            if desc in TARGET_STATUS:
                out.append(
                    {
                        "id_cliente_servico": s["id_cliente_servico"],
                        "codigo_cliente": cli["codigo_cliente"],
                        "nome_razaosocial": cli["nome_razaosocial"],
                        "status": desc,
                    }
                )
    return out


def fetch_os_page(keys, page):
    q = (
        "{ ordensServico(first: %d, page: %d) { data { id_cliente_servico status status_fechamento } } }"
    ) % (PAGE_SIZE, page)
    data = gql(keys, q)
    # id_cliente_servico vem como String em "clientes" (escalar ID) e como
    # Int em "ordensServico" - normalizamos tudo para str antes de comparar.
    return [
        (str(row["id_cliente_servico"]), row["status"], row.get("status_fechamento"))
        for row in data["ordensServico"]["data"]
        if row["id_cliente_servico"] is not None
    ]


def passo1_clientes(keys):
    if os.path.exists(OUT_ALVO):
        print(f"[passo1] Ja existe {OUT_ALVO}, pulando (apague o arquivo para refazer).")
        with open(OUT_ALVO, "r", encoding="utf-8") as f:
            return json.load(f)

    last_page, total = total_pages(keys, "clientes")
    print(f"[passo1] clientes: total={total} paginas={last_page}")

    alvo = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_clientes_page, keys, p): p for p in range(1, last_page + 1)}
        done = 0
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                alvo.extend(fut.result())
            except Exception as e:
                print(f"[passo1] ERRO pagina {p}: {e}", file=sys.stderr)
            done += 1
            if done % 20 == 0 or done == last_page:
                dt = time.time() - t0
                print(f"[passo1] {done}/{last_page} paginas ({dt:.0f}s) - {len(alvo)} servicos alvo ate agora")

    with open(OUT_ALVO, "w", encoding="utf-8") as f:
        json.dump(alvo, f, ensure_ascii=False)
    print(f"[passo1] concluido: {len(alvo)} servicos com status alvo -> {OUT_ALVO}")
    return alvo


def passo2_os(keys, ids_alvo):
    if os.path.exists(OUT_OS):
        print(f"[passo2] Ja existe {OUT_OS}, pulando (apague o arquivo para refazer).")
        with open(OUT_OS, "r", encoding="utf-8") as f:
            return json.load(f)

    ids_alvo_set = set(str(x) for x in ids_alvo)
    last_page, total = total_pages(keys, "ordensServico")
    print(f"[passo2] ordensServico: total={total} paginas={last_page}")

    os_por_servico = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_os_page, keys, p): p for p in range(1, last_page + 1)}
        done = 0
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                for id_cs, status, status_fechamento in fut.result():
                    if id_cs in ids_alvo_set:
                        os_por_servico.setdefault(id_cs, []).append(
                            {"status": status, "status_fechamento": status_fechamento}
                        )
            except Exception as e:
                print(f"[passo2] ERRO pagina {p}: {e}", file=sys.stderr)
            done += 1
            if done % 20 == 0 or done == last_page:
                dt = time.time() - t0
                print(f"[passo2] {done}/{last_page} paginas ({dt:.0f}s) - {len(os_por_servico)} servicos-alvo com OS encontrada ate agora")

    with open(OUT_OS, "w", encoding="utf-8") as f:
        json.dump(os_por_servico, f, ensure_ascii=False)
    print(f"[passo2] concluido -> {OUT_OS}")
    return os_por_servico


def normaliza(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return s


def main():
    keys = h.load_keys()
    os.makedirs(os.path.join(HERE, "saidas"), exist_ok=True)

    alvo = passo1_clientes(keys)
    ids_alvo = [a["id_cliente_servico"] for a in alvo]
    os_por_servico = passo2_os(keys, ids_alvo)

    TERMINAIS = {"cancelamento", "inviabilidade"}

    sem_os = []              # nenhuma OS cadastrada
    sem_os_aberta = []       # tem OS, mas todas "finalizado" (nenhuma em andamento)
    com_cancel_inviab = []   # tem pelo menos 1 OS finalizada como cancelamento/inviabilidade
    tem_os_aberta = []       # tem pelo menos 1 OS com status != finalizado -> fora do problema

    for a in alvo:
        idcs = a["id_cliente_servico"]
        lista = os_por_servico.get(idcs, [])
        if not lista:
            sem_os.append(a)
            continue

        tem_aberta = any(normaliza(os_["status"]) != "finalizado" for os_ in lista)
        motivos_fechamento = [
            normaliza(os_["status_fechamento"]) for os_ in lista if os_.get("status_fechamento")
        ]
        tem_motivo_terminal = any(
            any(t in m for t in TERMINAIS) for m in motivos_fechamento
        )

        registro = {**a, "os": lista}
        if tem_motivo_terminal:
            com_cancel_inviab.append(registro)
        if not tem_aberta:
            sem_os_aberta.append(registro)
        if tem_aberta and not tem_motivo_terminal:
            tem_os_aberta.append(registro)

    # uniao (sem duplicar): sem nenhuma OS, OU sem OS aberta (todas finalizadas),
    # OU tem alguma OS com motivo de fechamento cancelamento/inviabilidade
    ids_problema = set()
    for grupo in (sem_os, sem_os_aberta, com_cancel_inviab):
        for a in grupo:
            ids_problema.add(a["id_cliente_servico"])

    motivos_fechamento_vistos = Counter()
    status_os_vistos = Counter()
    for lista in os_por_servico.values():
        for os_ in lista:
            status_os_vistos[os_["status"]] += 1
            if os_.get("status_fechamento"):
                motivos_fechamento_vistos[os_["status_fechamento"]] += 1

    resultado = {
        "total_servicos_alvo": len(alvo),
        "por_status": {
            s: sum(1 for a in alvo if a["status"] == s) for s in TARGET_STATUS
        },
        "sem_nenhuma_os": len(sem_os),
        "com_os_mas_nenhuma_aberta": len(sem_os_aberta) - len(sem_os),
        "com_os_cancelamento_ou_inviabilidade": len(com_cancel_inviab),
        "total_problema_uniao": len(ids_problema),
        "tem_os_aberta_sem_motivo_terminal": len(tem_os_aberta),
        "status_os_observados": dict(status_os_vistos),
        "motivos_fechamento_observados": dict(motivos_fechamento_vistos),
        "detalhe_sem_os": sem_os,
        "detalhe_sem_os_aberta": sem_os_aberta,
        "detalhe_com_cancel_inviab": com_cancel_inviab,
    }
    with open(OUT_FINAL, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print()
    print("=== RESULTADO ===")
    print(json.dumps({k: v for k, v in resultado.items() if not k.startswith("detalhe")}, ensure_ascii=False, indent=2))
    print(f"\nDetalhes completos em: {OUT_FINAL}")


if __name__ == "__main__":
    main()