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


def resumo_geral() -> dict:
    dados = _dados()
    alunos = dados.get("alunos", [])

    total_emp = total_liq = total_pago = total_rec = 0.0
    total_mens = mens_pagas = 0
    por_nivel: dict[str, int] = {}
    por_inst: dict[str, dict] = {}
    por_curso: dict[str, dict] = {}
    por_perc: dict[str, int] = {}

    for a in alunos:
        r = a.get("resumo") or {}
        total_emp  += r.get("empenhado", 0) or 0
        total_liq  += r.get("liquidado", 0) or 0
        total_pago += r.get("pago", 0) or 0
        total_rec  += r.get("a_pagar", 0) or 0
        total_mens += r.get("qtd", 0) or 0
        mens_pagas += sum(1 for m in a.get("mensalidades", []) if (m.get("pago") or 0) > 0)

        nivel = str(a.get("nivel") or "Superior")
        por_nivel[nivel] = por_nivel.get(nivel, 0) + 1

        inst = str(a.get("instituicao") or "Outras")
        if inst not in por_inst:
            por_inst[inst] = {"alunos": 0, "empenhado": 0.0, "pago": 0.0}
        por_inst[inst]["alunos"] += 1
        por_inst[inst]["empenhado"] = round(por_inst[inst]["empenhado"] + (r.get("empenhado") or 0), 2)
        por_inst[inst]["pago"]      = round(por_inst[inst]["pago"]      + (r.get("pago")      or 0), 2)

        curso = str(a.get("curso") or "Não informado")
        if curso not in por_curso:
            por_curso[curso] = {"alunos": 0, "empenhado": 0.0, "pago": 0.0}
        por_curso[curso]["alunos"] += 1
        por_curso[curso]["empenhado"] = round(por_curso[curso]["empenhado"] + (r.get("empenhado") or 0), 2)
        por_curso[curso]["pago"]      = round(por_curso[curso]["pago"]      + (r.get("pago")      or 0), 2)

        perc = str(a.get("percentual") or "100")
        por_perc[perc] = por_perc.get(perc, 0) + 1

    return {
        "total_alunos": len(alunos),
        "total_empenhado": round(total_emp, 2),
        "total_liquidado": round(total_liq, 2),
        "total_pago": round(total_pago, 2),
        "total_a_pagar": round(total_rec, 2),
        "total_mensalidades": total_mens,
        "mensalidades_pagas": mens_pagas,
        "por_nivel": por_nivel,
        "por_instituicao": sorted(
            [{"nome": k, **v} for k, v in por_inst.items()],
            key=lambda x: x["empenhado"], reverse=True,
        ),
        "por_curso": sorted(
            [{"nome": k, **v} for k, v in por_curso.items()],
            key=lambda x: x["empenhado"], reverse=True,
        ),
        "por_percentual": por_perc,
    }


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
