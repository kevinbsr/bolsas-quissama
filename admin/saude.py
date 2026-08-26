"""Checagens de saúde do sistema, para o dashboard.

Responde as perguntas que hoje só se responde por SSH: o dataset está velho? a
produção está servindo o que acabei de publicar? o cron rodou? o disco do
container aguenta? sobrou algum aluno sem casar com o portal?
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from . import config, db

TIMEOUT = 8


def _run_git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(config.BASE),
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_data(s: str) -> datetime.datetime | None:
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def dataset() -> dict:
    if not config.DATASET.exists():
        return {"ok": False, "erro": "app/dados/bolsas_publicas.json não existe"}
    try:
        d = json.loads(config.DATASET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "erro": f"dataset ilegível: {e}"}

    alunos = d.get("alunos", [])
    mens = [m for a in alunos for m in a.get("mensalidades", [])]
    dt = _parse_data(d.get("data_atualizacao", ""))
    return {
        "ok": True,
        "data_atualizacao": d.get("data_atualizacao", ""),
        "idade_dias": (datetime.datetime.now() - dt).days if dt else None,
        "alunos": len(alunos),
        "mensalidades": len(mens),
        "pagas": sum(1 for m in mens if (m.get("pago") or 0) > 0),
        "empenhado": round(sum((a.get("resumo") or {}).get("empenhado", 0) for a in alunos), 2),
        "pago": round(sum((a.get("resumo") or {}).get("pago", 0) for a in alunos), 2),
        "a_pagar": round(sum((a.get("resumo") or {}).get("a_pagar", 0) for a in alunos), 2),
        "tamanho_kb": round(config.DATASET.stat().st_size / 1024),
    }


def producao() -> dict:
    url = f"{config.PROD_URL}/api/resumo-geral"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bolsas-admin/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {
            "ok": True, "url": config.PROD_URL,
            "data_atualizacao": d.get("data_atualizacao", ""),
            "alunos": d.get("total_alunos", 0),
            "pago": d.get("total_pago", 0),
        }
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
        return {"ok": False, "url": config.PROD_URL, "erro": f"{type(e).__name__}: {e}"}


_ULTIMO_FETCH = 0.0
INTERVALO_FETCH = 300   # s


def git() -> dict:
    global _ULTIMO_FETCH
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    sujo = [l for l in _run_git("status", "--porcelain").splitlines() if l.strip()]
    # `git fetch` fala com a rede; sem esta janela o dashboard travaria alguns
    # segundos a cada F5. O "atrás/à frente" tolera estar 5 min defasado.
    agora = time.monotonic()
    if agora - _ULTIMO_FETCH > INTERVALO_FETCH:
        _ULTIMO_FETCH = agora
        try:
            subprocess.run(["git", "fetch", "--quiet", "origin", branch or "master"],
                           cwd=str(config.BASE), capture_output=True, timeout=45)
        except (OSError, subprocess.SubprocessError):
            pass
    contagem = _run_git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch or 'master'}")
    frente = atras = 0
    if contagem and "\t" in contagem:
        try:
            frente, atras = (int(x) for x in contagem.split("\t"))
        except ValueError:
            pass
    return {
        "branch": branch or "?",
        "head": _run_git("log", "-1", "--format=%h %ad %s", "--date=short"),
        "sujo": sujo,
        "frente": frente,
        "atras": atras,
    }


def cache() -> dict:
    if not config.CACHE.exists():
        return {"arquivos": 0, "mb": 0.0}
    arquivos = list(config.CACHE.glob("*.json"))
    return {
        "arquivos": len(arquivos),
        "mb": round(sum(f.stat().st_size for f in arquivos) / 1_048_576, 1),
    }


def csvs() -> list[dict]:
    if not config.CSV_DIR.exists():
        return []
    out = []
    for f in sorted(config.CSV_DIR.glob("*.csv")):
        st = f.stat()
        out.append({
            "nome": f.name,
            "mb": round(st.st_size / 1_048_576, 1),
            "modificado": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })
    return out


def disco() -> dict:
    total, usado, livre = shutil.disk_usage(config.BASE)
    return {
        "usado_gb": round(usado / 1_073_741_824, 1),
        "total_gb": round(total / 1_073_741_824, 1),
        "pct": round(usado / total * 100) if total else 0,
    }


def cron() -> dict:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        linhas = [l for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith("#")]
    except (OSError, subprocess.SubprocessError):
        linhas = []
    return {"linhas": linhas, "ntfy": bool(os.getenv("NTFY_URL", "").strip())}


def ultimo_run() -> dict:
    u = db.ultimo_sucesso(config.RUNS_DB)
    if not u:
        return {"tem": False}
    try:
        quando = datetime.datetime.fromisoformat(u["iniciado_em"])
        dias = (datetime.datetime.now() - quando).days
    except (ValueError, TypeError):
        quando, dias = None, None
    return {
        "tem": True, "id": u["id"], "modo": u["modo"], "resumo": u["resumo"],
        "quando": quando.strftime("%d/%m/%Y %H:%M") if quando else u["iniciado_em"],
        "dias": dias, "duracao_s": u["duracao_s"],
    }


def alertas(ds: dict, prod: dict, g: dict, dk: dict, run: dict) -> list[dict]:
    """Só o que exige ação. Um dashboard que alerta sobre tudo não alerta nada."""
    out: list[dict] = []

    def add(nivel: str, texto: str) -> None:
        out.append({"nivel": nivel, "texto": texto})

    if not ds.get("ok"):
        add("erro", ds.get("erro", "dataset indisponível"))
    elif (ds.get("idade_dias") or 0) > config.ALERTA_DIAS_SEM_RUN:
        add("aviso", f"O dataset local tem {ds['idade_dias']} dias "
                     f"(atualizado em {ds['data_atualizacao']}). O cron rodou?")

    if not prod.get("ok"):
        add("erro", f"Produção não respondeu: {prod.get('erro', '?')}")
    elif ds.get("ok") and prod.get("data_atualizacao") != ds.get("data_atualizacao"):
        add("aviso", f"Produção está servindo {prod['data_atualizacao']!r} e aqui o "
                     f"dataset é {ds['data_atualizacao']!r} — falta publicar ou o deploy não subiu.")

    if g.get("atras"):
        add("aviso", f"O repositório local está {g['atras']} commit(s) atrás de "
                     f"origin/{g['branch']}. Rode um git pull antes de publicar.")
    if g.get("frente"):
        add("info", f"{g['frente']} commit(s) local(is) ainda não enviados.")
    if g.get("sujo"):
        add("info", f"{len(g['sujo'])} arquivo(s) modificados na árvore de trabalho.")

    if dk.get("pct", 0) >= 85:
        add("erro", f"Disco em {dk['pct']}% ({dk['usado_gb']} de {dk['total_gb']} GB).")
    elif dk.get("pct", 0) >= 70:
        add("aviso", f"Disco em {dk['pct']}%.")

    if run.get("tem") and (run.get("dias") or 0) > config.ALERTA_DIAS_SEM_RUN:
        add("aviso", f"O último run bem-sucedido pelo painel foi há {run['dias']} dias.")

    return out
