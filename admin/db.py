"""Histórico de execuções do pipeline (SQLite local do container).

Hoje a única memória de um run é a notificação ntfy (efêmera) e o
/var/log/scraper.log (append-only, sem estrutura). Aqui cada execução vira uma
linha consultável: quando, quanto durou, o que mudou, e o log inteiro.

Fica em data/admin/ — gitignored, é estado da máquina de coleta, não do projeto.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    modo         TEXT    NOT NULL,
    comando      TEXT    NOT NULL,
    origem       TEXT    NOT NULL DEFAULT 'painel',
    iniciado_em  TEXT    NOT NULL,
    terminado_em TEXT,
    duracao_s    REAL,
    rc           INTEGER,
    status       TEXT    NOT NULL DEFAULT 'rodando',
    resumo       TEXT    NOT NULL DEFAULT '',
    log          TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_inicio ON runs(iniciado_em DESC);
"""


def _conn(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(caminho, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init(caminho: Path) -> None:
    with _conn(caminho) as c:
        c.executescript(SCHEMA)


def abrir_run(caminho: Path, modo: str, comando: str, origem: str = "painel") -> int:
    with _conn(caminho) as c:
        cur = c.execute(
            "INSERT INTO runs (modo, comando, origem, iniciado_em) VALUES (?,?,?,?)",
            (modo, comando, origem, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def fechar_run(caminho: Path, run_id: int, rc: int | None, status: str,
               log: str, resumo: str = "") -> None:
    fim = datetime.datetime.now()
    with _conn(caminho) as c:
        ini = c.execute("SELECT iniciado_em FROM runs WHERE id=?", (run_id,)).fetchone()
        dur = None
        if ini:
            try:
                dur = round((fim - datetime.datetime.fromisoformat(ini["iniciado_em"])).total_seconds(), 1)
            except ValueError:
                dur = None
        c.execute(
            "UPDATE runs SET terminado_em=?, duracao_s=?, rc=?, status=?, log=?, resumo=? WHERE id=?",
            (fim.isoformat(timespec="seconds"), dur, rc, status, log, resumo, run_id),
        )


def listar(caminho: Path, limite: int = 30) -> list[dict]:
    with _conn(caminho) as c:
        rows = c.execute(
            "SELECT id, modo, origem, iniciado_em, terminado_em, duracao_s, rc, status, resumo "
            "FROM runs ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(r) for r in rows]


def obter(caminho: Path, run_id: int) -> dict | None:
    with _conn(caminho) as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(r) if r else None


def ultimo_sucesso(caminho: Path) -> dict | None:
    with _conn(caminho) as c:
        r = c.execute(
            "SELECT * FROM runs WHERE status='sucesso' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(r) if r else None
