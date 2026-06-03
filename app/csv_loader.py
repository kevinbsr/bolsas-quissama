"""Carrega e indexa os CSVs exportados do Portal da Transparência de Quissamã
(Movimentação Diária — Despesas, Consolidada).

O usuário exporta os arquivos via Portal → Despesas → Movimentação Diária →
Exportar CSV, e os coloca em movimentacao-diaria/. Este módulo faz todo o
parsing, limpeza, agregação por empenho e busca por credor.
"""

from __future__ import annotations

import glob
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

DIR_CSV = Path(__file__).resolve().parent.parent / "movimentacao-diaria"
_STOP = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ",
        unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    ).strip()


def _num(t: str) -> float:
    t = re.sub(r"[^\d,]", "", str(t or "")).replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return 0.0


def _carregar_arquivo(path: str, ano: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="latin-1", header=4,
                     quotechar='"', skipinitialspace=True,
                     on_bad_lines="skip", dtype=str)
    df.columns = [
        re.sub(r"[^a-z0-9_]", "_",
               unicodedata.normalize("NFKD", c).encode("ascii", "ignore")
               .decode().lower().strip().strip('="').strip())
        for c in df.columns
    ]
    for c in df.columns:
        df[c] = df[c].str.replace(r'^="?(.*?)"?$', r'\1', regex=True).str.strip()
    df = df[df.iloc[:, 1].str.match(r"\d{3,6}", na=False)]
    df["ano"] = ano
    return df


@lru_cache(maxsize=1)
def _df_completo() -> pd.DataFrame:
    """Lê todos os CSVs em movimentacao-diaria/ (cache em memória)."""
    arquivos = sorted(glob.glob(str(DIR_CSV / "*.csv")))
    if not arquivos:
        return pd.DataFrame()
    partes = []
    for path in arquivos:
        nome = Path(path).stem
        m = re.search(r"(\d{4})", nome)
        ano = m.group(1) if m else "?"
        partes.append(_carregar_arquivo(path, ano))
    df = pd.concat(partes, ignore_index=True)
    df["_credor"] = df["credor"].apply(_norm)
    for col in ("valor_empenho", "valor_em_liquidacao", "valor_liquidado", "valor_pago", "valor_anulado"):
        df[f"_n_{col}"] = df[col].apply(_num)
    return df


def invalidar_cache():
    _df_completo.cache_clear()


def pre_carregar():
    """Força o carregamento dos CSVs no startup, antes da primeira requisição."""
    _df_completo()


def _tokens(nome: str) -> list[str]:
    return [t for t in _norm(nome).split() if t not in _STOP]


def _agg(sub: pd.DataFrame) -> list[dict]:
    """Agrega linhas de movimentação em processos de empenho únicos, preservando cronologia."""
    agg: dict[tuple, dict] = {}
    for _, r in sub.iterrows():
        # Chave única por empenho e unidade (um empenho pode atravessar anos)
        k = (r["numero_do_empenho"], r["unidade_gestora"])
        d = agg.setdefault(k, {
            "empenho": r["numero_do_empenho"],
            "unidade_gestora": r["unidade_gestora"],
            "credor": r["credor"],
            "ano": r["ano"], # Ano de origem (será atualizado para o menor)
            "data_empenho": None,
            "data_liquidacao": None,
            "data_pagamento": None,
            "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "anulado": 0.0,
        })
        
        n_emp = r["_n_valor_empenho"]
        n_liq = r["_n_valor_liquidado"]
        n_pag = r["_n_valor_pago"]
        data = r.get("data_movimento", "")

        # Atribuição inteligente de datas e valores
        if n_emp > 0:
            d["empenhado"] = max(d["empenhado"], n_emp)
            if not d["data_empenho"] or int(r["ano"]) < int(d["ano"]):
                d["data_empenho"] = data
                d["ano"] = r["ano"]
        
        if n_liq > 0:
            d["liquidado"] = max(d["liquidado"], n_liq)
            d["data_liquidacao"] = data # Em geral, a última liquidação é a que vale
            
        if n_pag > 0:
            d["pago"] += n_pag
            d["data_pagamento"] = data
            # Captura o ano real do pagamento para o gráfico de fluxo
            if data:
                try:
                    ano_pag = data.split('/')[-1]
                    if "pagamentos_por_ano" not in d: d["pagamentos_por_ano"] = {}
                    d["pagamentos_por_ano"][ano_pag] = d["pagamentos_por_ano"].get(ano_pag, 0) + 1
                except Exception: pass
            
        d["anulado"] = max(d["anulado"], r["_n_valor_anulado"])

    regs = []
    for d in sorted(agg.values(), key=lambda x: (x["ano"], x["empenho"]), reverse=True):
        d["pago"] = round(d["pago"], 2)
        d["a_pagar"] = round(max(d["liquidado"] - d["pago"], 0.0), 2)
        # Fallback para data_movimento para compatibilidade
        d["data_movimento"] = d["data_empenho"] or d["data_liquidacao"] or d["data_pagamento"]
        regs.append(d)
    return regs


def listar_nomes() -> list[str]:
    """Retorna todos os nomes de credores únicos para cache no cliente."""
    df = _df_completo()
    if df.empty:
        return []
    return sorted(df["credor"].dropna().unique().tolist())


def sugerir(termo: str) -> list[str]:
    """Retorna uma lista de nomes de credores que combinam com o termo digitado."""
    df = _df_completo()
    if df.empty or len(termo) < 2:
        return []
    
    tokens = _tokens(termo)
    # Filtra nomes que contenham todos os tokens digitados
    mask = df["_credor"].apply(lambda x: all(t in x for t in tokens))
    return sorted(df[mask]["credor"].unique().tolist())[:10] # Limita a 10 sugestões


def buscar(nome: str) -> dict:
    """Retorna os empenhos do credor baseados exclusivamente nos dados oficiais do portal."""
    df = _df_completo()
    
    if df.empty:
        return {"nome": nome, "registros": [], "resumo": _resumo([])}

    tokens = _tokens(nome)
    mask = df["_credor"].apply(lambda x: all(t in x for t in tokens))
    sub = df[mask]
    credores = sub["credor"].unique().tolist() if not sub.empty else []
    regs = _agg(sub)
    res_oficial = _resumo(regs)

    return {
        "nome": nome,
        "credores_encontrados": credores,
        "registros": regs,
        "resumo": res_oficial,
        "fonte": "Portal da Transparência de Quissamã",
        "url": "https://webapp1-quissama.cidade360.cloud/pronimtb/index.asp?acao=3&item=11",
    }


def _resumo(regs: list[dict]) -> dict:
    return {
        "qtd": len(regs),
        "empenhado": round(sum(r["empenhado"] for r in regs), 2),
        "liquidado": round(sum(r["liquidado"] for r in regs), 2),
        "pago": round(sum(r["pago"] for r in regs), 2),
        "a_pagar": round(sum(r["a_pagar"] for r in regs), 2),
    }
