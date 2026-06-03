"""Motor de busca do hub: consulta empenhos de um credor no Portal da
Transparência de Quissamã (Cidade360/IPM) via Playwright + Chromium.

A página de Empenhos (acao=3&item=11) é "Movimentação Diária": cada empenho
aparece em VÁRIAS linhas (uma por movimento — empenho, liquidação, pagamento).
Aqui agregamos por número de empenho para obter o quadro real por empenho:
empenhado / liquidado / pago / a pagar.

É leitura de dado público, de baixo volume. Resultados são cacheados em
data/cache/ para não consultar o portal a cada acesso.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

BASE = "https://webapp1-quissama.cidade360.cloud/pronimtb/"
URL = BASE + "index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
ANOS_PADRAO = ["2024", "2025", "2026"]
CACHE_TTL = 6 * 3600  # 6h


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper()).strip()


def _num(t: str) -> float:
    t = re.sub(r"[^\d,.-]", "", t or "").replace(".", "").replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return 0.0


def _slug(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(nome).lower()).strip("-")


_STOP = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def _tokens_significativos(nome: str) -> list[str]:
    return [t for t in _norm(nome).split() if t not in _STOP]


def _termo_busca(nome: str) -> str:
    """Busca pelos 2 ÚLTIMOS sobrenomes significativos.

    O portal é sensível a acento; primeiros nomes podem ter acento (KAUÊ), mas
    sobrenomes raramente têm — então sobrenomes são um termo de busca mais
    confiável. O filtro por tokens depois garante que é a pessoa certa.
    """
    toks = _tokens_significativos(nome)
    return " ".join(toks[-2:]) if len(toks) >= 2 else (toks[0] if toks else nome)


def _extrair_grade(pg) -> list[list[str]]:
    return pg.evaluate("""() => {
      const t=[...document.querySelectorAll('table')].find(e=>[...e.querySelectorAll('th')].some(h=>/Número do Empenho/i.test(h.innerText)));
      if(!t) return [];
      return [...t.querySelectorAll('tr')]
        .map(tr=>[...tr.querySelectorAll('td')].map(td=>td.innerText.replace(/\\s+/g,' ').trim()))
        .filter(r=>r.length>=10);
    }""")


def buscar_credor(nome: str, anos: list[str] | None = None, usar_cache: bool = True) -> dict:
    anos = anos or ANOS_PADRAO
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{_slug(nome)}.json"
    if usar_cache and cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL:
        return json.loads(cache.read_text(encoding="utf-8"))

    from playwright.sync_api import sync_playwright

    termo = _termo_busca(nome)
    tokens = _tokens_significativos(nome)
    # por empenho: (ano, empenho) -> valores agregados
    agg: dict[tuple, dict] = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        for ano in anos:
            pg.goto(URL, wait_until="networkidle", timeout=60000)
            pg.select_option("select[name=cmbAno]", ano)
            pg.fill("input[name=txtNomeFornecedor]", termo)
            pg.click("input[value='Gerar']")
            pg.wait_for_timeout(4000)
            for r in _extrair_grade(pg):
                credor = _norm(r[4])
                if not all(t in credor for t in tokens):
                    continue
                chave = (ano, r[1])
                d = agg.setdefault(chave, {
                    "ano": ano, "empenho": r[1], "unidade_gestora": r[3], "credor": r[4],
                    "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "anulado": 0.0,
                })
                d["empenhado"] = max(d["empenhado"], _num(r[5]))
                d["liquidado"] = max(d["liquidado"], _num(r[7]))
                d["pago"] = max(d["pago"], _num(r[8]))
                d["anulado"] = max(d["anulado"], _num(r[9]))
        b.close()

    registros = []
    for d in sorted(agg.values(), key=lambda x: (x["ano"], x["empenho"])):
        d["a_pagar"] = round(max(d["liquidado"] - d["pago"], 0.0), 2)
        registros.append(d)

    resumo = {
        "qtd": len(registros),
        "empenhado": round(sum(x["empenhado"] for x in registros), 2),
        "liquidado": round(sum(x["liquidado"] for x in registros), 2),
        "pago": round(sum(x["pago"] for x in registros), 2),
        "a_pagar": round(sum(x["a_pagar"] for x in registros), 2),
    }
    resultado = {
        "nome": nome,
        "termo_busca": termo,
        "anos": anos,
        "fonte": "Portal da Transparência de Quissamã (Cidade360/IPM)",
        "url": URL,
        "registros": registros,
        "resumo": resumo,
    }
    cache.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado
