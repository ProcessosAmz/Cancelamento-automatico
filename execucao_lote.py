#!/usr/bin/env python3
"""
Execucao de um lote de cancelamento SEM tela - usada pelo agendador.py.
Mesma sequencia da execucao real da tela (acoes_cancelamento.
executar_cancelamento_real por cliente, pausa entre clientes, trava de
falhas seguidas, log de auditoria gravado a cada cliente em saidas/).
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import acoes_cancelamento as acr
import automacao_cancelamento as ac
import hubsoft as h

RESULTADOS_ATENCAO = ("FALHOU", "CANCELADO COM PENDENCIA")


def _salvar(lote):
    with open(lote["log"], "w", encoding="utf-8") as f:
        json.dump(lote, f, ensure_ascii=False, indent=2, default=str)


def rodar_lote(empresa, linhas, executado_por, modo="simulacao", delay=10, max_falhas=3, origem="agendador", aviso=print):
    """linhas: linhas cruas do Metabase (ja filtradas por plano/limite).
    modo "simulacao": so calcula e salva o log de simulacao (nada na API).
    modo "real": ACAO REAL, cliente por cliente.
    Retorna um resumo: {modo, log, total, contagem, interrompido, atencao}."""
    os.makedirs(ac.SAIDAS_DIR, exist_ok=True)
    if modo == "simulacao":
        planos = ac.simular_lote(linhas, empresa=empresa)
        resumo = ac.resume_lote(planos)
        path = ac.salvar_simulacao(planos, resumo, gerado_por=f"{executado_por} ({origem})", empresa=empresa)
        return {"modo": modo, "log": path, "total": len(planos), "contagem": {"SIMULADO": len(planos)},
                "interrompido": None, "atencao": [], "resumo_simulacao": resumo}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lote = {
        "empresa": empresa,
        "origem": origem,
        "executado_por": executado_por,
        "iniciado_em": ts,
        "log": os.path.join(ac.SAIDAS_DIR, f"execucao_real_{empresa}_{ts}.json"),
        "interrompido": None,
        "resumos": [],
        "detalhes": [],
    }
    keys = h.load_keys(empresa)
    data_venc = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    falhas_seguidas = 0
    total = len(linhas)

    for i, row in enumerate(linhas, start=1):
        plano = ac.montar_plano(row, empresa)
        if not plano["elegivel_automacao"]:
            resumo = {"cliente": row.get("cliente"), "id_cliente_servico": row.get("id_cliente_servico"),
                      "plano": row.get("plano"), "resultado": "PULADO (inelegivel)", "erro": plano["motivo_inelegivel"]}
            detalhe = {}
        else:
            try:
                r = acr.executar_cancelamento_real(keys, empresa, row, plano, data_venc)
                resumo, detalhe = r["resumo"], r["detalhe"]
            except Exception as e:  # noqa: BLE001 - registra e segue pro proximo
                resumo = {"cliente": row.get("cliente"), "id_cliente_servico": row.get("id_cliente_servico"),
                          "plano": row.get("plano"), "resultado": "FALHOU", "erro": f"excecao: {e}"}
                detalhe = {}
        resumo = {"#": i, **resumo}
        lote["resumos"].append(resumo)
        lote["detalhes"].append({"id_cliente_servico": row.get("id_cliente_servico"), **detalhe})
        _salvar(lote)
        aviso(f"[{empresa} {i}/{total}] {resumo['cliente']}: {resumo['resultado']}")

        falhas_seguidas = falhas_seguidas + 1 if resumo["resultado"] == "FALHOU" else 0
        if falhas_seguidas >= max_falhas:
            lote["interrompido"] = (
                f"Lote interrompido apos {max_falhas} cancelamentos seguidos com falha "
                f"(ultimo erro: {resumo.get('erro')}) - provavel erro geral (permissao/token/API)."
            )
            _salvar(lote)
            break
        if i < total:
            time.sleep(delay)

    contagem = {}
    for r in lote["resumos"]:
        contagem[r["resultado"]] = contagem.get(r["resultado"], 0) + 1
    return {
        "modo": modo,
        "log": lote["log"],
        "total": len(lote["resumos"]),
        "contagem": contagem,
        "interrompido": lote["interrompido"],
        "atencao": [
            {k: r.get(k) for k in ("cliente", "id_cliente_servico", "resultado", "erro")}
            for r in lote["resumos"] if r["resultado"] in RESULTADOS_ATENCAO
        ],
    }
