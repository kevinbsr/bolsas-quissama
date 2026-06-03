"""Extrai empenhos de um credor no Portal da Transparência de Quissamã
(Cidade360 / IPM TransparênciaBR) via navegador headless (Playwright + Chromium).

O portal é um postback ASP com reCAPTCHA invisível na geração; a consulta por
"Nome do Credor" (página acao=3&item=11) é pública. Este script automatiza:
seleciona o ano, preenche o nome, clica em "Gerar" e lê a grade de resultados
com os valores Empenhado / Em Liquidação / Liquidado / Pago / Anulado.

Gera data/empenhos_bolsa.json (consumido pelo portal). É leitura de dado
público da própria pessoa — uso de baixo volume.

Uso:
    python scripts/scrape_cidade360.py --nome "NOME COMPLETO" --anos 2024 2025 2026
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://webapp1-quissama.cidade360.cloud/pronimtb/"
URL = BASE + "index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COLUNAS = ["data_movimento", "empenho", "tipo", "unidade_gestora", "credor",
           "empenhado", "em_liquidacao", "liquidado", "pago", "anulado"]


def _num(txt: str) -> float:
    t = re.sub(r"[^\d,.-]", "", txt or "").replace(".", "").replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return 0.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def extrair_ano(pg, ano: str) -> list[list[str]]:
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.select_option("select[name=cmbAno]", ano)
    pg.fill("input[name=txtNomeFornecedor]", "")
    pg.fill("input[name=txtNomeFornecedor]", _NOME)
    pg.click("input[value='Gerar']")
    pg.wait_for_timeout(4500)
    return pg.evaluate("""() => {
      const t=[...document.querySelectorAll('table')]
        .find(e=>[...e.querySelectorAll('th')].some(h=>/Número do Empenho/i.test(h.innerText)));
      if(!t) return [];
      return [...t.querySelectorAll('tr')]
        .map(tr=>[...tr.querySelectorAll('td')].map(td=>td.innerText.replace(/\\s+/g,' ').trim()))
        .filter(r=>r.length>=10 && r.join('').length>10);
    }""")


def main() -> None:
    global _NOME
    p = argparse.ArgumentParser(description="Scraper de empenhos por credor (Cidade360)")
    p.add_argument("--nome", required=True, help="Nome do credor (como nos empenhos)")
    p.add_argument("--anos", nargs="+", default=["2024", "2025", "2026"])
    p.add_argument("--saida", default=str(DATA_DIR / "empenhos_bolsa.json"))
    p.add_argument("--estrito", action="store_true", help="só linhas cujo credor contém todos os termos do nome")
    args = p.parse_args()
    _NOME = args.nome

    termos = _norm(args.nome).split()
    registros, vistos = [], set()
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        for ano in args.anos:
            try:
                linhas = extrair_ano(pg, ano)
            except Exception as e:  # noqa: BLE001
                print(f"{ano}: falha — {e}")
                continue
            n0 = len(registros)
            for r in linhas:
                d = dict(zip(COLUNAS, r[:10]))
                credor_n = _norm(d.get("credor", ""))
                if args.estrito and not all(t in credor_n for t in termos):
                    continue
                chave = (ano, d.get("empenho"), d.get("unidade_gestora"), d.get("credor"))
                if chave in vistos:
                    continue
                vistos.add(chave)
                for c in ("empenhado", "em_liquidacao", "liquidado", "pago", "anulado"):
                    d[c] = _num(d.get(c, ""))
                d["ano"] = ano
                d["a_pagar"] = round(max(d["liquidado"] - d["pago"], 0.0), 2)
                registros.append(d)
            print(f"{ano}: {len(registros)-n0} empenhos")
        b.close()

    resumo = {
        "qtd": len(registros),
        "valor_total": round(sum(x["empenhado"] for x in registros), 2),
        "valor_liquidado": round(sum(x["liquidado"] for x in registros), 2),
        "valor_pago": round(sum(x["pago"] for x in registros), 2),
        "a_pagar": round(sum(x["a_pagar"] for x in registros), 2),
    }
    payload = {
        "fonte": "Portal da Transparência de Quissamã (Cidade360/IPM) — extração automatizada",
        "url": URL,
        "credor_busca": args.nome,
        "registros": registros,
        "resumo": resumo,
    }
    Path(args.saida).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{resumo['qtd']} empenhos | empenhado R$ {resumo['valor_total']:,.2f} | "
          f"pago R$ {resumo['valor_pago']:,.2f} | a pagar R$ {resumo['a_pagar']:,.2f}")
    print(f"Gravado: {args.saida}")


if __name__ == "__main__":
    main()
