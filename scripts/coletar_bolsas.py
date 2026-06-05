"""Constrói o dataset público de bolsas (app/dados/bolsas_publicas.json).

Combina três fontes:
  1. Roster oficial (relacao-bolsistas_padronizado.csv) — quem são os bolsistas
     (filtra Ensino Superior + Especialização; o Ensino Médio não tem empenho
     individual no portal).
  2. CSVs de Movimentação Diária (movimentacao-diaria/*.csv) — valores, datas e
     status agregados por empenho (via app.csv_loader).
  3. Página de detalhe do portal (scraping Playwright) — para cada empenho do aluno,
     confirma que é bolsa (Função=Educação + Ação~"BOLSA DE ESTUDO") e extrai o
     MÊS de referência da mensalidade (do texto "Descrição do Empenho").

O scraping é cacheado por empenho em data/cache/detalhe/, então reexecuções só
buscam o que falta. Use --limite para validar com poucos alunos.

Uso:
    python scripts/coletar_bolsas.py --limite 3      # validação
    python scripts/coletar_bolsas.py                 # roster inteiro
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.csv_loader import _df_completo, _norm, _tokens, buscar  # noqa: E402
ROSTER = BASE / "relacao-bolsistas_padronizado.csv"
SAIDA = BASE / "app" / "dados" / "bolsas_publicas.json"
CACHE = BASE / "data" / "cache" / "detalhe"
HOST = "https://webapp1-quissama.cidade360.cloud"
URL = HOST + "/pronimtb/index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"
NIVEIS_INCLUSOS = ("Superior", "Especialização")

MESES = {m: f"{i:02d}" for i, m in enumerate(
    ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO",
     "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"], start=1)}
MESES_RE = "|".join(MESES)


def _data_key(d: str | None) -> str:
    """'DD/MM/AAAA' -> 'AAAA-MM-DD' (ordenável); vazio/None ('0000-...') vai para o fim."""
    p = (d or "").split("/")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else "0000-00-00"


def _num_empenho(m: dict) -> int:
    return int(re.sub(r"\D", "", m.get("empenho") or "") or 0)


def ordenar_mensalidades(mens: list[dict]) -> list[dict]:
    """Mais novo -> mais antigo pela DATA DO EMPENHO, desempatando pelo número do
    processo (maior em cima; o de número menor fica abaixo). Ordenar pela data do
    processo (e não pelo mês de referência) expõe o descompasso quando a prefeitura
    empenha uma mensalidade fora do mês a que ela se refere."""
    mens.sort(key=lambda m: (_data_key(m.get("data_empenho")), _num_empenho(m)), reverse=True)
    return mens


def carregar_roster() -> list[dict]:
    alunos = []
    with open(ROSTER, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nivel = (row.get("Nível") or "").strip()
            if not any(nivel.startswith(n) for n in NIVEIS_INCLUSOS):
                continue
            nome = (row.get("Aluno") or "").strip()
            if not nome:
                continue
            alunos.append({
                "nome_roster": nome,
                "nivel": nivel,
                "curso": (row.get("Curso") or "").strip(),
                "instituicao": (row.get("Instituição") or "").strip(),
                "percentual": (row.get("Percentual") or "").strip(),
                "valor_mensal": (row.get("Valor") or "").strip(),
            })
    return alunos


def mapear_canonico(alunos: list[dict]) -> None:
    """Anota cada aluno com o nome canônico do portal (in-place)."""
    df = _df_completo()
    canon = {}  # _credor normalizado -> nome original
    for _, r in df[["credor", "_credor"]].drop_duplicates().iterrows():
        canon[r["_credor"]] = r["credor"]
    cred_tokens = [(c, set(c.split())) for c in canon]

    for a in alunos:
        toks = set(_tokens(a["nome_roster"]))
        alvo = next((c for c, ts in cred_tokens if toks and toks <= ts), None)
        if not alvo:  # fallback fuzzy (corrige typos do roster, ex.: "Sllva")
            alvo_norm = _norm(a["nome_roster"])
            melhor, score = None, 0.0
            for c in canon:
                s = difflib.SequenceMatcher(None, alvo_norm, c).ratio()
                if s > score:
                    melhor, score = c, s
            alvo = melhor if score >= 0.88 else None
        a["nome_canonico"] = canon.get(alvo) if alvo else None


# ---------------------------------------------------------------- scraping

def buscar_grade(pg, nome: str, ano: str) -> dict[str, str]:
    """Retorna {numero_empenho: url_detalhe} dos empenhos do credor no ano."""
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.select_option("select[name=cmbAno]", ano)
    # sem o range completo, o portal herda a janela padrão de 1 mês e perde mensalidades
    pg.fill("input[name=txtDataInicial]", f"01/01/{ano}")
    pg.fill("input[name=txtDataFinal]", f"31/12/{ano}")
    pg.fill("input[name=txtNomeFornecedor]", nome)
    pg.click("input[value='Gerar']")
    # espera a tabela de resultados materializar (em vez de timeout fixo)
    try:
        pg.wait_for_function(
            """() => [...document.querySelectorAll('table')].some(t =>
                 [...t.querySelectorAll('th')].some(h=>/Número do Empenho/i.test(h.innerText))
                 && [...t.querySelectorAll('tr')].some(tr=>tr.querySelectorAll('td').length>=10))""",
            timeout=20000)
    except Exception:
        pass
    pg.wait_for_timeout(1000)
    linhas = pg.evaluate("""() => {
      const t=[...document.querySelectorAll('table')]
        .find(e=>[...e.querySelectorAll('th')].some(h=>/Número do Empenho/i.test(h.innerText)));
      if(!t) return [];
      return [...t.querySelectorAll('tr')]
        .filter(tr=>tr.querySelectorAll('td').length>=10)
        .map(tr=>{ const a=tr.querySelector('a'); return a?a.getAttribute('href'):null; })
        .filter(Boolean);
    }""")
    out = {}
    for href in linhas:
        m = re.search(r"montaURLDetalhamentoItem\('([^']+)'\)", href)
        if not m:
            continue
        path = m.group(1)
        emp = re.search(r"empenho=(\d+)", path)
        if emp:
            out[emp.group(1).lstrip("0") or "0"] = HOST + path
    return out


def extrair_meses(texto: str) -> list[str]:
    """Lista de meses 'AAAA-MM' que o empenho cobre (1 = mensalidade única; vários =
    intervalo/lista/acordo; [] = não identificável). Tolera variações de digitação da
    fonte e ignora a data da LEI (ex.: 'MAIO DE 2021') ancorando no trecho a partir
    de 'MENSALIDADE'."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()
    t = re.sub(rf"\bDE({MESES_RE})", r"DE \1", t)                  # DEMARCO -> DE MARCO
    t = re.sub(rf"\b(MES(?:ES)?)\s+({MESES_RE})", r"\1 DE \2", t)  # MES NOVEMBRO -> MES DE NOVEMBRO
    t = re.sub(r"\bDE\s+DE\b", "DE", t)                            # DE DE -> DE
    i = t.rfind("MENSALIDADE")
    if i < 0:
        return []
    seg = t[i:]
    meses, prev_end = [], 0
    for am in re.finditer(r"\b(20\d{2})\b", seg):
        ano, chunk = am.group(1), seg[prev_end:am.start()]
        prev_end = am.end()
        nums, prev, rng = [], None, False
        for tok in re.findall(rf"{MESES_RE}|\bA\b|\bE\b", chunk):
            if tok == "A":
                rng = True
            elif tok == "E":
                rng = False
            else:
                cur = int(MESES[tok])
                nums += list(range(prev + 1, cur + 1)) if (rng and prev) else [cur]
                prev, rng = cur, False
        meses += [f"{ano}-{m:02d}" for m in nums]
    return sorted(set(meses))


