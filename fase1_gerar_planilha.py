#!/usr/bin/env python3
"""Gera a planilha da Fase 1 (suspensos por debito, 75 dias) a partir dos
JSONs ja calculados em saidas/. So leitura/formatacao - nenhum calculo novo
aqui, tudo que aparece ja foi computado e conferido antes."""
import json
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

FONT = "Arial"
HEADER_FILL = "4472C4"

resultado = json.load(open("saidas/fase1_resultado_faixas.json", encoding="utf-8"))
atingiu75 = json.load(open("saidas/fase1_atingiu_75_com_contrato.json", encoding="utf-8"))
excluidos = json.load(open("saidas/excluidos_pj.json", encoding="utf-8"))

wb = Workbook()


def estiliza_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


# ---------------- Sheet Resumo ----------------
ws = wb.active
ws.title = "Resumo"
ws.column_dimensions["A"].width = 60
ws.column_dimensions["B"].width = 16

linhas = [
    ("Fase 1 - Suspensos por Debito (75 dias) - metodologia e resumo", None),
    ("", None),
    ("Fonte de dados", "API HubSoft (GraphQL + REST) - sem acesso a banco/Metabase"),
    ("Data de referencia (hoje)", "2026-09-19"),
    ("", None),
    ("PROXY usado p/ 'data_ultima_suspensao' (nao existe na API):", None),
    ("  Formula", "data_vencimento da fatura em aberto (nao paga) mais antiga + 7 dias de tolerancia"),
    ("  Tolerancia (dias)", "7 (informado por Ana)"),
    ("  Janela de busca de faturas", "2024-09-19 a 2026-09-19 (24 meses)"),
    ("", None),
    ("Total de servicos 'Suspenso por Debito' na base", 6092),
    ("Excluidos por serem PJ/link dedicado/infraestrutura", len(excluidos)),
    ("  Padroes de exclusao usados", "nome do plano contem: DEDI, CORP, (EMPRESA), TRANSPORTE, L2L, REDE NEUTRA, ou e exatamente 'POP'"),
    ("Total de candidatos apos exclusao (Tabela 1 e 2)", len(resultado)),
    ("", None),
    ("ATENCAO - contrato assinado (Tabela 2):", None),
    (
        "  O campo 'contratos' da API REST voltou VAZIO para 100% dos clientes",
        "testados (855+, incluindo clientes ativos saudaveis, nao so suspensos)."
    ),
    (
        "  Isso indica que o dado de contrato assinado nao esta disponivel via API",
        "nessa base - nao que ninguem tem contrato assinado. A coluna 'assinado'",
    ),
    ("  da Tabela 2 deve ser tratada como NAO CONFIAVEL ate confirmar no banco/Metabase.", None),
]
for i, (a, b) in enumerate(linhas, start=1):
    ca = ws.cell(row=i, column=1, value=a)
    ca.font = Font(name=FONT, bold=(i == 1 or (a and a.startswith("ATENCAO"))))
    if b is not None:
        cb = ws.cell(row=i, column=2, value=b)
        cb.font = Font(name=FONT)
        ws.cell(row=i, column=1).alignment = Alignment(wrap_text=True)

# ---------------- Sheet Tabela 1 (faixas) ----------------
ws1 = wb.create_sheet("Tabela 1 - Faixas de prazo")
headers1 = ["Faixa de prazo", "Qtd. servicos", "MRR (R$)"]
for c, h in enumerate(headers1, start=1):
    ws1.cell(row=1, column=c, value=h)
estiliza_header(ws1, len(headers1))

import collections
faixas = collections.Counter(r["faixa_prazo"] for r in resultado)
mrr_por_faixa = collections.defaultdict(float)
for r in resultado:
    mrr_por_faixa[r["faixa_prazo"]] += r["valor"]

r_idx = 2
for f in sorted(faixas):
    ws1.cell(row=r_idx, column=1, value=f).font = Font(name=FONT)
    ws1.cell(row=r_idx, column=2, value=faixas[f]).font = Font(name=FONT)
    cell = ws1.cell(row=r_idx, column=3, value=round(mrr_por_faixa[f], 2))
    cell.font = Font(name=FONT)
    cell.number_format = '#,##0.00'
    r_idx += 1
ws1.column_dimensions["A"].width = 55
ws1.column_dimensions["B"].width = 14
ws1.column_dimensions["C"].width = 16
ws1.freeze_panes = "A2"

# ---------------- Sheet Tabela 2 (por plano) ----------------
ws2 = wb.create_sheet("Tabela 2 - Atingiu 75 dias")
headers2 = ["Plano", "Qtd. atingiu 75 dias", "Contrato assinado (NAO CONFIAVEL)", "Sem contrato assinado (NAO CONFIAVEL)", "MRR (R$)"]
for c, h in enumerate(headers2, start=1):
    ws2.cell(row=1, column=c, value=h)
estiliza_header(ws2, len(headers2))

