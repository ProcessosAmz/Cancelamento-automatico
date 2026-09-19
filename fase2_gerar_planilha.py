#!/usr/bin/env python3
"""Gera a planilha da Fase 2 (simulacao de cancelamento - SO LEITURA, nada
executado). Le saidas/fase2_resultado.json, ja calculado e conferido."""
import json
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

FONT = "Arial"

dados = json.load(open("saidas/fase2_resultado.json", encoding="utf-8"))

wb = Workbook()

# ---------------- Resumo ----------------
ws = wb.active
ws.title = "Resumo"
ws.column_dimensions["A"].width = 60
ws.column_dimensions["B"].width = 20

total_proporcional = sum(r["valor_proporcional"] for r in dados)
total_multa = sum(r["multa"] for r in dados if r["multa"] is not None)
com_multa = sum(1 for r in dados if r["multa"] and r["multa"] > 0)
sem_multa = sum(1 for r in dados if r["multa"] == 0)

linhas = [
    ("Fase 2 - Simulacao de cancelamento por 75 dias de debito (SEM EXECUCAO)", None),
    ("", None),
    ("Total de servicos simulados (ja atingiram 75 dias, sem PJ/dedicado)", len(dados)),
    ("", None),
    ("FORMULA A: Valor proporcional por dias utilizados", None),
    ("  valor_proporcional = (valor_mensal / 30) * 37", "37 dias FIXOS, confirmado por Ana"),
    ("  Soma total", f"R$ {total_proporcional:,.2f}"),
    ("", None),
    ("FORMULA B: Multa de rescisao (regra REAL da automacao nativa do HubSoft)", None),
    ("  multa_base", "R$ 300,00"),
    ("  fator(mes) = 1.00 - 0.03 * mes_cancelamento", "mes 1 = 0.97 ... mes 12 = 0.64"),
    ("  multa = multa_base * fator(mes)", "se mes_cancelamento entre 1 e 12"),
    ("  multa = 0", "se mes_cancelamento > 12 (fidelidade encerrada) ou sem vigencia de fidelidade"),
    ("  mes_cancelamento estimado como", "meses corridos entre data_inicio_contrato e hoje (2026-09-19)"),
    ("  Servicos com multa > 0", com_multa),
    ("  Servicos com multa = 0 (fidelidade ja encerrada)", sem_multa),
    ("  Soma total de multa", f"R$ {total_multa:,.2f}"),
    ("", None),
    ("TOTAL GERAL A COBRAR (proporcional + multa)", f"R$ {total_proporcional + total_multa:,.2f}"),
    ("", None),
    ("IMPORTANTE", "Nenhuma fatura foi gerada, nenhum atendimento foi aberto, nenhuma acao real"),
    ("", "foi executada. Isso e so uma simulacao para conferencia antes da Fase 3."),
]
for i, (a, b) in enumerate(linhas, start=1):
    ca = ws.cell(row=i, column=1, value=a)
    ca.font = Font(name=FONT, bold=(i in (1, 5, 9, 19, 20)))
    ca.alignment = Alignment(wrap_text=True)
    if b is not None:
        cb = ws.cell(row=i, column=2, value=b)
        cb.font = Font(name=FONT, bold=(i == 19))

# ---------------- Detalhe ----------------
ws2 = wb.create_sheet("Detalhe - simulacao")
headers = [
    "Codigo cliente", "Nome/Razao social", "Plano", "Valor mensal (R$)",
    "Dias suspenso (proxy)", "Vigencia fidelidade (meses)", "Mes cancelamento (estimado)",
    "Valor proporcional (R$)", "Multa (R$)", "Total a cobrar (R$)", "Observacao multa",
]
for c, h in enumerate(headers, start=1):
    cell = ws2.cell(row=1, column=c, value=h)
    cell.font = Font(name=FONT, bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="4472C4")
    cell.alignment = Alignment(horizontal="center", wrap_text=True)

dados_ordenados = sorted(dados, key=lambda r: -(r["total_a_cobrar"] or 0))
for i, r in enumerate(dados_ordenados, start=2):
    valores = [
        r["codigo_cliente"], r["nome_razaosocial"], r["plano"], r["valor"],
        r["dias_suspenso_proxy"], r.get("vigencia_meses"), r.get("mes_cancelamento_estimado"),
        r["valor_proporcional"], r["multa"], r["total_a_cobrar"], r["multa_obs"],
    ]
    for c, v in enumerate(valores, start=1):
        cell = ws2.cell(row=i, column=c, value=v)
        cell.font = Font(name=FONT)
        if c in (4, 8, 9, 10) and isinstance(v, (int, float)):
            cell.number_format = '#,##0.00'

widths = [14, 32, 42, 14, 14, 16, 16, 16, 12, 14, 45]
for i, w in enumerate(widths, start=1):
    ws2.column_dimensions[get_column_letter(i)].width = w
ws2.freeze_panes = "A2"
ws2.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(dados_ordenados)+1}"

wb.save("fase2_simulacao_cancelamento.xlsx")
print("salvo: fase2_simulacao_cancelamento.xlsx")
print(f"  {len(dados)} servicos | proporcional=R$ {total_proporcional:,.2f} | multa=R$ {total_multa:,.2f} | total=R$ {total_proporcional+total_multa:,.2f}")
