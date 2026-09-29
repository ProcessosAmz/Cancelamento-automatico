#!/usr/bin/env python3
"""
Tudo que muda de uma empresa (instancia HubSoft) pra outra fica aqui: prefixo
das credenciais no .env, consulta publica do Metabase e o corpo do
cancelamento (cada instancia tem os seus cadastros, entao os IDs de tipo de
atendimento, usuario, motivo etc. NAO sao os mesmos).

corpo_cancelamento_fixo: corpo de POST /api/v1/cliente/servico/
protocolo_cancelamento com TODOS os campos fixos ja preenchidos, igual ao
corpo confirmado da Amazonet (rotas_automacao_hubsoft.json). O programa so
preenche os campos variaveis de cada cliente (ver CAMPOS_VARIAVEIS e
acoes_cancelamento.montar_corpo_cancelamento). Valor None num campo fixo =
ainda nao informado - a execucao REAL fica bloqueada (ver ids_faltando).
"""

# Campos preenchidos por cliente (NAO ficam no corpo fixo)
CAMPOS_VARIAVEIS = [
    "id_cliente_servico",
    "empresa.id_empresa",
    "observacao",
    "gerar_multa",
    "gerar_proporcional",
    "data_vencimento",
    "faturas",
    "atendimento.descricao_abertura",
    "atendimento.nome_contato",
    "atendimento.telefone_contato",
    "atendimento.email_contato",
    "ordem_servico.data_inicio_programado",
    "ordem_servico.data_termino_programado",
]

