"""Loader do dataset público de bolsas (app/dados/bolsas_publicas.json).

Serve a interface usada pela API (buscar / sugerir / listar_nomes /
pre_carregar / invalidar_cache). Leve e sem pandas — o JSON tem ~100 alunos e
fica em memória. O dataset é construído offline por scripts/coletar_bolsas.py.
"""

from __future__ import annotations

import datetime
import json
import re
import statistics
import unicodedata
from functools import lru_cache
from pathlib import Path

DATASET = Path(__file__).resolve().parent / "dados" / "bolsas_publicas.json"
_STOP = {"DA", "DE", "DO", "DAS", "DOS", "E"}

# Ano do roster oficial usado para montar o dataset (lista de bolsistas ativos).
# Atualizar ao reprocessar com o roster de um novo ano.
ANO_ROSTER = 2026


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ",
        unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    ).strip()


def _tokens(nome: str) -> list[str]:
    return [t for t in _norm(nome).split() if t not in _STOP]


def _pdate(s: str | None) -> datetime.date | None:
    """Converte 'dd/mm/aaaa' em date; None se inválido."""
    if not s:
        return None
    p = s.split("/")
    if len(p) != 3:
        return None
    try:
        return datetime.date(int(p[2]), int(p[1]), int(p[0]))
    except ValueError:
        return None


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
    hoje = datetime.date.today()
    hoje_ano = hoje.year
    hoje_mes = hoje.month
    cadencia_delays: dict[str, list[int]] = {}
    desembolso: dict[str, float] = {}          # item 1: pago por mês de pagamento
    lag_emp_liq: list[int] = []                # item 2: dias empenho->liquidação
    lag_liq_pag: list[int] = []                # item 2: dias liquidação->pagamento
    lag_emp_pag: list[int] = []                # item 2: dias empenho->pagamento
    liq_nao_pago_val = 0.0                      # item 3: liquidado mas não pago
    liq_nao_pago_qtd = 0
    acordo_alunos = 0                           # item 5: acordos de pagamento
    acordo_val = 0.0

    for a in alunos:
        r = a.get("resumo") or {}
        total_emp  += r.get("empenhado", 0) or 0
        total_liq  += r.get("liquidado", 0) or 0
        total_pago += r.get("pago", 0) or 0
        total_rec  += r.get("a_pagar", 0) or 0
        total_mens += r.get("qtd", 0) or 0
        mens_pagas += sum(1 for m in a.get("mensalidades", []) if (m.get("pago") or 0) > 0)

        for m in a.get("mensalidades", []):
            ref = m.get("mes_referencia")
            if ref and (ref.startswith("2025") or ref.startswith("2026")):
                emp_date = m.get("data_empenho")
                if emp_date and len(emp_date.split("/")) == 3:
                    try:
                        emp_day, emp_month, emp_year = map(int, emp_date.split("/"))
                    except ValueError:
                        continue
                    
                    if (m.get("pago") or 0) > 0 and m.get("data_pagamento"):
                        try:
                            p_day, p_month, p_year = map(int, m["data_pagamento"].split("/"))
                            delay = (p_year - emp_year) * 12 + (p_month - emp_month)
                        except Exception:
                            delay = (hoje_ano - emp_year) * 12 + (hoje_mes - emp_month)
                    else:
                        delay = (hoje_ano - emp_year) * 12 + (hoje_mes - emp_month)
                    
                    delay = max(0, delay)
                    cadencia_delays.setdefault(ref, []).append(delay)

            # item 1: desembolso por mês em que o pagamento de fato ocorreu
            pago = m.get("pago") or 0
            pd = _pdate(m.get("data_pagamento"))
            if pago > 0 and pd:
                chave = f"{pd.year}-{pd.month:02d}"
                desembolso[chave] = round(desembolso.get(chave, 0.0) + pago, 2)

            # item 2: prazos entre etapas (em dias)
            ed = _pdate(m.get("data_empenho"))
            ld = _pdate(m.get("data_liquidacao"))
            if ed and ld:
                lag_emp_liq.append((ld - ed).days)
            if ld and pd and pago > 0:
                lag_liq_pag.append((pd - ld).days)
            if ed and pd and pago > 0:
                lag_emp_pag.append((pd - ed).days)

            # item 3: liquidado (reconhecido) mas ainda não pago
            if (m.get("liquidado") or 0) > 0 and pago <= 0:
                liq_nao_pago_val += m.get("liquidado") or 0
                liq_nao_pago_qtd += 1

        # item 5: bolsistas com parcela do tipo "acordo" (dívida renegociada)
        m_acordo = [m for m in a.get("mensalidades", []) if m.get("tipo") == "acordo"]
        if m_acordo:
            acordo_alunos += 1
            acordo_val += sum(m.get("empenhado") or 0 for m in m_acordo)

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

    cadencia_lista = []
    for k, v in sorted(cadencia_delays.items()):
        avg = round(sum(v) / len(v), 1) if v else 0.0
        cadencia_lista.append({
            "mes": k,
            "atraso_medio": avg,
            "total_mensalidades": len(v)
        })

    desembolso_lista = [
        {"mes": k, "pago": v} for k, v in sorted(desembolso.items())
    ]

    def _med(xs: list[int]) -> int:
        return int(round(statistics.median(xs))) if xs else 0

    prazos = {
        "empenho_liquidacao": _med(lag_emp_liq),
        "liquidacao_pagamento": _med(lag_liq_pag),
        "empenho_pagamento": _med(lag_emp_pag),
    }

    return {
        "ano_roster": ANO_ROSTER,
        "data_atualizacao": dados.get("data_atualizacao", ""),
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
        "cadencia": cadencia_lista,
        "desembolso_mensal": desembolso_lista,
        "prazos": prazos,
        "liquidado_nao_pago": {
            "valor": round(liq_nao_pago_val, 2),
            "parcelas": liq_nao_pago_qtd,
        },
        "acordos": {
            "alunos": acordo_alunos,
            "valor": round(acordo_val, 2),
        },
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