def parse_detalhe(txt: str) -> dict:
    """Extrai classificação, descrição e meses de referência do texto do detalhe.
    Trabalha sobre uma versão sem acentos (a fonte varia: MÊS/MES, MARÇO/MARCO)."""
    norm = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().upper()
    def capn(pat):
        m = re.search(pat, norm)
        return m.group(1).strip() if m else ""
    funcao = capn(r"FUNCAO:\s*\d*\s*-?\s*([^\t\n]+)")
    acao = capn(r"ACAO DE GOVERNO:\s*\d*\s*-?\s*([^\t\n]+)")
    # descrição (texto original, com acentos): captura todos os itens da tabela até os Totais
    md = re.search(r"Descri[çc][ãa]o do Empenho.*?Total\s*\n(.+?)\nTotais", txt, re.DOTALL | re.IGNORECASE)
    if md:
        lines = md.group(1).strip().split("\n")
        descriptions = []
        for line in lines:
            parts = line.split("\t")
            if parts:
                desc_text = parts[0].strip()
                if desc_text:
                    descriptions.append(desc_text)
        desc = " | ".join(descriptions)
    else:
        # fallback caso a tabela tenha formato diferente
        md_fallback = re.search(r"Descri[çc][ãa]o do Empenho.*?Total\s*\n(.+?)\t", txt, re.DOTALL | re.IGNORECASE)
        desc = md_fallback.group(1).strip() if md_fallback else ""

    meses = extrair_meses(txt)
    # Se a descrição for genérica ("RESTOS A PAGAR"), tenta extrair do histórico de pagamentos/liquidações
    if desc.upper() == "RESTOS A PAGAR":
        historia = []
        for m_hist in re.finditer(r"(?:VALOR REF\.|PAGTO\.|LIQUIDACAO)[^\t\n]+", txt, re.IGNORECASE):
            h_txt = m_hist.group(0).strip()
            if h_txt and h_txt not in historia:
                historia.append(h_txt)
        if historia:
            desc = " | ".join(historia)

    meses = extrair_meses(txt)
    mes = meses[0] if len(meses) == 1 else ""
    tipo, parcela = _classificar(norm, len(meses))
    return {"funcao": funcao, "acao": acao, "descricao": desc,
            "mes_referencia": mes, "meses": meses,
            "tipo": tipo, "parcela": parcela, "raw": txt}