EMPRESAS = {
    "amazonet": {
        "nome": "Amazonet",
        # HUBSOFT_BASE_URL, HUBSOFT_CLIENT_ID, ... no .env
        "prefixo_env": "HUBSOFT_",
        "token_cache": "token_cache.json",
        "metabase_env": "METABASE_PUBLIC_URL",
        "metabase_url_padrao": (
            "https://amazonet.hubsoft.com.br:8443/public/question/"
            "e219a17c-b395-41c9-a7c2-31697dfc1276"
        ),
        "fila_agendamento": "FILA_AMZ_AGENDAMENTO",
        # multa (valor_multa_estimado) e id_empresa vem prontos da consulta.
        # Meses restantes de fidelidade = 13 - mes_cancelamento da consulta,
        # a mesma conta que a consulta usa pro valor da multa (29/09/2026;
        # antes era 13 - faturas pagas, que nao batia com o valor cobrado)
        "meses_restantes_por": "mes_cancelamento",
        # atendimento + O.S. de retirada abertos pela propria chamada de
        # cancelamento (corpo_cancelamento_fixo.atendimento/ordem_servico)
        "os_retirada": "junto",
        # Confirmado via CANCELAMENTO REAL em 25/09/2026 (cliente 79593,
        # protocolo 132590) - ver rotas_automacao_hubsoft.json.
        "corpo_cancelamento_fixo": {
            "motivo_cancelamento": {"id_motivo_cancelamento": 67},  # "Cancelamento Automatico"
            "cancelar_fatura_pendente": True,
            "gerar_fatura": True,
            "abrir_os_retirada": True,
            "desautorizar_cpe": True,
            "remover_porta": False,
            "tipo_calculo": "automatico",
            "data_referencia_calculo_proporcional": None,
            "atendimento": {
                "tipo_atendimento": {"id_tipo_atendimento": 288},  # "RETIRADA DE EQUIPAMENTOS"
                "atendimento_status": {"id_atendimento_status": 1},
                "usuarios_responsaveis": [{"id": 1273}],  # FILA_AMZ_AGENDAMENTO (amzagendamento@amazonett.com.br)
            },
            "descricao_os_retirada": "Equipamentos no momento do cancelamento",
            "ordem_servico": {
                "status": "aguardando_agendamento",
                "duracao": "01:00:00",
                "hora_inicio_programado": "09:00:00",
                "hora_termino_programado": "18:00:00",
                "descricao_servico": "RETIRAR EQUIPAMENTO EM COMODATO.",
                "tecnicos": [{"id": 1273}],  # FILA_AMZ_AGENDAMENTO (amzagendamento@amazonett.com.br)
                "disponibilidade": [{"id_periodo_dia": 1}, {"id_periodo_dia": 2}],  # manha, tarde
                "prioridade": {"id_prioridade": 3},
            },
        },
        # usado so pelos fluxos antigos de acoes_cancelamento (O.S. avulsa)
        "id_tipo_ordem_servico_retirada": 3,
    },
    "mania": {
        "nome": "Mania",
        # HUBSOFT_MANIA_BASE_URL, HUBSOFT_MANIA_CLIENT_ID, ... no .env
        "prefixo_env": "HUBSOFT_MANIA_",
        "token_cache": "token_cache_mania.json",
        "metabase_env": "mania_metabase",
        "metabase_url_padrao": (
            "https://mania.hubsoft.com.br:8443/public/question/"
            "17879d74-a22f-48f3-a135-79f86a04073b"
        ),
        "fila_agendamento": "FILA_MANIA_AGENDAMENTO",
        # Mesmo corpo da Amazonet, com os IDs do HubSoft da Mania (informados
        # pela Ana em 28/09/2026)
        "corpo_cancelamento_fixo": {
            "motivo_cancelamento": {"id_motivo_cancelamento": 53},  # "Cancelamento Automatico"
            "cancelar_fatura_pendente": True,
            "gerar_fatura": True,
            "abrir_os_retirada": True,
            "desautorizar_cpe": True,
            "remover_porta": False,
            "tipo_calculo": "automatico",
            "data_referencia_calculo_proporcional": None,
            "atendimento": {
                "tipo_atendimento": {"id_tipo_atendimento": 428},  # "RETIRADA DE EQUIPAMENTOS"
                "atendimento_status": {"id_atendimento_status": 11},
                "usuarios_responsaveis": [{"id": 779}],  # FILA_MANIA_AGENDAMENTO
            },
            "descricao_os_retirada": "Equipamentos no momento do cancelamento",
            # igual ao que o painel da Mania envia (capturado no F12 em
            # 28/09/2026, tela "Cancelamento do Servico"): tipo da O.S.,
            # "Permite modificar o horario posteriormente" e horario 08-09h
            # (duracao 1h) - campos que o corpo da Amazonet nao tem
            "ordem_servico": {
                "status": "aguardando_agendamento",
                "duracao": "01:00:00",
                "tipo_ordem_servico": {"id_tipo_ordem_servico": 9},  # "RETIRADA DE EQUIPAMENTOS"
                "permite_modificar_horario_os": True,
                "ordem_servico_produto_item": [],
                "hora_inicio_programado": "08:00:00",
                "hora_termino_programado": "09:00:00",
                "descricao_servico": "RETIRAR EQUIPAMENTO EM COMODATO.",
                "tecnicos": [{"id": 779}],  # FILA_MANIA_AGENDAMENTO
                "disponibilidade": [{"id_periodo_dia": 1}, {"id_periodo_dia": 2}],  # manha, tarde
                "prioridade": {"id_prioridade": 3},
            },
        },
        "id_tipo_ordem_servico_retirada": 9,
        # multa (valor_multa_estimado) e id_empresa (AM=64, PA=68) vem prontos
        # da consulta - ja com a tabela do contrato da Mania: (valor sem
        # fidelidade - valor liquido) * (13 - mes_cancelamento). Meses
        # restantes = 13 - mes_cancelamento (1o mes = x12 ... 12o mes = x1).
        "meses_restantes_por": "mes_cancelamento",
        # O HubSoft da Mania barra o usuario da API de "agendar ordens de
        # servico manualmente" dentro do cancelamento (a O.S. ali exige
        # data/hora/tecnico). Por isso: cancela SEM O.S. e depois abre
        # atendimento + O.S. pelas rotas de integracao, que deixam a O.S. em
        # "aguardando_agendamento" pro setor montar a rota (testado no Postman
        # em 28/09/2026: atendimento 434384 + O.S. 155132, cliente 36107).
        # Os IDs usados sao os do corpo_cancelamento_fixo acima.
        "os_retirada": "separada",
    },
}


def get(empresa):
    return EMPRESAS[empresa]


def _nulos(valor, caminho=""):
    if valor is None:
        return [caminho]
    if isinstance(valor, dict):
        return [c for k, v in valor.items() for c in _nulos(v, f"{caminho}.{k}" if caminho else k)]
    if isinstance(valor, list):
        return [c for i, v in enumerate(valor) for c in _nulos(v, f"{caminho}[{i}]")]
    return []


# campos fixos que sao null de proposito
_NULOS_PERMITIDOS = {"data_referencia_calculo_proporcional"}


def ids_faltando(empresa):
    """Lista (campo, descricao) dos campos fixos do corpo de cancelamento
    ainda sem valor (None) pra empresa."""
    corpo = EMPRESAS[empresa]["corpo_cancelamento_fixo"]
    return [
        (c, "campo fixo do corpo de cancelamento sem valor")
        for c in _nulos(corpo)
        if c not in _NULOS_PERMITIDOS
    ]
