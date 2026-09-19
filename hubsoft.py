#!/usr/bin/env python3
"""
Conector HubSoft (Amazonet) - autenticacao OAuth2 (password grant) + consultas
a API de integracao (api/v1/integracao/...).

Uso:
    python hubsoft.py auth
    python hubsoft.py cliente --busca cpf_cnpj --termo 12345678900
    python hubsoft.py cliente --busca codigo_cliente --termo 59229
    python hubsoft.py cliente --busca nome_razaosocial --termo "ANA KETLLEN SILVA E SILVA"
    python hubsoft.py atendimento --id-cliente-servico 262252 --nome "Fulano" --telefone "92999999999" --descricao "..."
    python hubsoft.py estoque-produto [--id 123] [--pagina 0] [--itens 100]
    python hubsoft.py estoque-local [--id 123] [--pagina 0]
    python hubsoft.py estoque-movimento [--pagina 0] [--data-inicio 2026-09-01] [--data-fim 2026-09-17] [--tipo-data 1]
    python hubsoft.py raw GET /api/v1/integracao/cliente --params busca=cpf_cnpj termo_busca=12345678900
    python hubsoft.py raw POST /api/v1/integracao/estoque/movimento_estoque --body '{"id_local_estoque": 1}'

Buscas de cliente confirmadas (parametro --busca): cpf_cnpj, codigo_cliente,
nome_razaosocial. "codigo_cliente" e o numero curto que aparece na tela do
cliente (ex: 59229) - e diferente do "id_cliente" interno (ex: 60544).

ATENCAO: "atendimento" cria um chamado DE VERDADE no HubSoft (fila SAC),
nao e um sandbox. So roda se voce tiver certeza.

Todos os comandos gravam a resposta bruta em saidas/<comando>_<timestamp>.json
e imprimem um resumo no terminal.

As credenciais NAO ficam neste arquivo: elas moram em keys.env, ao lado deste
script. Nunca comite ou compartilhe keys.env.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(HERE, "keys.env")
TOKEN_CACHE_PATH = os.path.join(HERE, "token_cache.json")
SAIDAS_DIR = os.path.join(HERE, "saidas")

# margem de seguranca antes do token expirar (segundos)
TOKEN_SAFETY_MARGIN = 60


def load_keys():
    if not os.path.exists(KEYS_PATH):
        sys.exit(
            f"ERRO: nao encontrei {KEYS_PATH}. Crie o arquivo keys.env "
            "com HUBSOFT_BASE_URL, HUBSOFT_CLIENT_ID, HUBSOFT_CLIENT_SECRET, "
            "HUBSOFT_USERNAME, HUBSOFT_PASSWORD."
        )
    keys = {}
    with open(KEYS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    required = [
        "HUBSOFT_BASE_URL",
        "HUBSOFT_CLIENT_ID",
        "HUBSOFT_CLIENT_SECRET",
        "HUBSOFT_USERNAME",
        "HUBSOFT_PASSWORD",
    ]
    faltando = [k for k in required if k not in keys or not keys[k]]
    if faltando:
        sys.exit(f"ERRO: keys.env esta sem: {', '.join(faltando)}")
    keys["HUBSOFT_BASE_URL"] = keys["HUBSOFT_BASE_URL"].rstrip("/")
    return keys


def http_request(url, method="GET", headers=None, data=None, timeout=30):
    headers = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        status = e.code
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"_raw_nao_json": raw}
    return status, parsed


def get_token(keys, force_refresh=False):
    if not force_refresh and os.path.exists(TOKEN_CACHE_PATH):
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("expires_at", 0) - TOKEN_SAFETY_MARGIN > time.time():
            return cache["token_type"], cache["access_token"]

    url = f"{keys['HUBSOFT_BASE_URL']}/oauth/token"
    payload = {
        "client_id": keys["HUBSOFT_CLIENT_ID"],
        "client_secret": keys["HUBSOFT_CLIENT_SECRET"],
        "username": keys["HUBSOFT_USERNAME"],
        "password": keys["HUBSOFT_PASSWORD"],
        "grant_type": "password",
    }
    status, resp = http_request(url, method="POST", data=payload)
    if status != 200 or "access_token" not in resp:
        sys.exit(f"ERRO ao autenticar (HTTP {status}): {json.dumps(resp, ensure_ascii=False)}")

    expires_in = resp.get("expires_in", 3600)
    cache = {
        "token_type": resp["token_type"],
        "access_token": resp["access_token"],
        "expires_at": time.time() + expires_in,
    }
    with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return cache["token_type"], cache["access_token"]


def api_call(keys, method, path, params=None, body=None):
    token_type, access_token = get_token(keys)
    url = f"{keys['HUBSOFT_BASE_URL']}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"{token_type} {access_token}"}
    status, resp = http_request(url, method=method, headers=headers, data=body)

    # token pode ter expirado antes da margem de seguranca -> tenta 1x renovando
    if status == 401:
        token_type, access_token = get_token(keys, force_refresh=True)
        headers = {"Authorization": f"{token_type} {access_token}"}
        status, resp = http_request(url, method=method, headers=headers, data=body)

    if status == 429:
        print(
            "AVISO: rate limit (429) atingido. Espere um pouco antes de tentar de novo.",
            file=sys.stderr,
        )
    return status, resp


def salvar_saida(comando, payload):
    os.makedirs(SAIDAS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(SAIDAS_DIR, f"{comando}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def cmd_auth(args, keys):
    token_type, access_token = get_token(keys, force_refresh=True)
    print(f"OK: autenticado. token_type={token_type} access_token={access_token[:12]}...")


def cmd_cliente(args, keys):
    params = {}
    if args.busca:
        params["busca"] = args.busca
    if args.termo:
        params["termo_busca"] = args.termo
    status, resp = api_call(keys, "GET", "/api/v1/integracao/cliente", params=params)
    path = salvar_saida("cliente", resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:3000])


def cmd_estoque_produto(args, keys):
    if args.id:
        status, resp = api_call(keys, "GET", f"/api/v1/integracao/estoque/produto/{args.id}")
    else:
        params = {"pagina": args.pagina, "itens_por_pagina": args.itens}
        status, resp = api_call(keys, "GET", "/api/v1/integracao/estoque/produto", params=params)
    path = salvar_saida("estoque_produto", resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:3000])


def cmd_estoque_local(args, keys):
    if args.id:
        status, resp = api_call(keys, "GET", f"/api/v1/integracao/estoque/local_estoque/{args.id}")
    else:
        params = {"pagina": args.pagina}
        status, resp = api_call(keys, "GET", "/api/v1/integracao/estoque/local_estoque", params=params)
    path = salvar_saida("estoque_local", resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:3000])


def cmd_estoque_movimento(args, keys):
    params = {"pagina": args.pagina}
    if args.itens:
        params["itens_por_pagina"] = args.itens
    if args.data_inicio:
        params["data_inicio"] = args.data_inicio
    if args.data_fim:
        params["data_fim"] = args.data_fim
    if args.tipo_data:
        params["tipo_data"] = args.tipo_data
    status, resp = api_call(keys, "GET", "/api/v1/integracao/estoque/movimento_estoque", params=params)
    path = salvar_saida("estoque_movimento", resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:3000])


def cmd_atendimento(args, keys):
    body = {
        "id_cliente_servico": args.id_cliente_servico,
        "nome": args.nome,
        "telefone": args.telefone,
        "descricao": args.descricao,
    }
    status, resp = api_call(keys, "POST", "/api/v1/integracao/atendimento", body=body)
    path = salvar_saida("atendimento", resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:5000])


def cmd_raw(args, keys):
    params = {}
    for p in args.params or []:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k] = v
    body = json.loads(args.body) if args.body else None
    status, resp = api_call(keys, args.method.upper(), args.path, params=params, body=body)
    nome = "raw_" + args.path.strip("/").replace("/", "_")
    path = salvar_saida(nome, resp)
    print(f"HTTP {status} -> {path}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:5000])


def main():
    parser = argparse.ArgumentParser(description="Conector HubSoft")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("auth", help="Testa/renova a autenticacao")

    p = sub.add_parser("cliente", help="Busca cliente")
    p.add_argument(
        "--busca",
        default="cpf_cnpj",
        help="campo de busca (confirmados: cpf_cnpj, codigo_cliente, nome_razaosocial)",
    )
    p.add_argument("--termo", required=True, help="valor a buscar")

    p = sub.add_parser(
        "atendimento",
        help="Abre um atendimento DE VERDADE (fila SAC) para um cliente_servico",
    )
    p.add_argument("--id-cliente-servico", type=int, required=True)
    p.add_argument("--nome", required=True)
    p.add_argument("--telefone", required=True)
    p.add_argument("--descricao", required=True)

    p = sub.add_parser("estoque-produto", help="Lista/consulta produtos de estoque")
    p.add_argument("--id", help="id_produto especifico")
    p.add_argument("--pagina", type=int, default=0)
    p.add_argument("--itens", type=int, default=100)

    p = sub.add_parser("estoque-local", help="Lista/consulta locais de estoque")
    p.add_argument("--id", help="id_local_estoque especifico")
    p.add_argument("--pagina", type=int, default=0)

    p = sub.add_parser("estoque-movimento", help="Lista movimentacoes de estoque")
    p.add_argument("--pagina", type=int, default=0)
    p.add_argument("--itens", type=int)
    p.add_argument("--data-inicio")
    p.add_argument("--data-fim")
    p.add_argument("--tipo-data")

    p = sub.add_parser("raw", help="Chamada generica a qualquer endpoint")
    p.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    p.add_argument("path", help="ex: /api/v1/integracao/cliente")
    p.add_argument("--params", nargs="*", help="pares chave=valor de query string")
    p.add_argument("--body", help="JSON literal para o corpo (POST/PUT)")

    args = parser.parse_args()
    keys = load_keys()

    comandos = {
        "auth": cmd_auth,
        "cliente": cmd_cliente,
        "estoque-produto": cmd_estoque_produto,
        "estoque-local": cmd_estoque_local,
        "estoque-movimento": cmd_estoque_movimento,
        "atendimento": cmd_atendimento,
        "raw": cmd_raw,
    }
    comandos[args.comando](args, keys)


if __name__ == "__main__":
    main()