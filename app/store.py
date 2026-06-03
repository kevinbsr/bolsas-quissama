"""Dados do portal de acompanhamento das bolsas de estudo.

FONTE PRIMÁRIA: empenhos públicos extraídos do Portal da Transparência de
Quissamã (data/empenhos_bolsa.json, via scripts/scrape_cidade360.py).

COMPARAÇÃO (não é a fonte final): o controle pessoal do beneficiário
(data/bolsas.json), usado só para confrontar com o que consta oficialmente e
revelar pedidos sem empenho público correspondente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOLERANCIA = 0.50  # casamento de valores em reais


def _read(nome: str, default: Any) -> Any:
    caminho = DATA_DIR / nome
    if not caminho.exists():
        return default
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def carregar_empenhos() -> dict:
    return _read("empenhos_bolsa.json", {"registros": [], "resumo": {}})


def carregar_controle() -> dict:
    return _read("bolsas.json", {"resumo": {}, "pendentes": [], "recebidos": []})


def _valor_repr(emp: dict) -> float:
    """Valor de referência de um empenho para casar com o controle."""
    for c in ("empenhado", "liquidado", "pago"):
        if emp.get(c):
            return emp[c]
    return 0.0


def reconciliar(empenhos: dict, controle: dict) -> dict:
    """Casa cada empenho público com um lançamento do controle (por valor) e
    expõe os pedidos do controle que NÃO têm empenho público correspondente."""
    registros = list(empenhos.get("registros", []))
    # universo de lançamentos do controle (pendentes + recebidos)
    lancamentos = []
    for grupo, itens in (("recebido", controle.get("recebidos", [])), ("pendente", controle.get("pendentes", []))):
        for it in itens:
            lancamentos.append({**it, "_status": grupo, "_casado": False})

    casados = []
    for emp in registros:
        v = _valor_repr(emp)
        alvo = None
        for l in lancamentos:
            if not l["_casado"] and abs(l.get("valor", 0) - v) <= TOLERANCIA:
                alvo = l
                break
        if alvo:
            alvo["_casado"] = True
        casados.append({"empenho": emp, "controle": alvo})

    sem_empenho = [l for l in lancamentos if not l["_casado"]]
    sem_empenho_total = round(sum(l.get("valor", 0) for l in sem_empenho), 2)

    return {
        "empenhos_no_portal": len(registros),
        "lancamentos_no_controle": len(lancamentos),
        "sem_empenho_publico_qtd": len(sem_empenho),
        "sem_empenho_publico_total": sem_empenho_total,
        "sem_empenho_publico": sorted(sem_empenho, key=lambda x: x.get("valor", 0), reverse=True),
        "casados": casados,
    }


def montar() -> dict:
    empenhos = carregar_empenhos()
    controle = carregar_controle()
    return {
        "empenhos": empenhos,
        "controle_resumo": controle.get("resumo", {}),
        "reconciliacao": reconciliar(empenhos, controle),
    }