def _classificar(norm: str, n_meses: int) -> tuple[str, str | None]:
    """Classifica o empenho e extrai o número da parcela (se acordo).
    Retorna (tipo, parcela) onde tipo ∈ {mensalidade, conjunto, acordo}
    e parcela ∈ {None, 'única', '1', '2', ...}."""
    # "ACORDO" só é acordo de pagamento quando acompanhado de traço/dígito/PARCELA.
    # "DE ACORDO COM A LEI" é linguagem legal e NÃO deve ser detectado.
    is_acordo = bool(re.search(r"ACORDO\s*[-]?\s*(?:PARCELA|\d)", norm))
    if is_acordo:
        if re.search(r"PARCELA\s+UNICA", norm):
            return "acordo", "única"
        # "Xª A Yª PARCELAS" ou "Xª E Yª PARCELAS"
        mr = re.search(r"(\d+)\s*[ºaA]?\s*(?:A|E|-)\s*(\d+)\s*[ºaA]?\s*PARCELAS?", norm)
        if mr:
            return "acordo", f"{mr.group(1)} a {mr.group(2)}"
        # "Xª, Yª E Zª PARCELAS"
        mr3 = re.search(r"(\d+)\s*[ºaA]?\s*,\s*(?:\d+\s*[ºaA]?\s*,\s*)*\d+\s*[ºaA]?\s*E\s*(\d+)\s*[ºaA]?\s*PARCELAS?", norm)
        if mr3:
            return "acordo", f"{mr3.group(1)} a {mr3.group(2)}"
        # "NNª PARCELA" / "NNa PARCELA" (ª → a após normalização ASCII) / "NN PARCELA"
        m = re.search(r"(\d+)\s*[ºaA]?\s*PARCELA", norm)
        if m:
            return "acordo", m.group(1)
        return "acordo", None
    if n_meses > 1:
        return "conjunto", None
    return "mensalidade", None


