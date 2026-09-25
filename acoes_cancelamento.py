#!/usr/bin/env python3
"""
Acoes reais de cancelamento via API do HubSoft.

IMPORTANTE: as rotas usadas aqui criam atendimento/O.S. DE VERDADE (nao e
sandbox, ver hubsoft.py). Cada chamada aqui e uma acao real e nao reversivel
por este programa.

Fluxo antigo (executar_um/executar_lote): abre um atendimento generico
pedindo cancelamento (usado por app_cancelamento.py hoje).

Fluxo novo (abrir_atendimento_retirada): abre o atendimento especifico de
"RETIRADA DE EQUIPAMENTOS" com responsavel FILA_AMZ_AGENDAMENTO. Parametros
confirmados com a Ana em 22/09/2026 testando contra o HubSoft de verdade -
ver rotas_automacao_hubsoft.json para o historico dos testes.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import automacao_cancelamento as ac
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
SAIDAS_DIR = os.path.join(HERE, "saidas")

# Confirmados via teste real em 22/09/2026 (POST /api/v1/integracao/atendimento
# com id_cliente_servico=264046, cliente IDALIANA PEREIRA BARBOSA).
ID_TIPO_ATENDIMENTO_RETIRADA = 288  # "RETIRADA DE EQUIPAMENTOS"
ID_USUARIO_RESPONSAVEL_RETIRADA = 1273  # FILA_AMZ_AGENDAMENTO (amzagendamento@amazonett.com.br)
ID_ATENDIMENTO_STATUS_INICIAL = 1

# Confirmados via teste real em 22/09/2026 (POST .../ordem_servico/abrir_os
# com id_atendimento=3042908).
ID_TIPO_ORDEM_SERVICO_RETIRADA = 3  # "RETIRADA DE EQUIPAMENTOS"
ID_TECNICO_RETIRADA = ID_USUARIO_RESPONSAVEL_RETIRADA  # mesma FILA_AMZ_AGENDAMENTO

# Confirmados via CANCELAMENTO REAL em 25/09/2026 (cliente 79593, protocolo
# de cancelamento 132590) - ver rotas_automacao_hubsoft.json.
ID_MOTIVO_CANCELAMENTO_AUTOMATICO = 67  # "Cancelamento Automatico"
ID_PRIORIDADE_OS_RETIRADA = 3
ID_PERIODO_DIA_MANHA = 1
ID_PERIODO_DIA_TARDE = 2


def montar_corpo_cancelamento(
    id_cliente_servico,
    id_empresa,
    nome_contato,
    telefone_contato,
    email_contato,
    ids_fatura_cancelar,
    data_vencimento,
    descricao_abertura_atendimento,
    gerar_multa=False,
    observacao="Cliente com mais de 75 dias suspenso por debito",
):
    """Monta (SEM ENVIAR) o corpo da chamada de cancelamento completo - para
    poder mostrar na tela exatamente o que vai ser mandado antes/depois de
    executar de verdade. Ver cancelar_servico_completo pro que cada campo
    faz e como foi confirmado.

    descricao_abertura_atendimento: texto da descricao de abertura do
    atendimento - usar automacao_cancelamento.descricao_abertura_atendimento
    (dias suspenso) pra gerar o texto padrao combinado com a Ana em
    25/09/2026.

    gerar_multa: False por padrao - so passar True quando o plano do
    cliente tiver fidelidade vigente (ver
    automacao_cancelamento.plano_tem_fidelidade). Planos "SEM FIDELIDADE"
    nunca devem gerar multa, independente do que a consulta do Metabase
    diga em elegivel_multa."""
    return {
        "id_cliente_servico": int(id_cliente_servico),
        "motivo_cancelamento": {"id_motivo_cancelamento": ID_MOTIVO_CANCELAMENTO_AUTOMATICO},
        "empresa": {"id_empresa": int(id_empresa)},
        "observacao": observacao,
        "cancelar_fatura_pendente": True,
        "gerar_fatura": True,
        "gerar_multa": bool(gerar_multa),
        "gerar_proporcional": True,
        "abrir_os_retirada": True,
        "desautorizar_cpe": True,
        "remover_porta": False,
        "tipo_calculo": "automatico",
        "data_vencimento": data_vencimento,
        "data_referencia_calculo_proporcional": None,
        "faturas": [{"id_fatura": int(x)} for x in ids_fatura_cancelar],
        "atendimento": {
            "tipo_atendimento": {"id_tipo_atendimento": ID_TIPO_ATENDIMENTO_RETIRADA},
            "descricao_abertura": descricao_abertura_atendimento,
            "nome_contato": nome_contato,
            "telefone_contato": telefone_contato,
            "email_contato": email_contato,
            "atendimento_status": {"id_atendimento_status": ID_ATENDIMENTO_STATUS_INICIAL},
            "usuarios_responsaveis": [{"id": ID_USUARIO_RESPONSAVEL_RETIRADA}],
        },
        "descricao_os_retirada": "Equipamentos no momento do cancelamento",
        "ordem_servico": {
            "status": "aguardando_agendamento",
            "duracao": "01:00:00",
            "data_inicio_programado": data_vencimento,
            "data_termino_programado": data_vencimento,
            "hora_inicio_programado": "09:00:00",
            "hora_termino_programado": "18:00:00",
            "descricao_servico": ac.DESCRICAO_RETIRADA,
            "tecnicos": [{"id": ID_TECNICO_RETIRADA}],
            "disponibilidade": [
                {"id_periodo_dia": ID_PERIODO_DIA_MANHA},
                {"id_periodo_dia": ID_PERIODO_DIA_TARDE},
            ],
            "prioridade": {"id_prioridade": ID_PRIORIDADE_OS_RETIRADA},
        },
    }


def cancelar_servico_completo(
    keys,
    id_cliente_servico,
    id_empresa,
    nome_contato,
    telefone_contato,
    email_contato,
    ids_fatura_cancelar,
    data_vencimento,
    descricao_abertura_atendimento,
    gerar_multa=False,
    observacao="Cliente com mais de 75 dias suspenso por debito",
):
    """ACAO REAL COMPLETA DE CANCELAMENTO: endpoint OFICIAL usado pela
    propria tela "Cancelamento do Servico" do painel HubSoft
    (POST /api/v1/cliente/servico/protocolo_cancelamento). Numa unica
    chamada: cancela as faturas vencidas informadas, gera a fatura
    proporcional (calculo automatico pela API - nao precisa da nossa formula
    plano/30*37), gera a multa se gerar_multa=True, abre o atendimento +
    O.S. de retirada de equipamento, desautoriza o CPE, e marca o servico
    como cancelado (motivo + data). SUBSTITUI as 5 chamadas separadas
    (abrir_atendimento_retirada, abrir_os_retirada, apagar_faturas_vencidas,
    gerar_fatura_proporcional, desautorizar_cpe) - use esta funcao daqui pra
    frente.

    CONFIRMADO com um cancelamento real em 25/09/2026 (cliente 79593,
    protocolo de cancelamento 132590) - ver rotas_automacao_hubsoft.json
    pro payload completo e a resposta real.

    id_empresa: VARIA por filial/regiao do cliente (ex: 114 = FILIAL MAO).
    gerar_multa: False por padrao - so True se o plano tiver fidelidade
    vigente (ver automacao_cancelamento.plano_tem_fidelidade).
    Retorna (status, resposta, corpo_enviado) - o corpo e devolvido junto
    pra quem chamou poder exibir/logar exatamente o que foi mandado."""
    corpo = montar_corpo_cancelamento(
        id_cliente_servico,
        id_empresa,
        nome_contato,
        telefone_contato,
        email_contato,
        ids_fatura_cancelar,
        data_vencimento,
        descricao_abertura_atendimento,
        gerar_multa=gerar_multa,
        observacao=observacao,
    )
    status, resp = h.api_call(
        keys,
        "POST",
        "/api/v1/cliente/servico/protocolo_cancelamento",
        params={
            "id_motivo_cancelamento": ID_MOTIVO_CANCELAMENTO_AUTOMATICO,
            "id_cliente_servico": int(id_cliente_servico),
        },
        body=corpo,
    )
    return status, resp, corpo


def abrir_atendimento_retirada(keys, id_cliente_servico, nome, telefone):
    """ACAO REAL: abre um atendimento de verdade tipo "RETIRADA DE
    EQUIPAMENTOS", responsavel FILA_AMZ_AGENDAMENTO. So os 3 primeiros
    parametros mudam por cliente - o resto e sempre igual (confirmado com a
    Ana testando contra a API de verdade em 22/09/2026)."""
    return h.api_call(
        keys,
        "POST",
        "/api/v1/integracao/atendimento",
        params={
            "id_cliente_servico": int(id_cliente_servico),
            "id_tipo_atendimento": ID_TIPO_ATENDIMENTO_RETIRADA,
            "descricao": ac.DESCRICAO_RETIRADA,
            "nome": nome,
            "telefone": telefone,
            "id_usuario_responsavel": ID_USUARIO_RESPONSAVEL_RETIRADA,
            "id_atendimento_status": ID_ATENDIMENTO_STATUS_INICIAL,
        },
    )


def abrir_os_retirada(keys, id_atendimento):
    """ACAO REAL: abre a O.S. de retirada de equipamento vinculada a um
    atendimento ja aberto (chamar DEPOIS de abrir_atendimento_retirada, com
    o id_atendimento que ela devolveu). Confirmado com a Ana testando contra
    a API de verdade em 22/09/2026."""
    return h.api_call(
        keys,
        "POST",
        "/api/v1/integracao/ordem_servico/abrir_os",
        params={
            "id_atendimento": int(id_atendimento),
            "id_tipo_ordem_servico": ID_TIPO_ORDEM_SERVICO_RETIRADA,
            "tecnicos[0][id]": ID_TECNICO_RETIRADA,
        },
    )


def executar_retirada_um(keys, row):
    """ACAO REAL: encadeia os passos ja confirmados pra um cliente/servico -
    busca telefone, abre o atendimento de retirada e, com o id_atendimento
    devolvido, abre a O.S. vinculada. Ainda NAO inclui apagar fatura vencida,
    gerar fatura proporcional, cobrar multa nem desautorizar CPE - esses
    passos faltam confirmar com a API (ver rotas_automacao_hubsoft.json)."""
    resultado = {
        "id_cliente_servico": row.get("id_cliente_servico"),
        "cliente": row.get("cliente"),
        "plano": row.get("plano"),
    }
    try:
        telefone = row.get("telefone_cliente")
        if not telefone:
            resultado.update(ok=False, etapa="telefone", erro="cliente sem telefone cadastrado")
            return resultado

        status, resp = abrir_atendimento_retirada(keys, row["id_cliente_servico"], row.get("cliente"), telefone)
        if status != 200:
            resultado.update(
                ok=False, etapa="abrir_atendimento", http_status=status,
                erro=json.dumps(resp, ensure_ascii=False)[:300],
            )
            return resultado
        if not isinstance(resp, dict):
            resultado.update(ok=False, etapa="abrir_atendimento", erro=f"resposta inesperada (nao-JSON): {str(resp)[:200]}")
            return resultado
        atendimento = resp.get("atendimento")
        if not isinstance(atendimento, dict):
            atendimento = {}
        id_atendimento = atendimento.get("id_atendimento") or resp.get("id_atendimento")
        resultado["id_atendimento"] = id_atendimento
        resultado["protocolo"] = atendimento.get("protocolo") or resp.get("protocolo")
        if not id_atendimento:
            resultado.update(ok=False, etapa="abrir_atendimento", erro="resposta sem id_atendimento")
            return resultado

        status_os, resp_os = abrir_os_retirada(keys, id_atendimento)
        if status_os != 200:
            resultado.update(
                ok=False, etapa="abrir_os", http_status=status_os,
                erro=json.dumps(resp_os, ensure_ascii=False)[:300],
            )
            return resultado

        resultado.update(ok=True, etapa="atendimento_e_os_abertos", resposta_os=resp_os)
    except Exception as e:
        resultado.update(ok=False, erro=str(e))
    return resultado


def desautorizar_cpe(keys, id_cliente_servico, phy_addr=None):
    """ACAO REAL: desvincula o(s) CPE(s) (ONU/equipamento) do servico do
    cliente. Rota OFICIAL documentada (nao precisou de probing) -
    POST /api/v1/integracao/cliente/desvincular_cpe.

    Sem phy_addr, desvincula TODOS os CPEs vinculados ao servico - e o
    comportamento que queremos no cancelamento. A desvinculacao tem efeito
    imediato (nao depende de rotina de escaneamento) e fica registrada no
    historico do cliente."""
    body = {"id_cliente_servico": int(id_cliente_servico)}
    if phy_addr:
        body["phy_addr"] = phy_addr
    return h.api_call(
        keys,
        "POST",
        "/api/v1/integracao/cliente/desvincular_cpe",
        body=body,
    )


def gerar_fatura_proporcional(keys, id_cliente_servico, valor, descricao, data_vencimento, parcelado=False):
    """ACAO REAL: gera uma cobranca avulsa com fatura pro cliente/servico -
    usada pra cobrar o valor proporcional (plano/30*37) que substitui as
    faturas vencidas apagadas. Campos obrigatorios e formato de
    data_vencimento ('AAAA-MM-DD') confirmados testando de verdade contra a
    API em 22/09/2026 (POST .../financeiro/cobranca/com_fatura), depois que
    a permissao do usuario "API - ANA" foi corrigida.

    IMPORTANTE: a resposta pode trazer o "valor" dividido em MAIS DE UMA
    cobranca dentro de resp["cobranca"] (ex: uma pra "Comunicacao e
    Multimidia", outra pra "Valor Adicionado"/SVA, se o plano do cliente
    combinar os dois) - a soma delas e que bate com o "valor" enviado, nao
    o campo "valor" de uma cobranca isolada. Ver rotas_automacao_hubsoft.json
    pro teste que confirmou isso (valor=100 -> cobrancas de 20 + 80)."""
    return h.api_call(
        keys,
        "POST",
        "/api/v1/cliente/financeiro/cobranca/com_fatura",
        body={
            "cliente_servico": {"id_cliente_servico": int(id_cliente_servico)},
            "descricao": descricao,
            "valor": valor,
            "data_vencimento": data_vencimento,
            "parcelado": parcelado,
        },
    )


def apagar_faturas_vencidas(keys, ids_fatura, observacao):
    """ACAO REAL: apaga em massa as faturas vencidas informadas. Campos
    obrigatorios confirmados via erro de validacao em 22/09/2026 (POST
    .../financeiro/fatura/apagar_massivo).

    AINDA BLOQUEADA por permissao no usuario "API - ANA" (mesmo caso de
    gerar_fatura_proporcional) - ver rotas_automacao_hubsoft.json."""
    return h.api_call(
        keys,
        "POST",
        "/api/v1/cliente/financeiro/fatura/apagar_massivo",
        body={
            "faturas": [int(x) for x in ids_fatura],
            "observacao": observacao,
        },
    )


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
        telefone = row.get("telefone_cliente")
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
