"""Execução dos scripts do pipeline com log ao vivo e trava compartilhada.

Um run por vez, e o lock usado é o MESMO do cron (`flock -n /tmp/scraper.lock`):
disparar pela tela enquanto o cron roda — ou vice-versa — corromperia o dataset,
que é gravado incrementalmente a cada aluno. Quem chega depois recebe recusa,
não fila: um run de coleta pode durar horas e enfileirar só esconde o conflito.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, db

# rotulo, argv, descrição, precisa_de_rede
MODOS: dict[str, dict] = {
    "incremental": {
        "rotulo": "Incremental",
        "argv": ["scripts/coletar_bolsas.py", "--incremental"],
        "desc": "Raspa só os empenhos que faltam no cache e reparseia tudo. É o modo diário — segundos a minutos.",
        "rede": True,
    },
    "reparsear": {
        "rotulo": "Reparsear (sem rede)",
        "argv": ["scripts/coletar_bolsas.py", "--reparsear"],
        "desc": "Reaplica o parser e o CSV fresco ao cache existente. Não toca no portal — use depois de mexer no parser ou nos ajustes.",
        "rede": False,
    },
    "forcar": {
        "rotulo": "Completo (--forcar)",
        "argv": ["scripts/coletar_bolsas.py", "--forcar"],
        "desc": "Re-raspa todos os alunos do portal. Pega alunos novos no roster e re-busca o texto bruto. Pode levar ~2h.",
        "rede": True,
    },
    "pipeline": {
        "rotulo": "Pipeline completo + push",
        "argv": ["scripts/atualizar_dados.py"],
        "desc": "Baixa o CSV do ano, roda o incremental e faz commit/push — o que dispara o deploy no Render.",
        "rede": True,
    },
    "pipeline_seco": {
        "rotulo": "Pipeline sem push",
        "argv": ["scripts/atualizar_dados.py", "--skip-push"],
        "desc": "Igual ao anterior, mas para antes do commit. As mudanças ficam na árvore de trabalho para você conferir.",
        "rede": True,
    },
    "pipeline_full": {
        "rotulo": "Pipeline completo (--full) + push",
        "argv": ["scripts/atualizar_dados.py", "--full"],
        "desc": "A verificação semanal: baixa o CSV, roda o --forcar e publica. Reserve algumas horas.",
        "rede": True,
    },
}

MAX_LINHAS = 4000   # o --forcar cospe muita linha; o log inteiro vai pro SQLite


class Ocupado(RuntimeError):
    """Já existe uma execução em curso (aqui ou no cron)."""


class Runner:
    def __init__(self) -> None:
        self._lk = threading.Lock()
        self.linhas: list[str] = []
        self.proc: subprocess.Popen | None = None
        self.run_id: int | None = None
        self.modo: str | None = None
        self.inicio: float | None = None
        self.terminado: bool = True
        self.status: str = "ocioso"
        self._lock_fd: int | None = None

    # ------------------------------------------------------------- trava
    def _travar(self) -> bool:
        fd = os.open(config.LOCK, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _destravar(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def lock_livre(self) -> bool:
        """True se ninguém (nem o cron) está segurando a trava agora."""
        if self._lock_fd is not None:
            return False
        try:
            fd = os.open(config.LOCK, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return True   # sem permissão de criar o lock: não dá pra afirmar ocupado
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    # ------------------------------------------------------------- estado
    def rodando(self) -> bool:
        return not self.terminado

    def estado(self) -> dict:
        return {
            "rodando": self.rodando(),
            "modo": self.modo,
            "rotulo": MODOS.get(self.modo or "", {}).get("rotulo", self.modo),
            "run_id": self.run_id,
            "status": self.status,
            "linhas": len(self.linhas),
            "decorrido": round(time.time() - self.inicio, 1) if self.inicio and self.rodando() else None,
        }

    def desde(self, indice: int) -> list[str]:
        return self.linhas[indice:]

    # ------------------------------------------------------------- execução
    def iniciar(self, modo: str) -> int:
        if modo not in MODOS:
            raise ValueError(f"modo desconhecido: {modo}")
        with self._lk:
            if self.rodando():
                raise Ocupado("Já existe uma execução em andamento no painel.")
            if not self._travar():
                raise Ocupado(
                    f"A trava {config.LOCK} está ocupada — provavelmente o cron "
                    "está rodando agora. Espere ele terminar."
                )
            argv = [sys.executable, *MODOS[modo]["argv"]]
            self.linhas = [f"$ {' '.join(argv)}", ""]
            self.modo = modo
            self.terminado = False
            self.status = "rodando"
            self.inicio = time.time()
            self.run_id = db.abrir_run(config.RUNS_DB, modo, " ".join(argv))

        antes = _totais()
        threading.Thread(target=self._executar, args=(argv, antes), daemon=True).start()
        return self.run_id

    def _executar(self, argv: list[str], antes: dict) -> None:
        rc: int | None = None
        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            self.proc = subprocess.Popen(
                argv, cwd=str(config.BASE), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
            )
            assert self.proc.stdout is not None
            for linha in self.proc.stdout:
                self.linhas.append(linha.rstrip("\n"))
                if len(self.linhas) > MAX_LINHAS:
                    del self.linhas[: len(self.linhas) - MAX_LINHAS]
            rc = self.proc.wait()
        except Exception as e:  # noqa: BLE001
            self.linhas.append(f"[painel] falha ao executar: {type(e).__name__}: {e}")
            rc = -1
        finally:
            self.proc = None
            log = "\n".join(self.linhas)
            if self.status == "cancelado":
                status = "cancelado"
            elif rc == 0:
                status = "sucesso"
            else:
                status = "falha"
            self.status = status
            resumo = _resumir(self.modo or "", log, antes, _totais())
            self.linhas.append("")
            self.linhas.append(f"[painel] {status} (rc={rc}) — {resumo}")
            if self.run_id is not None:
                db.fechar_run(config.RUNS_DB, self.run_id, rc, status,
                              "\n".join(self.linhas), resumo)
            self._destravar()
            self.terminado = True

    def cancelar(self) -> bool:
        p = self.proc
        if not p or self.terminado:
            return False
        self.status = "cancelado"
        self.linhas.append("[painel] cancelamento solicitado; encerrando o processo…")
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.linhas.append("[painel] não encerrou em 10s; matando (SIGKILL).")
            p.kill()
        return True


# ------------------------------------------------------------------ resumo

def _totais() -> dict:
    """Fotografia barata do dataset, para dizer o que o run mudou."""
    try:
        d = json.loads(config.DATASET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    alunos = d.get("alunos", [])
    return {
        "alunos": len(alunos),
        "mensalidades": sum(len(a.get("mensalidades", [])) for a in alunos),
        "pago": round(sum((a.get("resumo") or {}).get("pago", 0) for a in alunos), 2),
        "empenhado": round(sum((a.get("resumo") or {}).get("empenhado", 0) for a in alunos), 2),
        "data": d.get("data_atualizacao", ""),
    }


def _brl(v: float) -> str:
    return "R$ " + f"{(v or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _resumir(modo: str, log: str, antes: dict, depois: dict) -> str:
    partes: list[str] = []

    if antes and depois:
        d_al = depois["alunos"] - antes["alunos"]
        d_me = depois["mensalidades"] - antes["mensalidades"]
        d_pg = round(depois["pago"] - antes["pago"], 2)
        if d_al:
            partes.append(f"{d_al:+d} aluno(s)")
        if d_me:
            partes.append(f"{d_me:+d} mensalidade(s)")
        if abs(d_pg) >= 0.01:
            partes.append(f"{'+' if d_pg > 0 else '−'}{_brl(abs(d_pg))} pagos")

    # linhas-âncora que os scripts já imprimem no fim
    for pat in (r"^\[incremental\] (\d+) empenho",
                r"^Reparse: .+$",
                r"^\d+ alunos \| \d+ mensalidades.*$",
                r"^\[\+\] (Nenhuma alteração.*|Push concluído.*)$"):
        m = re.search(pat, log, re.MULTILINE)
        if m:
            partes.append(m.group(0).strip())

    if not partes:
        partes.append("sem mudanças no dataset")
    return " · ".join(dict.fromkeys(partes))


runner = Runner()
