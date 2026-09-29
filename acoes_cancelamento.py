#!/usr/bin/env python3
"""
Acoes reais de cancelamento via API do HubSoft.

IMPORTANTE: as rotas usadas aqui criam atendimento/O.S. DE VERDADE (nao e
sandbox, ver hubsoft.py). Cada chamada aqui e uma acao real e nao reversivel
por este programa.

Fluxo antigo (executar_um/executar_lote): abre um atendimento generico
pedindo cancelamento (nao usado pela tela atual).

Fluxo novo (abrir_atendimento_retirada): abre o atendimento especifico de
"RETIRADA DE EQUIPAMENTOS" com responsavel FILA_AMZ_AGENDAMENTO. Parametros
confirmados com a Ana em 22/09/2026 testando contra o HubSoft de verdade -
ver rotas_automacao_hubsoft.json para o historico dos testes.
"""
import copy
import re
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import automacao_cancelamento as ac
import empresas
import hubsoft as h

HERE = os.path.dirname(os.path.abspath(__file__))
SAIDAS_DIR = os.path.join(HERE, "saidas")

# IDs da Amazonet (o corpo de cada empresa fica em empresas.py) - usados
# pelos fluxos antigos abaixo, que so rodam na Amazonet.
_CORPO_AMZ = empresas.get("amazonet")["corpo_cancelamento_fixo"]
ID_TIPO_ATENDIMENTO_RETIRADA = _CORPO_AMZ["atendimento"]["tipo_atendimento"]["id_tipo_atendimento"]
ID_USUARIO_RESPONSAVEL_RETIRADA = _CORPO_AMZ["atendimento"]["usuarios_responsaveis"][0]["id"]
ID_ATENDIMENTO_STATUS_INICIAL = _CORPO_AMZ["atendimento"]["atendimento_status"]["id_atendimento_status"]
ID_TIPO_ORDEM_SERVICO_RETIRADA = empresas.get("amazonet")["id_tipo_ordem_servico_retirada"]
ID_TECNICO_RETIRADA = _CORPO_AMZ["ordem_servico"]["tecnicos"][0]["id"]

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
    gerar_proporcional=False,
    observacao="Cliente com mais de 75 dias suspenso por debito",
    empresa="amazonet",
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
    diga em elegivel_multa.

    gerar_proporcional: False por padrao (desde 26/09/2026) - o calculo
    automatico da API conta os dias da ULTIMA COBRANCA ate o CANCELAMENTO,
    nao da ultima suspensao, entao nao e o valor real que queremos cobrar.
    Deixamos False aqui e geramos a fatura proporcional numa chamada
    separada (gerar_fatura_proporcional), com o nosso valor fixo de 37 dias.

    empresa: chave de empresas.py - os campos FIXOS vem de
    corpo_cancelamento_fixo da empresa; aqui so preenchemos os variaveis
    (empresas.CAMPOS_VARIAVEIS)."""
    corpo = copy.deepcopy(empresas.get(empresa)["corpo_cancelamento_fixo"])
    corpo["id_cliente_servico"] = int(id_cliente_servico)
    corpo["empresa"] = {"id_empresa": int(id_empresa)}
    corpo["observacao"] = observacao
    corpo["gerar_multa"] = bool(gerar_multa)
    corpo["gerar_proporcional"] = bool(gerar_proporcional)
    corpo["data_vencimento"] = data_vencimento
    corpo["faturas"] = [{"id_fatura": int(x)} for x in ids_fatura_cancelar]
    corpo["atendimento"].update(
        descricao_abertura=descricao_abertura_atendimento,
        nome_contato=nome_contato,
        telefone_contato=telefone_contato,
        email_contato=email_contato,
    )
    corpo["ordem_servico"].update(
        data_inicio_programado=data_vencimento,
        data_termino_programado=data_vencimento,
    )
    if empresas.get(empresa)["os_retirada"] == "separada":
        # atendimento + O.S. saem depois, em abrir_retirada_separada
        corpo["abrir_os_retirada"] = False
        for campo in ("atendimento", "ordem_servico", "descricao_os_retirada"):
            corpo.pop(campo)
    return corpo


def abrir_retirada_separada(keys, empresa, id_cliente_servico, nome, telefone, descricao):
    """ACAO REAL, so pra empresa com os_retirada="separada" (Mania): depois do
    cancelamento, abre o atendimento de retirada e a O.S. vinculada pelas
    rotas de integracao - a O.S. fica "aguardando_agendamento" sem data
    marcada, pro setor de agendamento montar a rota. Mesmos IDs do
    corpo_cancelamento_fixo da empresa. Confirmado no Postman em 28/09/2026
    (Mania, cliente 36107: atendimento 434384, O.S. 155132).

    abrir_os vai no corpo JSON porque o HubSoft exige booleano de verdade
    (na query string "false" vira texto e e recusado).
    Retorna dict com status/resposta de cada passo e ok=True so se os dois
    passaram."""
    fixo = empresas.get(empresa)["corpo_cancelamento_fixo"]
    at = fixo["atendimento"]
    resultado = {"ok": False, "atendimento": None, "ordem_servico": None}
    if not telefone:
        resultado["erro"] = "cliente sem telefone cadastrado (obrigatorio pra abrir o atendimento)"
        return resultado

    status_at, resp_at = h.api_call(
        keys,
        "POST",
        "/api/v1/integracao/atendimento",
        body={
            "id_cliente_servico": int(id_cliente_servico),
            "id_tipo_atendimento": at["tipo_atendimento"]["id_tipo_atendimento"],
            "id_usuario_responsavel": at["usuarios_responsaveis"][0]["id"],
            "id_atendimento_status": at["atendimento_status"]["id_atendimento_status"],
            "nome": nome,
            "telefone": telefone,
            "descricao": descricao,
            "abrir_os": False,
        },
    )
    resultado["atendimento"] = (status_at, resp_at)
    atendimento = resp_at.get("atendimento") if isinstance(resp_at, dict) else None
    id_atendimento = (atendimento or {}).get("id_atendimento")
    if not (isinstance(resp_at, dict) and resp_at.get("status") == "success" and id_atendimento):
        resultado["erro"] = "falha ao abrir o atendimento de retirada"
        return resultado
    resultado["id_atendimento"] = id_atendimento
    resultado["protocolo_atendimento"] = atendimento.get("protocolo")

    status_os, resp_os = h.api_call(
        keys,
        "POST",
        "/api/v1/integracao/ordem_servico/abrir_os",
        params={
            "id_atendimento": int(id_atendimento),
            "id_tipo_ordem_servico": fixo["ordem_servico"]["tipo_ordem_servico"]["id_tipo_ordem_servico"],
            "tecnicos[0][id]": fixo["ordem_servico"]["tecnicos"][0]["id"],
        },
    )
    resultado["ordem_servico"] = (status_os, resp_os)
    if not (isinstance(resp_os, dict) and resp_os.get("status") == "success"):
        resultado["erro"] = f"atendimento {id_atendimento} aberto, mas a O.S. falhou"
        return resultado
    resultado["id_ordem_servico"] = (resp_os.get("ordem_servico") or {}).get("id_ordem_servico")
    resultado["ok"] = True
    return resultado


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
    gerar_proporcional=False,
    observacao="Cliente com mais de 75 dias suspenso por debito",
    empresa="amazonet",
):
    """ACAO REAL COMPLETA DE CANCELAMENTO: endpoint OFICIAL usado pela
    propria tela "Cancelamento do Servico" do painel HubSoft
    (POST /api/v1/cliente/servico/protocolo_cancelamento). Numa unica
    chamada: cancela as faturas vencidas informadas, gera multa/proporcional
    se pedido, abre o atendimento + O.S. de retirada de equipamento,
    desautoriza o CPE, e marca o servico como cancelado (motivo + data).
    SUBSTITUI as 5 chamadas separadas (abrir_atendimento_retirada,
    abrir_os_retirada, apagar_faturas_vencidas, gerar_fatura_proporcional,
    desautorizar_cpe) - use esta funcao daqui pra frente.

    CONFIRMADO com um cancelamento real em 25/09/2026 (cliente 79593,
    protocolo de cancelamento 132590) - ver rotas_automacao_hubsoft.json
    pro payload completo e a resposta real.

    id_empresa: VARIA por filial/regiao do cliente (ex: 114 = FILIAL MAO).
    gerar_multa: False por padrao - so True se o plano tiver fidelidade
    vigente (ver automacao_cancelamento.plano_tem_fidelidade).
    gerar_proporcional: False por padrao (desde 26/09/2026) - o calculo
    automatico da API usa dias reais (ultima cobranca ate cancelamento), nao
    o nosso valor fixo de 37 dias - gerar a fatura proporcional depois, numa
    chamada separada (gerar_fatura_proporcional).
    Retorna (status, resposta, corpo_enviado) - o corpo e devolvido junto
    pra quem chamou poder exibir/logar exatamente o que foi mandado.

    empresa: chave de empresas.py - os keys passados tem que ser da mesma
    empresa (h.load_keys(empresa)). Recusa se faltar algum campo fixo da empresa."""
    faltando = empresas.ids_faltando(empresa)
    if faltando:
        raise ValueError(
            f"Campos fixos do corpo de cancelamento da empresa '{empresa}' sem valor em empresas.py: "
            + ", ".join(k for k, _ in faltando)
        )
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
        gerar_proporcional=gerar_proporcional,
        observacao=observacao,
        empresa=empresa,
    )
    status, resp = h.api_call(
        keys,
        "POST",
        "/api/v1/cliente/servico/protocolo_cancelamento",
        params={
            "id_motivo_cancelamento": corpo["motivo_cancelamento"]["id_motivo_cancelamento"],
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


def gerar_fatura_multa(keys, id_cliente_servico, valor, descricao, data_vencimento, parcelado=False):
    """ACAO REAL: gera a multa de rescisao numa fatura SEPARADA da fatura
    proporcional - mesma rota de gerar_fatura_proporcional
    (POST .../financeiro/cobranca/com_fatura), so que numa chamada isolada.

    Por que separado: confirmado com a Ana em 26/09/2026 que quando
    gerar_multa e gerar_proporcional vao juntos na mesma chamada de
    cancelar_servico_completo, a API AGRUPA as cobrancas de multa e
    proporcional numa unica fatura (mesma data_vencimento -> mesmo
    agrupamento). O esperado e cada uma sair na sua propria fatura. Solucao:
    chamar cancelar_servico_completo com gerar_multa=False (so gera a fatura
    proporcional dentro do cancelamento) e, em seguida, chamar esta funcao
    separada pra gerar a fatura da multa."""
    return gerar_fatura_proporcional(keys, id_cliente_servico, valor, descricao, data_vencimento, parcelado)


def _ok(resp):
    return isinstance(resp, dict) and resp.get("status") == "success"


_RE_FATURA_COM_NF = re.compile(r"Nosso N\w*mero:\s*(\d+)", re.IGNORECASE)


def nosso_numero_fatura_com_nf(msg):
    """Nosso numero da fatura recusada por ter nota fiscal, lido da mensagem
    de erro do cancelamento; None se o erro for outro."""
    if not msg or "nota" not in msg.lower():
        return None
    m = _RE_FATURA_COM_NF.search(msg)
    return m.group(1) if m else None


def faturas_pendentes_cliente(keys, id_cliente_servico):
    """Faturas pendentes do servico (so leitura) - traz id_fatura e
    nosso_numero, pra achar a fatura que o HubSoft cita pelo nosso numero.
    Rota oficial GET /api/v1/integracao/cliente/financeiro (confirmada na
    Mania em 29/09/2026: nosso numero 604539 = id_fatura 754180)."""
    status, resp = h.api_call(
        keys,
        "GET",
        "/api/v1/integracao/cliente/financeiro",
        params={"busca": "id_cliente_servico", "termo_busca": int(id_cliente_servico), "apenas_pendente": "sim"},
    )
    return (resp.get("faturas") or []) if _ok(resp) else []


def executar_cancelamento_real(keys, empresa, row, plano, data_vencimento):
    """ACAO REAL COMPLETA de 1 cliente, na ordem usada pela tela:
      1. cancelar_servico_completo (gerar_multa/gerar_proporcional sempre
         False - as duas saem separadas, com nosso valor/descricao, pra nao
         agrupar na mesma fatura nem usar o calculo automatico da API, que
         conta da ultima cobranca e nao da ultima suspensao)
      2. (empresa com os_retirada="separada") atendimento + O.S. de retirada
      3. fatura proporcional, se aplica
      4. fatura de multa, se aplica
    Os passos 2-4 so rodam se o cancelamento deu certo.

    plano: automacao_cancelamento.montar_plano(row, empresa).
    Retorna dict com "resumo" (1 linha pra lista de revisao) e "detalhe"
    (corpo enviado e respostas de cada chamada, pro log de auditoria)."""
    acoes = plano["acoes"]
    proporcional = acoes["gerar_fatura_proporcional"]
    multa = acoes["cobrar_multa_rescisao"]
    descricao_atendimento = acoes["abrir_atendimento_retirada"]["descricao_abertura"]
    resumo = {
        "cliente": row.get("cliente"),
        "id_cliente_servico": row.get("id_cliente_servico"),
        "plano": row.get("plano"),
        "resultado": "FALHOU",
        "protocolo_cancelamento": None,
        "faturas_enviadas_p_cancelar": len(acoes["apagar_faturas_vencidas"]["ids_fatura"]),
        "retirada": None,
        "fatura_proporcional": "nao aplica",
        "fatura_multa": "nao aplica",
        "erro": None,
    }
    detalhe = {"tentativas_cancelamento": []}

    # Fatura com nota fiscal emitida nao pode ser apagada no cancelamento (o
    # HubSoft recusa a chamada inteira: "...foi escolhido para apagar a fatura
    # (Nosso Numero: X ...) e ela existe as seguintes notas fiscais associadas
    # a ela..."). Nesse caso tiramos essa fatura da lista e tentamos de novo -
    # ela fica em aberto pro financeiro/fiscal tratar (29/09/2026).
    ids_fatura = list(acoes["apagar_faturas_vencidas"]["ids_fatura"])
    mantidas_nf = []
    faturas_cliente = None
    while True:
        status, resp, corpo = cancelar_servico_completo(
            keys,
            id_cliente_servico=row["id_cliente_servico"],
            id_empresa=plano["id_empresa"],
            nome_contato=row.get("cliente"),
            telefone_contato=row.get("telefone_cliente") or "",
            email_contato=row.get("email_cliente") or "",
            ids_fatura_cancelar=ids_fatura,
            data_vencimento=data_vencimento,
            descricao_abertura_atendimento=descricao_atendimento,
            gerar_multa=False,
            gerar_proporcional=False,
            empresa=empresa,
        )
        detalhe["tentativas_cancelamento"].append({"http": status, "corpo": corpo, "resposta": resp})
        if _ok(resp):
            break
        msg = (resp.get("msg") if isinstance(resp, dict) else None) or f"HTTP {status}"
        nosso_numero = nosso_numero_fatura_com_nf(msg)
        if nosso_numero is None:
            resumo["erro"] = msg
            break
        if faturas_cliente is None:
            faturas_cliente = faturas_pendentes_cliente(keys, row["id_cliente_servico"])
        id_fatura_nf = next(
            (f["id_fatura"] for f in faturas_cliente if str(f.get("nosso_numero")) == nosso_numero), None
        )
        if id_fatura_nf is None or id_fatura_nf not in ids_fatura:
            resumo["erro"] = f"fatura com nota fiscal (nosso numero {nosso_numero}) nao identificada: {msg}"
            break
        ids_fatura.remove(id_fatura_nf)
        mantidas_nf.append(f"{id_fatura_nf} (nosso numero {nosso_numero})")
    detalhe["cancelamento"] = detalhe["tentativas_cancelamento"][-1]
    resumo["faturas_mantidas_por_nf"] = ", ".join(mantidas_nf) or None
    resumo["faturas_enviadas_p_cancelar"] = len(ids_fatura)
    if not _ok(resp):
        return {"resumo": resumo, "detalhe": detalhe}

    resumo["resultado"] = "CANCELADO"
    resumo["protocolo_cancelamento"] = (resp.get("protocolo_cancelamento") or {}).get("id_protocolo_cancelamento")
    avisos = []
    if mantidas_nf:
        avisos.append(
            f"fatura(s) {', '.join(mantidas_nf)} NAO apagada(s) por ter nota fiscal - "
            "ficou em aberto (cancelar a nota e apagar manualmente, se for o caso)"
        )

    if empresas.get(empresa)["os_retirada"] == "separada":
        ret = abrir_retirada_separada(
            keys, empresa, row["id_cliente_servico"], row.get("cliente"),
            row.get("telefone_cliente") or "", descricao_atendimento,
        )
        detalhe["retirada"] = ret
        if ret["ok"]:
            resumo["retirada"] = f"atendimento {ret.get('id_atendimento')} / O.S. {ret.get('id_ordem_servico')}"
        else:
            resumo["retirada"] = "FALHOU"
            avisos.append(f"retirada: {ret.get('erro')}")
    else:
        resumo["retirada"] = "no cancelamento"

    if proporcional["aplica"]:
        st_p, resp_p = gerar_fatura_proporcional(
            keys, row["id_cliente_servico"], proporcional["valor"], proporcional["descricao"], data_vencimento,
        )
        detalhe["fatura_proporcional"] = {"http": st_p, "resposta": resp_p}
        resumo["fatura_proporcional"] = f"R$ {proporcional['valor']:.2f}" if _ok(resp_p) else "FALHOU"
        if not _ok(resp_p):
            avisos.append("fatura proporcional falhou")

    if multa["aplica"]:
        st_m, resp_m = gerar_fatura_multa(
            keys, row["id_cliente_servico"], multa["valor"], multa["descricao"], data_vencimento,
        )
        detalhe["fatura_multa"] = {"http": st_m, "resposta": resp_m}
        resumo["fatura_multa"] = f"R$ {multa['valor']:.2f}" if _ok(resp_m) else "FALHOU"
        if not _ok(resp_m):
            avisos.append("fatura de multa falhou")

    if avisos:
        resumo["resultado"] = "CANCELADO COM PENDENCIA"
        resumo["erro"] = "; ".join(avisos)
    return {"resumo": resumo, "detalhe": detalhe}


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
