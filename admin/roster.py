"""Leitura, diagnóstico e edição do roster de bolsistas.

O roster (`relacao-bolsistas_padronizado.csv`) é a lista oficial: define QUEM é
bolsista. É a única entrada do pipeline que o operador edita à mão, e é onde
mora o problema recorrente — nomes que não casam com o credor do portal por
diferença de grafia. Hoje isso só aparece no stdout de um run e se perde; aqui
vira uma tabela onde dá para consertar a grafia na hora.

O arquivo contém ENDEREÇO RESIDENCIAL dos alunos. Este módulo lê a coluna para
não destruí-la ao regravar o CSV, mas nunca a devolve para a interface.
"""

from __future__ import annotations

import csv
import datetime
import importlib.util
import io
import shutil
from pathlib import Path

from . import config

COLUNAS_OBRIGATORIAS = ("Nível", "Aluno")
COLUNAS_ESPERADAS = ("Nível", "Nº", "Aluno", "Endereço", "Percentual", "Curso", "Instituição", "Valor")
OCULTAS = ("Endereço",)   # nunca sai deste módulo
NIVEIS_INCLUSOS = ("Superior", "Especialização")

_builder = None


def builder():
    """Carrega scripts/coletar_bolsas.py como módulo (é script, não pacote).

    Reaproveitar `mapear_canonico` de lá em vez de reimplementar o casamento é
    deliberado: a regra de subconjunto de tokens já teve um bug que contou
    R$ 245 mil em dobro, e duas cópias dela divergiriam em silêncio.
    """
    global _builder
    if _builder is None:
        caminho = config.BASE / "scripts" / "coletar_bolsas.py"
        spec = importlib.util.spec_from_file_location("bq_coletar_bolsas", caminho)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"não consegui carregar {caminho}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _builder = mod
    return _builder


def existe() -> bool:
    return config.ROSTER.exists()


def _ler_bruto() -> tuple[list[str], list[dict]]:
    with open(config.ROSTER, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def linhas() -> list[dict]:
    """Linhas do roster sem as colunas sensíveis, com o filtro de nível marcado."""
    if not existe():
        return []
    _, rows = _ler_bruto()
    out = []
    for i, row in enumerate(rows):
        nivel = (row.get("Nível") or "").strip()
        out.append({
            "i": i,
            "nome": (row.get("Aluno") or "").strip(),
            "nivel": nivel,
            "curso": (row.get("Curso") or "").strip(),
            "instituicao": (row.get("Instituição") or "").strip(),
            "percentual": (row.get("Percentual") or "").strip(),
            "valor": (row.get("Valor") or "").strip(),
            "no_escopo": any(nivel.startswith(n) for n in NIVEIS_INCLUSOS),
        })
    return out


def diagnostico() -> dict:
    """Cruza o roster com os credores do portal e aponta quem não casou.

    Custa alguns segundos na primeira chamada: carrega os ~26 MB de CSV de
    movimentação com pandas (depois fica em lru_cache).
    """
    todas = linhas()
    no_escopo = [l for l in todas if l["no_escopo"] and l["nome"]]
    if not no_escopo:
        return {"total": len(todas), "escopo": 0, "casados": [], "sem_casamento": [], "erro": None}

    try:
        b = builder()
        alunos = [{"nome_roster": l["nome"]} for l in no_escopo]
        b.mapear_canonico(alunos)
    except Exception as e:  # noqa: BLE001
        return {"total": len(todas), "escopo": len(no_escopo), "casados": [],
                "sem_casamento": [], "erro": f"{type(e).__name__}: {e}"}

    casados, sem = [], []
    for l, a in zip(no_escopo, alunos):
        item = {**l, "canonico": a.get("nome_canonico")}
        (casados if item["canonico"] else sem).append(item)
    return {"total": len(todas), "escopo": len(no_escopo),
            "casados": casados, "sem_casamento": sem, "erro": None}


def _backup() -> Path | None:
    if not existe():
        return None
    carimbo = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    pasta = config.ADMIN_DATA / "roster-backup"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"roster-{carimbo}.csv"
    # Um upload seguido de uma correção de nome cai no mesmo segundo e o segundo
    # backup sobrescreveria o primeiro — justamente o que se queria guardar.
    n = 1
    while destino.exists():
        destino = pasta / f"roster-{carimbo}-{n}.csv"
        n += 1
    shutil.copy2(config.ROSTER, destino)
    return destino


def corrigir_nome(indice: int, novo: str) -> str:
    """Reescreve o campo Aluno de uma linha, preservando todas as colunas."""
    novo = (novo or "").strip()
    if not novo:
        raise ValueError("o nome não pode ficar vazio")
    campos, rows = _ler_bruto()
    if not (0 <= indice < len(rows)):
        raise ValueError(f"linha {indice} não existe no roster")
    antigo = (rows[indice].get("Aluno") or "").strip()
    if antigo == novo:
        return antigo
    _backup()
    rows[indice]["Aluno"] = novo
    with open(config.ROSTER, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(rows)
    return antigo


def validar_upload(conteudo: bytes) -> tuple[list[str], list[str]]:
    """Devolve (colunas, problemas) sem gravar nada."""
    problemas: list[str] = []
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        return [], ["não consegui decodificar o arquivo (tentei utf-8 e latin-1)"]

    r = csv.DictReader(io.StringIO(texto))
    campos = list(r.fieldnames or [])
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in campos]
    if faltando:
        problemas.append(f"colunas obrigatórias ausentes: {', '.join(faltando)}")
    rows = list(r)
    if not rows:
        problemas.append("o arquivo não tem nenhuma linha de dados")
    no_escopo = sum(
        1 for row in rows
        if any((row.get("Nível") or "").strip().startswith(n) for n in NIVEIS_INCLUSOS)
    )
    if rows and not no_escopo:
        problemas.append(
            "nenhuma linha tem Nível começando com 'Superior' ou 'Especialização' — "
            "o builder ignoraria o arquivo inteiro"
        )
    ausentes = [c for c in COLUNAS_ESPERADAS if c not in campos]
    if ausentes and not faltando:
        problemas.append(f"aviso: colunas esperadas ausentes (o builder usa o padrão): {', '.join(ausentes)}")
    return campos, problemas


def gravar_upload(conteudo: bytes) -> tuple[int, Path | None]:
    """Grava o roster novo em UTF-8, guardando backup do anterior."""
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("não consegui decodificar o arquivo")

    bkp = _backup()
    config.ROSTER.write_text(texto, encoding="utf-8")
    return len(linhas()), bkp
