#!/usr/bin/env python3
"""
Configuracao e estado do agendamento automatico (lido pelo agendador.py e
editado pelo painel "Agendamento" da tela).

agendamentos.json (configuracao, uma entrada por empresa):
  ativo            - liga/desliga o agendamento da empresa
  horario          - "HH:MM", horario de Manaus (UTC-4)
  dias_semana      - 0=segunda ... 6=domingo
  planos           - nomes exatos dos planos (como vem no Metabase)
  modo             - "simulacao" (so calcula) ou "real" (cancela de verdade)
  limite_clientes  - maximo de clientes por execucao (0 = sem limite)

saidas/agendador_estado.json (estado, gravado pelo agendador): ultima
execucao por empresa + batimento do agendador (pra tela saber se ele esta
ligado).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import empresas

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "agendamentos.json")
ESTADO_PATH = os.path.join(HERE, "saidas", "agendador_estado.json")

# Manaus nao tem horario de verao - fuso fixo
FUSO = timezone(timedelta(hours=-4), "Manaus")
# depois do horario marcado, ate quantos minutos ainda da pra disparar (se o
# agendador estava desligado no horario, nao roda horas depois)
JANELA_MINUTOS = 60
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]


def agora():
    return datetime.now(FUSO)


def config_padrao():
    return {
        e: {"ativo": False, "horario": "08:00", "dias_semana": [0, 1, 2, 3, 4], "planos": [],
            "modo": "simulacao", "limite_clientes": 5}
        for e in empresas.EMPRESAS
    }


def _ler(path, padrao):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def carregar_config():
    cfg = config_padrao()
    for e, v in _ler(CONFIG_PATH, {}).items():
        if e in cfg:
            cfg[e].update(v)
    return cfg


def salvar_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def carregar_estado():
    return _ler(ESTADO_PATH, {"batimento": None, "empresas": {}})


def salvar_estado(estado):
    os.makedirs(os.path.dirname(ESTADO_PATH), exist_ok=True)
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2, default=str)


def deve_rodar(cfg_empresa, ultima_data, momento):
    """True se a empresa esta ativa, hoje e dia marcado, ja passou do horario
    (dentro da janela) e ainda nao rodou hoje."""
    if not cfg_empresa.get("ativo") or not cfg_empresa.get("planos"):
        return False
    if momento.weekday() not in cfg_empresa.get("dias_semana", []):
        return False
    hh, mm = (int(x) for x in cfg_empresa.get("horario", "08:00").split(":"))
    marcado = momento.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if not (marcado <= momento < marcado + timedelta(minutes=JANELA_MINUTOS)):
        return False
    return ultima_data != momento.date().isoformat()


def proxima_execucao(cfg_empresa, momento):
    """Proximo horario marcado (datetime) ou None se desligado."""
    if not cfg_empresa.get("ativo") or not cfg_empresa.get("planos") or not cfg_empresa.get("dias_semana"):
        return None
    hh, mm = (int(x) for x in cfg_empresa.get("horario", "08:00").split(":"))
    for d in range(8):
        dia = momento + timedelta(days=d)
        cand = dia.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand.weekday() in cfg_empresa["dias_semana"] and cand > momento:
            return cand
    return None
