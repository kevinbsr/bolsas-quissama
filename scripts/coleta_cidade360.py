"""Ingere dados públicos de empenhos/despesas do Portal da Transparência de
Quissamã (Cidade360 / IPM Pronim) relacionados a bolsa/auxílio a estudantes.

O portal é um aplicativo ASP com consulta por POST (difícil de raspar de forma
estável) MAS possui o recurso "Exportar Dados". O caminho confiável é:

  1. Acesse https://webapp1-quissama.cidade360.cloud/pronimtb/
  2. Menu Despesas → "Natureza da despesa"
  3. Filtre a natureza 3.3.90.18 — Auxílio Financeiro a Estudantes
     (ou Despesas → Empenhos; ou Credores → busque seu nome)
  4. Selecione o ano e clique em "Exportar Dados" (CSV/XLS)
  5. Salve o arquivo e rode este script apontando para ele.

O parser tolera variações de cabeçalho comuns do IPM (empenho, credor, data,
valor, natureza, situação/pago). Gera data/empenhos_bolsa.json para o portal.

Uso:
    python scripts/coleta_cidade360.py --arquivo ~/Downloads/despesas.csv
    python scripts/coleta_cidade360.py --arquivo export.xls --sep ";"
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# fragmentos de cabeçalho -> campo canônico
MAPA = {
    "empenho": ["empenho", "nrempenho", "numeroempenho"],
    "credor": ["credor", "favorecido", "fornecedor", "beneficiario"],
    "data": ["data", "dataempenho", "dtempenho", "emissao"],
    "valor": ["valor", "vlempenho", "valorempenho", "vlrempenho"],
    "pago": ["pago", "valorpago", "vlpago"],
    "natureza": ["natureza", "elemento", "despesa"],
    "situacao": ["situacao", "status", "fase"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def mapear_colunas(cols) -> dict:
    norm = {c: _norm(c) for c in cols}
    achado = {}
    for canon, frags in MAPA.items():
        for c, n in norm.items():
            if any(n == f or n.startswith(f) for f in frags):
                achado[canon] = c
                break
    return achado


def carregar(arquivo: str, sep: str | None) -> pd.DataFrame:
    p = Path(arquivo)
    if p.suffix.lower() in (".xls", ".xlsx"):
        return pd.read_excel(arquivo)
    for enc in ("latin-1", "utf-8"):
        try:
            return pd.read_csv(arquivo, sep=sep or ";", encoding=enc, decimal=",", thousands=".")
        except Exception:  # noqa: BLE001
            continue
    return pd.read_csv(arquivo, sep=sep or ";")


def main() -> None:
    p = argparse.ArgumentParser(description="Ingere export do Cidade360 (empenhos de bolsa)")
    p.add_argument("--arquivo", required=True, help="CSV/XLS exportado do portal")
    p.add_argument("--sep", default=None)
    p.add_argument("--saida", default=str(DATA_DIR / "empenhos_bolsa.json"))
    args = p.parse_args()

    df = carregar(args.arquivo, args.sep)
    col = mapear_colunas(df.columns)
    print("Colunas reconhecidas:", col)
    if "valor" not in col:
        raise SystemExit("Não encontrei coluna de valor. Confira o arquivo / use --sep.")

    df["_valor"] = pd.to_numeric(df[col["valor"]], errors="coerce")
    if "data" in col:
        df["_ano"] = pd.to_datetime(df[col["data"]], errors="coerce", dayfirst=True).dt.year

    registros = []
    for _, r in df.iterrows():
        if pd.isna(r["_valor"]):
            continue
        registros.append({
            "empenho": str(r[col["empenho"]]) if "empenho" in col else None,
            "credor": str(r[col["credor"]]) if "credor" in col else None,
            "data": str(r[col["data"]]) if "data" in col else None,
            "valor": round(float(r["_valor"]), 2),
            "pago": round(float(pd.to_numeric(r[col["pago"]], errors="coerce")), 2) if "pago" in col and pd.notna(pd.to_numeric(r[col["pago"]], errors="coerce")) else None,
            "natureza": str(r[col["natureza"]]) if "natureza" in col else None,
            "situacao": str(r[col["situacao"]]) if "situacao" in col else None,
        })

    total = round(sum(x["valor"] for x in registros), 2)
    pago = round(sum(x["pago"] for x in registros if x.get("pago")), 2)
    payload = {
        "fonte": "Portal da Transparência de Quissamã (Cidade360/IPM) — export manual",
        "url": "https://webapp1-quissama.cidade360.cloud/pronimtb/",
        "registros": registros,
        "resumo": {"qtd": len(registros), "valor_total": total, "valor_pago": pago, "a_pagar": round(total - pago, 2)},
    }
    Path(args.saida).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(registros)} registros | empenhado R$ {total:,.2f} | pago R$ {pago:,.2f}")
    print(f"Gravado: {args.saida}")


if __name__ == "__main__":
    main()