def abrir_detalhe(pg, url: str) -> dict:
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    return parse_detalhe(pg.evaluate("() => document.body.innerText"))


def eh_bolsa(det: dict) -> bool:
    # Função sempre Educação; "bolsa de estudo" pode estar na Ação (Superior) ou só
    # na descrição (Especialização usa a Ação "Capacitação e Qualificação").
    blob = (det["acao"] + " " + (det.get("descricao") or "")).lower()
    if "educa" in det["funcao"].lower() and "bolsa" in blob and "estudo" in blob:
        return True
        
    # Se for Restos a Pagar (função/ação vazias), valida pelo texto bruto (raw)
    raw_lower = det.get("raw", "").lower()
    if "educa" in raw_lower and "bolsa" in raw_lower and "estudo" in raw_lower:
        return True
        
    # Fallback para Restos a Pagar sem histórico detalhado: aceita se for "restos" e pertencer à Educação,
    # pois o credor já é um aluno filtrado pelo roster oficial
    if "restos" in det.get("descricao", "").lower() and "educa" in raw_lower:
        return True
        
    return False


def detalhe_cacheado(pg, numero: str, ano: str, url: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / f"{ano}-{numero}.json"
    if cf.exists():
        det = json.loads(cf.read_text(encoding="utf-8"))
        if det.get("raw") is not None:
            # re-aplica o parser atual ao texto bruto (correções valem sem re-busca)
            novo = parse_detalhe(det["raw"])
            if novo != det:
                cf.write_text(json.dumps(novo, ensure_ascii=False), encoding="utf-8")
            return novo
        if det.get("mes_referencia"):  # parse antigo sem raw — deriva os meses do mês único
            det.setdefault("meses", [det["mes_referencia"]])
            return det
    det = abrir_detalhe(pg, url)
    cf.write_text(json.dumps(det, ensure_ascii=False), encoding="utf-8")
    return det


# ---------------------------------------------------------------- orquestração

FONTE_NOME = "Portal da Transparência de Quissamã"


def _carregar_existente() -> dict:
    """Dataset já gravado, indexado por nome (para merge/resumo incremental)."""
    if SAIDA.exists():
        try:
            d = json.loads(SAIDA.read_text(encoding="utf-8"))
            return {a["nome"]: a for a in d.get("alunos", [])}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _salvar(por_nome: dict) -> None:
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    alunos = sorted(por_nome.values(), key=lambda a: a["nome"])
    SAIDA.write_text(json.dumps({"fonte": FONTE_NOME, "url": URL, "alunos": alunos},
                                ensure_ascii=False, indent=2), encoding="utf-8")


def coletar_aluno(pg, a: dict) -> dict:
    """Raspa as mensalidades de bolsa de um aluno (nome canônico já resolvido)."""
    nome = a["nome_canonico"]
    # valores/datas/status já agregados pelo csv_loader; também é a lista de
    # empenhos ESPERADOS por ano (verificação anti-flakiness)
    base = buscar(nome)
    por_empenho, esperado_por_ano = {}, defaultdict(set)
    for r in base["registros"]:
        num = r["empenho"].lstrip("0") or "0"
        por_empenho[num] = r
        esperado_por_ano[r["ano"]].add(num)

    mensalidades = []
    for ano, esperados in sorted(esperado_por_ano.items()):
        grade = {}
        for tent in range(4):  # re-tenta (flakiness/rede) até cobrir o CSV
            try:
                grade = buscar_grade(pg, nome, ano)
                if esperados <= set(grade):
                    break
            except Exception as e:  # noqa: BLE001
                print(f"   .. rede {nome} {ano} (tent {tent+1}): {repr(e)[:70]}")
            time.sleep(3)
        faltando = esperados - set(grade)
        if faltando:
            print(f"   !! {nome} {ano}: sem detalhe p/ {sorted(faltando)}")
        for numero in sorted(esperados & set(grade)):
            try:
                det = detalhe_cacheado(pg, numero, ano, grade[numero])
            except Exception as e:  # noqa: BLE001
                print(f"   .. detalhe {numero} falhou: {repr(e)[:70]}")
                continue
            if not eh_bolsa(det):
                continue
            reg = por_empenho.get(numero, {})
            # Ignora empenhos que foram totalmente anulados/cancelados (tudo zerado)
            if reg.get("empenhado", 0.0) <= 0.0 and reg.get("liquidado", 0.0) <= 0.0 and reg.get("pago", 0.0) <= 0.0:
                continue
            mensalidades.append({
                "empenho": numero,
                "ano": ano,
                "mes_referencia": det["mes_referencia"],
                "meses": det.get("meses", []),
                "tipo": det.get("tipo", "mensalidade"),
                "parcela": det.get("parcela"),
                "empenhado": reg.get("empenhado", 0.0),
                "liquidado": reg.get("liquidado", 0.0),
                "pago": reg.get("pago", 0.0),
                "a_pagar": reg.get("a_pagar", 0.0),
                "data_empenho": reg.get("data_empenho"),
                "data_liquidacao": reg.get("data_liquidacao"),
                "data_pagamento": reg.get("data_pagamento"),
                "descricao": det["descricao"],
            })
    ordenar_mensalidades(mensalidades)
    return {
        "nome": nome,
        "nivel": a["nivel"],
        "curso": a["curso"],
        "instituicao": a["instituicao"],
        "percentual": a["percentual"],
        "valor_mensal": a["valor_mensal"],
        "mensalidades": mensalidades,
        "resumo": {
            "qtd": len(mensalidades),
            "empenhado": round(sum(m["empenhado"] for m in mensalidades), 2),
            "liquidado": round(sum(m["liquidado"] for m in mensalidades), 2),
            "pago": round(sum(m["pago"] for m in mensalidades), 2),
            "a_pagar": round(sum(m["a_pagar"] for m in mensalidades), 2),
        },
    }


def coletar(limite: int | None = None, alvos: list[str] | None = None, forcar: bool = False) -> dict:
    alunos = carregar_roster()
    mapear_canonico(alunos)
    total = len(alunos)
    sem_match = [a["nome_roster"] for a in alunos if not a["nome_canonico"]]
    alunos = [a for a in alunos if a["nome_canonico"]]
    print(f"Roster (Superior+Especialização): {total} | casados no portal: {len(alunos)}")
    if sem_match:
        print(f"  sem casamento ({len(sem_match)}): {sem_match}")
    if alvos:
        alvos_n = [_norm(x) for x in alvos]
        alunos = [a for a in alunos
                  if any(av in _norm(a["nome_roster"]) or av in _norm(a["nome_canonico"]) for av in alvos_n)]
        print(f"  filtro --alunos → {[a['nome_canonico'] for a in alunos]}")
    if limite:
        alunos = alunos[:limite]

    por_nome = _carregar_existente()
    print(f"Dataset existente: {len(por_nome)} alunos (merge incremental)")
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        for a in alunos:
            nome = a["nome_canonico"]
            if not forcar and por_nome.get(nome, {}).get("mensalidades"):
                print(f"  {nome}: já no dataset, pulando")
                continue
            por_nome[nome] = coletar_aluno(pg, a)
            print(f"  {nome}: {len(por_nome[nome]['mensalidades'])} mensalidades de bolsa", flush=True)
            _salvar(por_nome)  # incremental + merge (não sobrescreve quem já existe)
        b.close()

    return {"fonte": FONTE_NOME, "url": URL,
            "alunos": sorted(por_nome.values(), key=lambda a: a["nome"])}


def reparsear() -> None:
    """Reaplica o parser atual aos detalhes já em cache (campo `raw`), deduz anulações
    e atualiza o dataset — sem rede. Use depois de melhorar parse_detalhe."""
    por_nome = _carregar_existente()
    fixados = 0
    from app.csv_loader import buscar as csv_buscar
    for nome, a in list(por_nome.items()):
        # Obtém os registros oficiais do CSV para poder filtrar os anulados e incluir novos
        base = csv_buscar(nome)
        por_empenho = {r["empenho"].lstrip("0") or "0": r for r in base["registros"]}
        
        novas_mensalidades = []
        for numero, reg in por_empenho.items():
            cf = CACHE / f"{reg['ano']}-{numero}.json"
            if not cf.exists():
                continue
            det = json.loads(cf.read_text(encoding="utf-8"))
            if not eh_bolsa(det):
                continue
            
            if det.get("raw"):
                novo = parse_detalhe(det["raw"])
            else:
                novo = {
                    "funcao": det.get("funcao", ""),
                    "acao": det.get("acao", ""),
                    "descricao": det.get("descricao", ""),
                    "mes_referencia": det.get("mes_referencia", ""),
                    "meses": det.get("meses", [det.get("mes_referencia", "")]),
                    "tipo": det.get("tipo", "mensalidade"),
                    "parcela": det.get("parcela")
                }
            
            m_empenhado = reg.get("empenhado", 0.0)
            m_liquidado = reg.get("liquidado", 0.0)
            m_pago = reg.get("pago", 0.0)
            m_a_pagar = reg.get("a_pagar", 0.0)
            
            # Filtra se o empenho foi totalmente anulado (tudo zerado)
            if m_empenhado <= 0.0 and m_liquidado <= 0.0 and m_pago <= 0.0:
                continue
                
            # Verifica se houve correção de meses
            # Encontra se já existia na lista para poder contar fixados
            m_antigo = next((m for m in a.get("mensalidades", []) if m["empenho"] == numero), None)
            if m_antigo and novo.get("meses") != m_antigo.get("meses"):
                fixados += 1
                
            novas_mensalidades.append({
                "empenho": numero,
                "ano": reg["ano"],
                "mes_referencia": novo["mes_referencia"],
                "meses": novo.get("meses", []),
                "tipo": novo.get("tipo", "mensalidade"),
                "parcela": novo.get("parcela"),
                "empenhado": m_empenhado,
                "liquidado": m_liquidado,
                "pago": m_pago,
                "a_pagar": m_a_pagar,
                "data_empenho": reg.get("data_empenho"),
                "data_liquidacao": reg.get("data_liquidacao"),
                "data_pagamento": reg.get("data_pagamento"),
                "descricao": novo["descricao"]
            })
            
            if det.get("raw"):
                cf.write_text(json.dumps(novo, ensure_ascii=False), encoding="utf-8")
            
        a["mensalidades"] = novas_mensalidades
        ordenar_mensalidades(a["mensalidades"])
        
        # Atualiza o resumo financeiro do aluno
        a["resumo"] = {
            "qtd": len(a["mensalidades"]),
            "empenhado": round(sum(m["empenhado"] for m in a["mensalidades"]), 2),
            "liquidado": round(sum(m["liquidado"] for m in a["mensalidades"]), 2),
            "pago": round(sum(m["pago"] for m in a["mensalidades"]), 2),
            "a_pagar": round(sum(m["a_pagar"] for m in a["mensalidades"]), 2),
        }
    _salvar(por_nome)
    print(f"Reparse: {fixados} meses recuperados em {len(por_nome)} alunos")


def main() -> None:
    p = argparse.ArgumentParser(description="Constrói o dataset de bolsas (merge incremental)")
    p.add_argument("--limite", type=int, default=None, help="processa só os N primeiros alunos")
    p.add_argument("--alunos", default=None, help="coleta só estes nomes (separados por ';')")
    p.add_argument("--forcar", action="store_true", help="re-coleta mesmo quem já está no dataset")
    p.add_argument("--reparsear", action="store_true", help="reprocessa o cache com o parser atual (sem rede)")
    args = p.parse_args()

    if args.reparsear:
        reparsear()
        return

    alvos = [x.strip() for x in args.alunos.split(";")] if args.alunos else None
    dados = coletar(args.limite, alvos, args.forcar)
    n = len(dados["alunos"])
    tot = sum(a["resumo"]["qtd"] for a in dados["alunos"])
    print(f"\n{n} alunos | {tot} mensalidades | gravado em {SAIDA}")


if __name__ == "__main__":
    main()
