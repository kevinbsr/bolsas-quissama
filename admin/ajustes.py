"""Camada de ajustes manuais sobre o dataset (app/dados/ajustes.json).

Existe porque nem todo empenho é classificável por regex: o texto livre do
portal varia, e às vezes o `mes_referencia` sai errado (ou o empenho nem é
bolsa). Em vez de espremer o parser para cada caso isolado, o operador corrige
o caso pela mão e a correção fica registrada, versionada e auditável.

Aplicado em `coletar_bolsas._salvar()`, ponto único por onde TODO modo do
builder (--forcar / --incremental / --reparsear) grava o dataset. Assim a
correção sobrevive a qualquer reprocessamento — sem isso, o próximo run
desfaria o conserto.

O arquivo é versionado no git de propósito: não contém dado pessoal (só número
de empenho, mês e o nome canônico que já é público no dataset) e, ficando no
repositório, sobrevive a uma reconstrução do container.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

VERSAO = 1

# Campos de mensalidade que um ajuste pode sobrescrever. Deliberadamente NÃO
# inclui valores nem datas: esses vêm do CSV oficial e reescrevê-los seria
# falsear a fonte. O que se corrige aqui é interpretação (qual mês, que tipo),
# nunca o dinheiro.
CAMPOS_MENSALIDADE = ("mes_referencia", "meses", "tipo", "parcela")


def _vazio() -> dict:
    return {"versao": VERSAO, "ano_roster": None, "mensalidades": {}, "alunos": {}}


def carregar(caminho: Path) -> dict:
    if not caminho.exists():
        return _vazio()
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _vazio()
    base = _vazio()
    base.update({k: v for k, v in d.items() if k in base})
    base["mensalidades"] = d.get("mensalidades") or {}
    base["alunos"] = d.get("alunos") or {}
    return base


def salvar(caminho: Path, d: dict) -> None:
    d["versao"] = VERSAO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")


def chave(ano: str, empenho: str) -> str:
    """Identidade de uma mensalidade: o par (ano, empenho) é único no portal."""
    return f"{ano}-{str(empenho).lstrip('0') or '0'}"


def _agora() -> str:
    return datetime.datetime.now().strftime("%d/%m/%Y %H:%M")


def registrar_mensalidade(d: dict, ano: str, empenho: str, campos: dict, nota: str = "") -> str:
    """Grava (ou funde) um ajuste de mensalidade. Retorna a chave usada."""
    k = chave(ano, empenho)
    atual = d["mensalidades"].get(k, {})
    for c in (*CAMPOS_MENSALIDADE, "excluir"):
        if c in campos:
            valor = campos[c]
            # `not valor` e não `valor in (None, "", [])`: aquele teste usa ==, e
            # `False == None` é falso, então desmarcar "excluir" gravava
            # `excluir: False` em vez de apagar o ajuste. Nenhum destes campos é
            # numérico, então tratar todo falsy como "limpar" é seguro.
            if not valor:
                atual.pop(c, None)
            else:
                atual[c] = valor
    # `meses` é derivado de `mes_referencia` quando não vem explícito: o app lê
    # `meses` para montar o calendário e `mes_referencia` para o rótulo, e divergir
    # os dois produz um aluno com mês fantasma. Vale nos dois sentidos — ao limpar
    # o mês, o derivado tem de sair junto, senão sobra um ajuste que parece vazio
    # mas continua sobrescrevendo o dataset.
    if "meses" not in campos:
        if "mes_referencia" in atual:
            atual["meses"] = [atual["mes_referencia"]]
        else:
            atual.pop("meses", None)
    if nota:
        atual["nota"] = nota
    atual["em"] = _agora()
    if not {c for c in atual if c not in ("nota", "em")}:
        d["mensalidades"].pop(k, None)   # ajuste esvaziado = ajuste removido
    else:
        d["mensalidades"][k] = atual
    return k


def registrar_aluno(d: dict, nome: str, campos: dict, nota: str = "") -> None:
    atual = d["alunos"].get(nome, {})
    for c in ("curso", "instituicao", "nivel", "percentual", "ocultar"):
        if c in campos:
            valor = campos[c]
            if not valor:
                atual.pop(c, None)
            else:
                atual[c] = valor
    if nota:
        atual["nota"] = nota
    atual["em"] = _agora()
    if not {c for c in atual if c not in ("nota", "em")}:
        d["alunos"].pop(nome, None)
    else:
        d["alunos"][nome] = atual


def remover(d: dict, escopo: str, k: str) -> bool:
    alvo = d["mensalidades"] if escopo == "mensalidade" else d["alunos"]
    return alvo.pop(k, None) is not None


def _resumo(mens: list[dict]) -> dict:
    return {
        "qtd": len(mens),
        "empenhado": round(sum(m.get("empenhado") or 0 for m in mens), 2),
        "liquidado": round(sum(m.get("liquidado") or 0 for m in mens), 2),
        "pago": round(sum(m.get("pago") or 0 for m in mens), 2),
        "a_pagar": round(sum(m.get("a_pagar") or 0 for m in mens), 2),
    }


def aplicar(por_nome: dict, ajustes: dict) -> int:
    """Aplica os ajustes ao dataset indexado por nome, in-place.

    Recalcula o `resumo` de todo aluno tocado — exclusões mudam os totais, e um
    resumo desatualizado é pior que a mensalidade errada, porque contamina os
    agregados da home. Retorna quantos ajustes tiveram efeito.
    """
    m_aj = ajustes.get("mensalidades") or {}
    a_aj = ajustes.get("alunos") or {}
    aplicados = 0

    for nome, aluno in list(por_nome.items()):
        mexeu = False

        ov = a_aj.get(nome)
        if ov:
            if ov.get("ocultar"):
                por_nome.pop(nome, None)
                aplicados += 1
                continue
            for c in ("curso", "instituicao", "nivel", "percentual"):
                if c in ov:
                    aluno[c] = ov[c]
                    mexeu = True
            if mexeu:
                aplicados += 1

        mantidas = []
        for m in aluno.get("mensalidades", []):
            k = chave(m.get("ano", ""), m.get("empenho", ""))
            ov = m_aj.get(k)
            if not ov:
                mantidas.append(m)
                continue
            if ov.get("excluir"):
                aplicados += 1
                mexeu = True
                continue
            for c in CAMPOS_MENSALIDADE:
                if c in ov:
                    m[c] = ov[c]
            aplicados += 1
            mexeu = True
            mantidas.append(m)

        if len(mantidas) != len(aluno.get("mensalidades", [])):
            aluno["mensalidades"] = mantidas
        if mexeu:
            aluno["resumo"] = _resumo(aluno.get("mensalidades", []))

    return aplicados


def orfaos(por_nome: dict, ajustes: dict) -> list[str]:
    """Ajustes que não casam com nenhuma mensalidade do dataset atual.

    Acontece quando o empenho é anulado no portal ou o aluno sai do roster: o
    ajuste vira letra morta e some da vista sem este aviso.
    """
    vivos = {
        chave(m.get("ano", ""), m.get("empenho", ""))
        for a in por_nome.values() for m in a.get("mensalidades", [])
    }
    return sorted(k for k in (ajustes.get("mensalidades") or {}) if k not in vivos)
