"""Processa o controle de reembolsos do programa de bolsas de estudo e gera os
dados do portal (resumo, pendências, linha do tempo do valor devido, projeção).

Planilha esperada: cabeçalho na linha 4, colunas:
  Processos | Mensalidade | Pago à FIAP em | Valores | Protocolado |
  Protocolado em | Restituído | Recebido em | Liquidado

Uso:
    python scripts/analise_bolsas.py --xlsx ~/Downloads/bolsas.xlsx
    python scripts/analise_bolsas.py --xlsx ~/Downloads/bolsas.xlsx --portal-json data/bolsas.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

COLS = ["processo", "mensalidade", "pago_fiap", "valor", "protocolado",
        "protocolado_em", "restituido", "recebido_em", "liquidado"]


def carregar(xlsx: str, header_linha: int = 4) -> pd.DataFrame:
    raw = pd.read_excel(xlsx, header=None)
    df = raw.iloc[header_linha:].copy()
    df.columns = COLS
    df = df.reset_index(drop=True)
    for c in ("mensalidade", "pago_fiap", "protocolado_em", "recebido_em"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
        # células com só o ano (ex.: 2024) viram lixo perto de 1970 — descarta
        df.loc[df[c] < pd.Timestamp("2000-01-01"), c] = pd.NaT
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    for c in ("protocolado", "restituido"):
        df[c] = df[c].astype(str).str.strip().isin(["True", "VERDADEIRO", "1"])
    return df.dropna(subset=["valor"])


def _data_ref(row) -> pd.Timestamp:
    return row["protocolado_em"] if pd.notna(row["protocolado_em"]) else row["mensalidade"]


def linha_do_tempo_devido(prot: pd.DataFrame) -> list[dict]:
    """Valor protocolado e ainda não restituído, acumulado mês a mês."""
    eventos = []  # (data, +valor ao protocolar, -valor ao receber)
    for _, r in prot.iterrows():
        ini = _data_ref(r)
        if pd.notna(ini):
            eventos.append((ini.to_period("M").to_timestamp(), r["valor"]))
        if r["restituido"] and pd.notna(r["recebido_em"]):
            eventos.append((r["recebido_em"].to_period("M").to_timestamp(), -r["valor"]))
    if not eventos:
        return []
    s = pd.Series(dtype=float)
    df = pd.DataFrame(eventos, columns=["mes", "delta"]).groupby("mes")["delta"].sum().sort_index()
    meses = pd.period_range(df.index.min().to_period("M"), pd.Timestamp("2026-06-02").to_period("M"), freq="M")
    acum, out = 0.0, []
    serie = df.reindex([m.to_timestamp() for m in meses], fill_value=0.0)
    for mes, delta in serie.items():
        acum = round(acum + delta, 2)
        out.append({"mes": mes.strftime("%Y-%m"), "devido_acumulado": round(max(acum, 0.0), 2)})
    return out


def construir(df: pd.DataFrame, hoje: pd.Timestamp) -> dict:
    prot = df[df["protocolado"]].copy()
    rest = prot[prot["restituido"]].copy()
    pend = prot[~prot["restituido"]].copy()
    futuras = df[~df["protocolado"]].copy()  # mensalidades futuras ainda não pedidas

    pend["dias_em_aberto"] = (hoje - pend.apply(_data_ref, axis=1)).dt.days
    rest_v = rest.dropna(subset=["recebido_em", "mensalidade"]).copy()
    rest_v["dias_espera"] = (rest_v["recebido_em"] - rest_v["mensalidade"]).dt.days

    def item(r, extra):
        d = {
            "processo": str(r["processo"]),
            "mensalidade": r["mensalidade"].strftime("%Y-%m-%d") if pd.notna(r["mensalidade"]) else None,
            "valor": round(float(r["valor"]), 2),
        }
        d.update(extra)
        return d

    pendentes = [
        item(r, {
            "protocolado_em": r["protocolado_em"].strftime("%Y-%m-%d") if pd.notna(r["protocolado_em"]) else None,
            "dias_em_aberto": int(r["dias_em_aberto"]) if pd.notna(r["dias_em_aberto"]) else None,
        })
        for _, r in pend.sort_values("dias_em_aberto", ascending=False).iterrows()
    ]
    recebidos = [
        item(r, {
            "recebido_em": r["recebido_em"].strftime("%Y-%m-%d"),
            "dias_espera": int(r["dias_espera"]),
        })
        for _, r in rest_v.sort_values("recebido_em").iterrows()
    ]

    return {
        "fonte": "Controle pessoal do beneficiário (reembolsos do programa municipal de bolsa de estudo)",
        "atualizado_em": hoje.strftime("%Y-%m-%d"),
        "resumo": {
            "protocolado_total": round(float(prot["valor"].sum()), 2),
            "reembolsado_total": round(float(rest["valor"].sum()), 2),
            "pendente_total": round(float(pend["valor"].sum()), 2),
            "pendentes_qtd": int(len(pend)),
            "recebidos_qtd": int(len(rest)),
            "pendente_mais_antigo_dias": int(pend["dias_em_aberto"].max()) if len(pend) else 0,
            "pendentes_mais_1_ano_qtd": int((pend["dias_em_aberto"] > 365).sum()),
            "pendentes_mais_1_ano_valor": round(float(pend.loc[pend["dias_em_aberto"] > 365, "valor"].sum()), 2),
            "espera_media_dias": int(rest_v["dias_espera"].mean()) if len(rest_v) else None,
            "espera_max_dias": int(rest_v["dias_espera"].max()) if len(rest_v) else None,
            "futuras_previstas_total": round(float(futuras["valor"].sum()), 2),
        },
        "pendentes": pendentes,
        "recebidos": recebidos,
        "timeline_devido": linha_do_tempo_devido(prot),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Análise de reembolsos de bolsa de estudo")
    p.add_argument("--xlsx", required=True)
    p.add_argument("--hoje", default="2026-06-02")
    p.add_argument("--portal-json", help="grava o JSON usado pelo portal")
    args = p.parse_args()

    df = carregar(args.xlsx)
    dados = construir(df, pd.Timestamp(args.hoje))
    r = dados["resumo"]
    print("== REEMBOLSOS DE BOLSA — RESUMO ==")
    print(f"  Protocolado:  R$ {r['protocolado_total']:,.2f}")
    print(f"  Reembolsado:  R$ {r['reembolsado_total']:,.2f}")
    print(f"  PENDENTE:     R$ {r['pendente_total']:,.2f}  ({r['pendentes_qtd']} itens)")
    print(f"  +1 ano:       R$ {r['pendentes_mais_1_ano_valor']:,.2f} | mais antigo {r['pendente_mais_antigo_dias']} dias")
    if r["espera_media_dias"]:
        print(f"  Espera (pagos): média {r['espera_media_dias']} d | pior {r['espera_max_dias']} d")

    if args.portal_json:
        Path(args.portal_json).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  Portal JSON gravado em {args.portal_json}  ({len(dados['timeline_devido'])} meses na linha do tempo)")


if __name__ == "__main__":
    main()
