#!/usr/bin/env python3
"""
Conector HubSoft (Amazonet) - autenticacao OAuth2 (password grant) + todas as
rotas conhecidas da API REST de integracao e da API GraphQL.

As credenciais NAO ficam neste arquivo: elas moram em keys.env, ao lado deste
script. Nunca comite ou compartilhe keys.env / token_cache.json / saidas/.

=============================================================================
INVENTARIO DE ROTAS CONHECIDAS (atualizado em 19/09/2026)
=============================================================================

--- REST (base: HUBSOFT_BASE_URL + /api/v1/integracao/...) ---

Autenticacao:
  POST /oauth/token   (grant_type=password; client_id, client_secret,
                        username, password) -> access_token, token_type,
                        expires_in

Cliente:
  GET  /cliente?busca=<campo>&termo_busca=<valor>
       --busca confirmados: cpf_cnpj, codigo_cliente, nome_razaosocial
       (SEM esses dois parametros -> erro "Favor preencher o atributo
       (busca)"; NAO existe listagem em massa nem filtro por status por essa
       rota - so busca pontual por um valor exato. Para listagem em massa
       usar a rota GraphQL "clientes")
       NAO existe GET /cliente/{id} direto (404) - so via busca=.

Atendimento:
  POST /atendimento   body: id_cliente_servico, nome, telefone, descricao
       -> cria atendimento DE VERDADE na fila SAC (nao e sandbox).
       Campos obrigatorios descobertos via probing dos erros de validacao.
  GET  /atendimento (index/listagem) -> DESABILITADO
       ("Metodo/endpoint nao disponivel"). Use a rota GraphQL "atendimentos"
       para listar em massa.

Estoque:
  GET  /estoque/produto?pagina=N&itens_por_pagina=N   (+ /estoque/produto/:id)
  GET  /estoque/local_estoque?pagina=N                (+ /estoque/local_estoque/:id)
  GET  /estoque/movimento_estoque?pagina=N&data_inicio=&data_fim=&tipo_data=
       (+ /estoque/movimento_estoque/:id)
  POST /estoque/movimento_estoque    (criar movimento - nao testado a fundo)
  POST /estoque/movimento_estoque/transferencia
  DELETE /estoque/movimento_estoque/:id
  POST /estoque/produto  | PUT /estoque/produto/:id  | DELETE /estoque/produto/:id
  GET/PUT /estoque/produto_item?id_produto=&pagina=   (+ /estoque/produto_item/:id)
  (fonte: wiki.hubsoft.com.br/pt-br/modulos/estoque/api - nao testamos os
  metodos de escrita do estoque, so os GETs de listagem)

Ordem de servico:
  GET  /ordem_servico          (index) -> DESABILITADO ("Metodo index nao
       disponivel"), testado com e sem parametros (id_cliente, codigo_cliente,
       status, id_cliente_servico) - sempre desabilitado.
  GET  /ordem_servico/{qualquer coisa} -> tratado como :id, "Metodo show nao
       disponivel" (tambem desabilitado).
  POST /ordem_servico -> "Metodo store nao disponivel" (desabilitado).
  ==> A API REST NAO da acesso a ordens de servico de jeito nenhum. Use a
      rota GraphQL "ordensServico" / "ordemServicoById" / "ordemServicoByNumero".

Rotas REST tentadas e que NAO existem (404, confirmado):
  /cliente_servico, /cliente/servico, /os, /atendimento_os, /servico,
  /relatorio, /contrato

Rate limit (documentado em docs.hubsoft.com.br):
  - /oauth/token: 30 requisicoes/min (burst 20)
  - demais endpoints REST: 20 requisicoes/seg (burst 200)
  - estoura -> HTTP 429 com retry_after

Paginacao REST: comeca em pagina=0.


--- GraphQL (POST HUBSOFT_BASE_URL + /graphql/v1) ---

Autenticacao: mesmo Bearer token OAuth do REST, MAS o usuario precisa ter a
permissao "API GraphQL" habilitada no HubSoft alem da permissao de API REST
(se nao tiver, a query falha por permissao mesmo com token valido).

Paginacao: argumentos (first, page, orderBy) em cada query de lista.
  - "first" MAXIMO = 1000 (erro claro se pedir mais: "Maximum number of 1000
    requested items exceeded").
  - ARMADILHA: paginatorInfo.lastPage so reflete o "first" USADO NAQUELA
    MESMA consulta. Uma consulta com first:1 sempre devolve lastPage == total
    (porque cada "pagina" tem 1 item). NUNCA use o lastPage de uma consulta
    com first diferente do que voce vai usar para paginar de verdade - calcule
    voce mesmo: paginas = ceil(total / first_que_vou_usar).
  - Nao existe argumento de filtro (where/status/data) nas queries de lista
    root (clientes, servicos, ordensServico, atendimentos, faturas,
    cobrancas, ...) alem de orderBy/first/page - so da pra filtrar client-side
    depois de paginar tudo, ou usar as variantes "...ByData..." (data_cadastro,
    data_vencimento, data_pagamento, data_emissao) que aceitam range de data
    (nao confirmamos os nomes exatos dos argumentos de data, testar com
    introspeccao: `python hubsoft.py gql-schema --field ordensServicoByDataCadastro`).
  - id_cliente_servico volta como STRING (escalar ID) em "clientes.data[].
    servicos[].id_cliente_servico", mas como INT em "ordensServico.data[].
    id_cliente_servico". Normalize com str(...) antes de comparar/cruzar.

Queries root confirmadas (introspeccao em 18-19/09/2026):
  Por ID / chave unica:
    atendimentoById, atendimentoByProtocolo, ordemServicoById,
    ordemServicoByNumero, clienteById, clienteByCodigo, clienteByCpfCnpj,
    clienteByNomeRazaoSocial, prospectoById, faturaById, cobrancaById,
    notaFiscalById, nfseById, nfeById, popById, cpeById, cpeByPhyAddr,
    equipamentoConexaoById
  Listas paginadas (first/page/orderBy):
    clientes, servicos (CATALOGO de planos/produtos - id_servico - NAO e a
      assinatura do cliente), atendimentos, atendimentosByDataCadastro,
      ordensServico, ordensServicoByDataCadastro, prospectos,
      prospectoByDataCadastro, faturas, faturasByDataVencimento,
      faturasByDataPagamento, cobrancas, cobrancasByDataVencimento,
      cobrancasByDataPagamento, notasFiscais, notasFiscaisByDataEmissao,
      nfses, nfsesByDataEmissao, nfes, nfesByDataEmissao, pops, cpes,
      equipamentosConexao, logins, statusConexaoRadius

Types principais (campos confirmados via __type introspection):
  Cliente: id_cliente, codigo_cliente, nome_razaosocial, cpf_cnpj, rj,
    rj_emissor, inscricao_estadual, inscricao_municipal, tipo_pessoa,
    data_cadastro, data_nascimento, telefone_primario/secundario/terciario,
    email_principal/secundario, servicos (lista de ClienteServico, SEM
    argumento de filtro), prospecto, enderecos
  ClienteServico: id_cliente_servico, id_cliente, numero_plano, valor,
    data_cadastro, data_habilitacao, data_cancelamento, vendedor, servico
    (-> Servico), servico_status (-> ServicoStatus), cliente_servico_autenticacao,
    cliente (-> Cliente), enderecos, endereco_instalacao, endereco_cobranca
    !! NAO tem campo "data_ultima_suspensao" nem relacao com contrato
    (cliente_servico_contrato) exposta aqui - so existe no banco/Metabase.
  ServicoStatus: id_servico_status, descricao (ex: "Aguardando Assinatura de
    Contrato", "Aguardando Agendamento", "Suspenso por Debito", "Servico
    Habilitado"), prefixo
  Servico (catalogo de planos): id_servico, descricao, valor,
    servico_navegacao, ativo
  OrdemServico: id_ordem_servico, id_atendimento, id_cliente_servico,
    id_prospecto, id_pop, id_tipo_ordem_servico, id_usuario_abertura,
    id_usuario_fechamento, descricao_abertura, descricao_servico,
    descricao_fechamento, gera_custo, valor_custo, numero_ordem_servico,
    data_cadastro, status, status_fechamento, data_inicio_programado,
    data_termino_programado, data_inicio_executado, data_termino_executado,
    atendimento (-> Atendimento), cliente_servico (-> ClienteServico),
    tipo_ordem_servico, prospecto, pop, mensagens
    status observados na pratica: finalizado, aguardando_agendamento, pendente
    status_fechamento observados na pratica: concluido, sem_conclusao
    (NAO existe "cancelamento"/"inviabilidade" como valor proprio desse
    campo - se existir esse detalhe, provavelmente esta em
    "descricao_fechamento" como texto livre, nao testamos ainda)

Uso:
    python hubsoft.py auth
    python hubsoft.py cliente --busca codigo_cliente --termo 59229
    python hubsoft.py atendimento --id-cliente-servico 262252 --nome "Fulano" --telefone "92999999999" --descricao "..."
    python hubsoft.py estoque-produto [--id 123] [--pagina 0] [--itens 100]
    python hubsoft.py estoque-local [--id 123] [--pagina 0]
    python hubsoft.py estoque-movimento [--pagina 0] [--data-inicio 2026-09-01] [--data-fim 2026-09-17] [--tipo-data 1]
    python hubsoft.py gql-schema                       # lista as queries root
    python hubsoft.py gql-schema --tipo ClienteServico  # lista campos de um type
    python hubsoft.py gql-list clientes --fields "codigo_cliente nome_razaosocial" --max-paginas 5
    python hubsoft.py gql-list ordensServico --fields "id_cliente_servico status status_fechamento"
    python hubsoft.py gql-by-id ordemServico 12345 --fields "status status_fechamento descricao_fechamento"
    python hubsoft.py gql --query '{ clientes(first:5){ data{ codigo_cliente } } }'
    python hubsoft.py raw GET /api/v1/integracao/cliente --params busca=cpf_cnpj termo_busca=12345678900
"""
import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
_KEYS_CANDIDATES = [os.path.join(HERE, ".env"), os.path.join(HERE, "keys.env")]
KEYS_PATH = next((p for p in _KEYS_CANDIDATES if os.path.exists(p)), _KEYS_CANDIDATES[0])
TOKEN_CACHE_PATH = os.path.join(HERE, "token_cache.json")
SAIDAS_DIR = os.path.join(HERE, "saidas")

