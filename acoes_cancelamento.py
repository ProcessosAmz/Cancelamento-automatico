#!/usr/bin/env python3
"""
Acao real de cancelamento: abre um atendimento na fila do SAC do HubSoft
(POST /api/v1/integracao/atendimento) pedindo o cancelamento do servico.

IMPORTANTE: essa rota cria um atendimento DE VERDADE (nao e sandbox, ver
hubsoft.py). Nao cancela o servico sozinha - dispara o processo humano de
cancelamento. Cada chamada aqui e uma acao real e nao reversivel por este
programa.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
SAIDAS_DIR = os.path.join(HERE, "saidas")


def buscar_telefone(keys, nome_cliente):
    """A consulta do Metabase (desde 21/09/2026) nao traz mais id_cliente,
    entao buscamos o telefone pelo nome/razao social exato. Se der 0 ou mais
    de 1 resultado (nome ambiguo/duplicado), retorna vazio - o chamador
    trata isso como "cliente sem telefone cadastrado"."""
    q = (
        '{ clienteByNomeRazaoSocial(nome_razaosocial: "%s", first: 5) '
        "{ data { telefone_primario telefone_secundario } } }" % nome_cliente.replace('"', "'")
    )
    data = h.gql_call(keys, q)
    candidatos = (data.get("clienteByNomeRazaoSocial") or {}).get("data") or []
    if len(candidatos) != 1:
        return ""
    c = candidatos[0]
    return c.get("telefone_primario") or c.get("telefone_secundario") or ""


def montar_descricao(row):
    multa_txt = "pode gerar multa de rescisao" if row.get("cobra_multa") else "nao gera multa (sem fidelidade vigente)"
    if row.get("contrato_assinado"):
        contrato_txt = "com contrato assinado"
    else:
        contrato_txt = "SEM CONTRATO ASSINADO - verificar antes de cobrar multa"
    valor = row.get("valor_mensal") or 0
    return (
        "Cancelamento automatico por debito (regra de 75 dias suspenso). "
        f"Plano: {row.get('plano')}. Valor mensal: R$ {valor:.2f}. "
        f"Dias suspenso por debito: {row.get('dias_suspenso')}. "
        f"Contrato: {contrato_txt}. Multa: {multa_txt}. "
        "Solicito abertura do processo de cancelamento."
    )


def executar_um(keys, row):
    resultado = {
        "id_cliente_servico": row.get("id_cliente_servico"),
        "cliente": row.get("cliente"),
        "plano": row.get("plano"),
    }
    try:
        telefone = buscar_telefone(keys, row.get("cliente"))
        if not telefone:
            resultado.update(ok=False, http_status=None, erro="cliente sem telefone cadastrado")
            return resultado
        descricao = montar_descricao(row)
        status, resp = h.api_call(
            keys,
            "POST",
            "/api/v1/integracao/atendimento",
            body={
                "id_cliente_servico": int(row["id_cliente_servico"]),
                "nome": row.get("cliente"),
                "telefone": telefone,
                "descricao": descricao,
            },
        )
        ok = status == 200
        resultado.update(
            ok=ok,
            http_status=status,
            erro=None if ok else json.dumps(resp, ensure_ascii=False)[:300],
            resposta=resp,
        )
    except Exception as e:
        resultado.update(ok=False, http_status=None, erro=str(e))
    return resultado


def executar_lote(linhas, executado_por, callback_progresso=None):
    """linhas: lista de dicts (registros agregados do metabase_cancelamento).
    Executa em sequencia (nao paraleliza acoes reais de escrita), salva um
    log de auditoria em saidas/ e retorna (resultados, caminho_log)."""
    keys = h.load_keys()
    resultados = []
    for i, row in enumerate(linhas):
        resultados.append(executar_um(keys, row))
        if callback_progresso:
            callback_progresso(i + 1, len(linhas))

    os.makedirs(SAIDAS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = os.path.join(SAIDAS_DIR, f"execucao_cancelamento_{ts}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            {"executado_por": executado_por, "executado_em": ts, "resultados": resultados},
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    return resultados, log_path
