"""Bolsas Quissamã — hub de acompanhamento das bolsas de estudo.

Fonte: CSVs exportados do Portal da Transparência (movimentacao-diaria/).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .csv_loader import buscar, invalidar_cache, pre_carregar, sugerir

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Bolsas Quissamã", version="3.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.on_event("startup")
def startup():
    pre_carregar()


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/sugerir")
def api_sugerir(q: str = Query(..., min_length=2)):
    return sugerir(q)


@app.get("/api/buscar")
def api_buscar(nome: str = Query(..., min_length=2)):
    try:
        return JSONResponse(buscar(nome))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@app.post("/api/recarregar")
def api_recarregar(secret: str = Query(default="")):
    """Invalida o cache de CSVs. Protegido por RELOAD_SECRET se definido."""
    token = os.getenv("RELOAD_SECRET", "")
    if token and secret != token:
        raise HTTPException(403, "Acesso negado")
    invalidar_cache()
    return {"ok": True}


@app.get("/api/saude")
def saude():
    return {"status": "ok", "fonte": "csv"}