TOKEN_SAFETY_MARGIN = 60  # segundos de margem antes do token expirar
GQL_MAX_FIRST = 1000
GQL_DEFAULT_WORKERS = 8

# rotas REST confirmadas como desabilitadas - documentado aqui pra nao
# perder tempo tentando de novo
REST_DESABILITADAS = {
    "/api/v1/integracao/ordem_servico": "index/show/store desabilitados - use GraphQL ordensServico",
    "/api/v1/integracao/atendimento (GET index)": "desabilitado - use GraphQL atendimentos",
}


# ---------------------------------------------------------------------------
# infra basica: keys, http, token, chamadas REST e GraphQL
# ---------------------------------------------------------------------------

def load_keys():
    if not os.path.exists(KEYS_PATH):
        sys.exit(
            f"ERRO: nao encontrei {KEYS_PATH}. Crie o arquivo .env (ou keys.env) com "
            "HUBSOFT_BASE_URL, HUBSOFT_CLIENT_ID, HUBSOFT_CLIENT_SECRET, "
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
    obrigatorias = [
        "HUBSOFT_BASE_URL",
        "HUBSOFT_CLIENT_ID",
        "HUBSOFT_CLIENT_SECRET",
        "HUBSOFT_USERNAME",
        "HUBSOFT_PASSWORD",
    ]
    faltando = [k for k in obrigatorias if k not in keys or not keys[k]]
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


def api_call(keys, method, path, params=None, body=None, tentativas=3):
    """Chamada REST autenticada, com 1 retentativa de refresh de token em 401
    e retentativas simples em erro de rede/proxy (comum em varreduras longas)."""
    url = f"{keys['HUBSOFT_BASE_URL']}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    for tentativa in range(tentativas):
        token_type, access_token = get_token(keys)
        headers = {"Authorization": f"{token_type} {access_token}"}
        try:
            status, resp = http_request(url, method=method, headers=headers, data=body)
        except Exception as e:
            if tentativa == tentativas - 1:
                raise
            time.sleep(1.5 * (tentativa + 1))
            continue

        if status == 401:
            get_token(keys, force_refresh=True)
            continue
        if status == 429:
            print("AVISO: rate limit (429). Aguardando antes de tentar de novo.", file=sys.stderr)
            time.sleep(3 * (tentativa + 1))
            continue
        return status, resp

    return status, resp


def gql_call(keys, query, variables=None, tentativas=4):
    """Chamada POST /graphql/v1 com retry em erro de rede/429."""
    body = {"query": query}
    if variables:
        body["variables"] = variables
    for tentativa in range(tentativas):
        status, resp = api_call(keys, "POST", "/graphql/v1", body=body)
        if status == 200 and "errors" not in resp:
            return resp["data"]
        if status == 429 or (isinstance(resp, dict) and "errors" in resp and tentativa < tentativas - 1):
            time.sleep(2 * (tentativa + 1))
            continue
        if "errors" in resp:
            raise RuntimeError(json.dumps(resp["errors"], ensure_ascii=False))
        raise RuntimeError(f"HTTP {status}: {json.dumps(resp, ensure_ascii=False)}")
    raise RuntimeError("gql_call falhou apos varias tentativas")


def salvar_saida(comando, payload):
    os.makedirs(SAIDAS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(SAIDAS_DIR, f"{comando}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def normaliza(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


# ---------------------------------------------------------------------------
# comandos REST
# ---------------------------------------------------------------------------

def cmd_auth(args, keys):
    token_type, access_token = get_token(keys, force_refresh=True)
    print(f"OK: autenticado. token_type={token_type} access_token={access_token[:12]}...")


def cmd_cliente(args, keys):
    params = {"busca": args.busca, "termo_busca": args.termo}
    status, resp = api_call(keys, "GET", "/api/v1/integracao/cliente", params=params)
    path = salvar_saida("cliente", resp)
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


# ---------------------------------------------------------------------------
# comandos GraphQL
# ---------------------------------------------------------------------------

def cmd_gql(args, keys):
    query = args.query
    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as f:
            query = f.read()
    data = gql_call(keys, query)
    path = salvar_saida("gql", data)
    print(f"OK -> {path}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:6000])


def cmd_gql_schema(args, keys):
    if args.tipo:
        query = (
            "{ __type(name: \"%s\") { name kind fields { name args { name } "
            "type { name kind ofType { name kind ofType { name kind } } } } } }"
        ) % args.tipo
        data = gql_call(keys, query)
        t = data["__type"]
        if not t:
            print(f"Tipo '{args.tipo}' nao encontrado.")
            return
        print(f"=== {t['name']} ({t['kind']}) ===")
        for f in t.get("fields") or []:
            argstr = ", ".join(a["name"] for a in f["args"]) if f["args"] else ""
            print(f"  {f['name']}({argstr})" if argstr else f"  {f['name']}")
    else:
        query = "{ __schema { queryType { fields { name args { name } } } } }"
        data = gql_call(keys, query)
        for f in data["__schema"]["queryType"]["fields"]:
            argstr = ", ".join(a["name"] for a in f["args"]) if f["args"] else ""
            print(f"{f['name']}({argstr})" if argstr else f["name"])


def _gql_paginated_total(keys, field, first):
    query = "{ %s(first: %d) { paginatorInfo { total } } }" % (field, first)
    data = gql_call(keys, query)
    return data[field]["paginatorInfo"]["total"]


def _fetch_gql_page(keys, field, fields_selection, first, page, order_by=None):
    ob = f", orderBy: {order_by}" if order_by else ""
    query = "{ %s(first: %d, page: %d%s) { data { %s } } }" % (
        field,
        first,
        page,
        ob,
        fields_selection,
    )
    data = gql_call(keys, query)
    return data[field]["data"]


def cmd_gql_list(args, keys):
    """Pagina uma query GraphQL de lista root (clientes, ordensServico,
    atendimentos, faturas, cobrancas, servicos, prospectos, ...) por
    completo, em paralelo, e salva tudo em um unico JSON.

    IMPORTANTE: sempre calcula o numero de paginas como
    ceil(total / first) usando o PROPRIO "first" que vai ser usado -
    nunca confie no paginatorInfo.lastPage de uma consulta menor."""
    first = min(args.first, GQL_MAX_FIRST)
    total = _gql_paginated_total(keys, args.field, first)
    paginas = (total + first - 1) // first
    if args.max_paginas:
        paginas = min(paginas, args.max_paginas)
    print(f"[gql-list] {args.field}: total={total} paginas_a_buscar={paginas} first={first}")

    resultados = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(_fetch_gql_page, keys, args.field, args.fields, first, p, args.order_by): p
            for p in range(1, paginas + 1)
        }
        done = 0
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                resultados.extend(fut.result())
            except Exception as e:
                print(f"[gql-list] ERRO pagina {p}: {e}", file=sys.stderr)
            done += 1
            if done % 20 == 0 or done == paginas:
                print(f"[gql-list] {done}/{paginas} paginas ({time.time()-t0:.0f}s) - {len(resultados)} itens")

    path = salvar_saida(f"gql_list_{args.field}", resultados)
    print(f"[gql-list] concluido: {len(resultados)} itens -> {path}")


def cmd_gql_by_id(args, keys):
    """Consulta pontual por ID/protocolo/numero (atendimentoById,
    ordemServicoById, clienteById, clienteByCodigo, clienteByCpfCnpj,
    clienteByNomeRazaoSocial, faturaById, cobrancaById, ...)."""
    query = '{ %s(id: "%s") { %s } }' % (args.query_field, args.valor, args.fields)
    data = gql_call(keys, query)
    path = salvar_saida(f"gql_{args.query_field}", data)
    print(f"OK -> {path}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Conector HubSoft (REST + GraphQL)")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("auth", help="Testa/renova a autenticacao")

    p = sub.add_parser("cliente", help="Busca pontual de cliente (REST)")
    p.add_argument("--busca", default="cpf_cnpj", help="cpf_cnpj | codigo_cliente | nome_razaosocial")
    p.add_argument("--termo", required=True)

    p = sub.add_parser("atendimento", help="Abre atendimento DE VERDADE (fila SAC) - REST")
    p.add_argument("--id-cliente-servico", type=int, required=True)
    p.add_argument("--nome", required=True)
    p.add_argument("--telefone", required=True)
    p.add_argument("--descricao", required=True)

    p = sub.add_parser("estoque-produto", help="Lista/consulta produtos de estoque (REST)")
    p.add_argument("--id")
    p.add_argument("--pagina", type=int, default=0)
    p.add_argument("--itens", type=int, default=100)

    p = sub.add_parser("estoque-local", help="Lista/consulta locais de estoque (REST)")
    p.add_argument("--id")
    p.add_argument("--pagina", type=int, default=0)

    p = sub.add_parser("estoque-movimento", help="Lista movimentacoes de estoque (REST)")
    p.add_argument("--pagina", type=int, default=0)
    p.add_argument("--itens", type=int)
    p.add_argument("--data-inicio")
    p.add_argument("--data-fim")
    p.add_argument("--tipo-data")

    p = sub.add_parser("raw", help="Chamada REST generica a qualquer endpoint")
    p.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    p.add_argument("path", help="ex: /api/v1/integracao/cliente")
    p.add_argument("--params", nargs="*")
    p.add_argument("--body", help="JSON literal para o corpo")

    p = sub.add_parser("gql", help="Query/mutation GraphQL arbitraria")
    p.add_argument("--query", help="query GraphQL inline")
    p.add_argument("--query-file", help="arquivo .graphql/.txt com a query")

    p = sub.add_parser("gql-schema", help="Introspeccao: lista queries root ou campos de um type")
    p.add_argument("--tipo", help="nome de um type (ex: ClienteServico, OrdemServico, Cliente, Servico, ServicoStatus)")

    p = sub.add_parser(
        "gql-list",
        help="Pagina uma query GraphQL de lista root por completo (ex: clientes, ordensServico, faturas)",
    )
    p.add_argument("field", help="ex: clientes | ordensServico | atendimentos | faturas | cobrancas | servicos | prospectos")
    p.add_argument("--fields", required=True, help='campos a selecionar dentro de "data", ex: "codigo_cliente nome_razaosocial"')
    p.add_argument("--first", type=int, default=GQL_MAX_FIRST, help=f"itens por pagina (maximo {GQL_MAX_FIRST})")
    p.add_argument("--max-paginas", type=int, help="limite de paginas (teste rapido)")
    p.add_argument("--workers", type=int, default=GQL_DEFAULT_WORKERS)
    p.add_argument("--order-by", help='ex: "[{column: DATA_CADASTRO, order: DESC}]" (sintaxe exata: confirmar com gql-schema)')

    p = sub.add_parser(
        "gql-by-id",
        help="Consulta pontual GraphQL por ID/protocolo/numero/codigo",
    )
    p.add_argument("query_field", help="ex: atendimentoById | ordemServicoById | clienteByCodigo | clienteByCpfCnpj | faturaById")
    p.add_argument("valor", help="o id/codigo/protocolo a buscar")
    p.add_argument("--fields", required=True)

    args = parser.parse_args()
    keys = load_keys()

    comandos = {
        "auth": cmd_auth,
        "cliente": cmd_cliente,
        "atendimento": cmd_atendimento,
        "estoque-produto": cmd_estoque_produto,
        "estoque-local": cmd_estoque_local,
        "estoque-movimento": cmd_estoque_movimento,
        "raw": cmd_raw,
        "gql": cmd_gql,
        "gql-schema": cmd_gql_schema,
        "gql-list": cmd_gql_list,
        "gql-by-id": cmd_gql_by_id,
    }
    comandos[args.comando](args, keys)


if __name__ == "__main__":
    main()