por_plano = collections.defaultdict(lambda: {"total": 0, "assinado": 0, "nao_assinado": 0, "mrr": 0.0})
for d in atingiu75:
    p = por_plano[d["plano"]]
    p["total"] += 1
    p["mrr"] += d["valor"]
    if d["contrato_info"]["tem_contrato_assinado"]:
        p["assinado"] += 1
    else:
        p["nao_assinado"] += 1

r_idx = 2
for plano, p in sorted(por_plano.items(), key=lambda kv: -kv[1]["total"]):
    ws2.cell(row=r_idx, column=1, value=plano).font = Font(name=FONT)
    ws2.cell(row=r_idx, column=2, value=p["total"]).font = Font(name=FONT)
    ws2.cell(row=r_idx, column=3, value=p["assinado"]).font = Font(name=FONT)
    ws2.cell(row=r_idx, column=4, value=p["nao_assinado"]).font = Font(name=FONT)
    cell = ws2.cell(row=r_idx, column=5, value=round(p["mrr"], 2))
    cell.font = Font(name=FONT)
    cell.number_format = '#,##0.00'
    r_idx += 1
ws2.column_dimensions["A"].width = 50
for col in "BCD":
    ws2.column_dimensions[col].width = 20
ws2.column_dimensions["E"].width = 14
ws2.freeze_panes = "A2"
ws2.auto_filter.ref = f"A1:{get_column_letter(len(headers2))}{r_idx-1}"

# ---------------- Sheet Detalhe (todos os candidatos) ----------------
ws3 = wb.create_sheet("Detalhe - todos candidatos")
headers3 = [
    "Codigo cliente", "Nome/Razao social", "ID cliente_servico", "Plano", "Valor mensal (R$)",
    "Vencimento fatura mais antiga em aberto", "Data proxy de suspensao (+7d)", "Dias suspenso (proxy)", "Faixa de prazo",
]
for c, h in enumerate(headers3, start=1):
    ws3.cell(row=1, column=c, value=h)
estiliza_header(ws3, len(headers3))

resultado_ordenado = sorted(resultado, key=lambda r: (r["faixa_prazo"], -(r["dias_suspenso_proxy"] or -999)))
for i, r in enumerate(resultado_ordenado, start=2):
    ws3.cell(row=i, column=1, value=r["codigo_cliente"]).font = Font(name=FONT)
    ws3.cell(row=i, column=2, value=r["nome_razaosocial"]).font = Font(name=FONT)
    ws3.cell(row=i, column=3, value=r["id_cliente_servico"]).font = Font(name=FONT)
    ws3.cell(row=i, column=4, value=r["plano"]).font = Font(name=FONT)
    c = ws3.cell(row=i, column=5, value=r["valor"]); c.font = Font(name=FONT); c.number_format = '#,##0.00'
    ws3.cell(row=i, column=6, value=r["vencimento_fatura_mais_antiga_aberta"]).font = Font(name=FONT)
    ws3.cell(row=i, column=7, value=r["data_proxy_suspensao"]).font = Font(name=FONT)
    ws3.cell(row=i, column=8, value=r["dias_suspenso_proxy"]).font = Font(name=FONT)
    ws3.cell(row=i, column=9, value=r["faixa_prazo"]).font = Font(name=FONT)
widths3 = [14, 34, 16, 46, 14, 22, 20, 14, 30]
for i, w in enumerate(widths3, start=1):
    ws3.column_dimensions[get_column_letter(i)].width = w
ws3.freeze_panes = "A2"
ws3.auto_filter.ref = f"A1:{get_column_letter(len(headers3))}{len(resultado_ordenado)+1}"

# ---------------- Sheet Excluidos PJ ----------------
ws4 = wb.create_sheet("Excluidos (PJ-dedicado-infra)")
headers4 = ["Codigo cliente", "Nome/Razao social", "ID cliente_servico", "Plano", "Valor mensal (R$)"]
for c, h in enumerate(headers4, start=1):
    ws4.cell(row=1, column=c, value=h)
estiliza_header(ws4, len(headers4))
for i, e in enumerate(sorted(excluidos, key=lambda x: x["plano"]), start=2):
    ws4.cell(row=i, column=1, value=e["codigo_cliente"]).font = Font(name=FONT)
    ws4.cell(row=i, column=2, value=e["nome_razaosocial"]).font = Font(name=FONT)
    ws4.cell(row=i, column=3, value=e["id_cliente_servico"]).font = Font(name=FONT)
    ws4.cell(row=i, column=4, value=e["plano"]).font = Font(name=FONT)
    c = ws4.cell(row=i, column=5, value=e["valor"]); c.font = Font(name=FONT); c.number_format = '#,##0.00'
widths4 = [14, 34, 16, 46, 14]
for i, w in enumerate(widths4, start=1):
    ws4.column_dimensions[get_column_letter(i)].width = w
ws4.freeze_panes = "A2"

wb.save("fase1_suspensos_debito.xlsx")
print("salvo: fase1_suspensos_debito.xlsx")
print(f"  Tabela 1: {len(faixas)} faixas, {len(resultado)} servicos")
print(f"  Tabela 2: {len(por_plano)} planos, {len(atingiu75)} servicos que atingiram 75 dias")
print(f"  Excluidos: {len(excluidos)} servicos PJ/dedicado/infra")
