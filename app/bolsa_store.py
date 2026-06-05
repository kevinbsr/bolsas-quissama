"""Loader do dataset público de bolsas (app/dados/bolsas_publicas.json).

Serve a interface usada pela API (buscar / sugerir / listar_nomes /
pre_carregar / invalidar_cache). Leve e sem pandas — o JSON tem ~100 alunos e
fica em memória. O dataset é construído offline por scripts/coletar_bolsas.py.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DATASET = Path(__file__).resolve().parent / "dados" / "bolsas_publicas.json"
_STOP = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ",
        unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    ).strip()


def _tokens(nome: str) -> list[str]:
    return [t for t in _norm(nome).split() if t not in _STOP]


@lru_cache(maxsize=1)
def _dados() -> dict:
    if not DATASET.exists():
        return {"fonte": "", "url": "", "alunos": []}
    dados = json.loads(DATASET.read_text(encoding="utf-8"))
    for a in dados.get("alunos", []):
        a["_norm"] = _norm(a["nome"])
        a["_tokens"] = set(_tokens(a["nome"]))
    return dados


def invalidar_cache() -> None:
    _dados.cache_clear()


def pre_carregar() -> None:
    _dados()


def listar_nomes() -> list[str]:
    return sorted(a["nome"] for a in _dados().get("alunos", []))


def sugerir(termo: str) -> list[str]:
    toks = _tokens(termo)
    if not toks:
        return []
    alunos = _dados().get("alunos", [])
    achados = [a["nome"] for a in alunos if all(t in a["_norm"] for t in toks)]
    return sorted(achados)[:10]


def buscar(nome: str) -> dict:
    dados = _dados()
    toks = set(_tokens(nome))
    alvo = None
    if toks:
        # casa todos os tokens digitados contra o nome do aluno
        alvo = next((a for a in dados["alunos"] if toks <= a["_tokens"]), None)
    base = {"nome": nome, "fonte": dados.get("fonte", ""), "url": dados.get("url", "")}
    if not alvo:
        return {**base, "encontrado": False, "mensalidades": [],
                "resumo": {"qtd": 0, "empenhado": 0, "liquidado": 0, "pago": 0, "a_pagar": 0}}
    return {
        **base,
        "encontrado": True,
        "nome": alvo["nome"],
        "nivel": alvo.get("nivel"),
        "curso": alvo.get("curso"),
        "instituicao": alvo.get("instituicao"),
        "percentual": alvo.get("percentual"),
        "valor_mensal": alvo.get("valor_mensal"),
        "mensalidades": alvo.get("mensalidades", []),
        "resumo": alvo.get("resumo", {}),
    }
