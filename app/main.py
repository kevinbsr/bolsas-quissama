"""Bolsas Quissamã — hub de acompanhamento das bolsas de estudo.

Fonte: CSVs exportados do Portal da Transparência (movimentacao-diaria/).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from .bolsa_store import buscar, invalidar_cache, listar_nomes, pre_carregar, resumo_geral, sugerir

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = BASE_DIR / "templates" / "index.html"

# Domínio canônico (usado em SEO: canonical, OG, robots, sitemap, JSON-LD).
SITE_URL = os.getenv("SITE_URL", "https://bolsasquissama.com.br").rstrip("/")
# Em dev, desabilita totalmente o cache; em produção, usa cache normal (os assets
# têm cache-busting via ?v=). Defina BQ_ENV=dev localmente.
DEV = os.getenv("BQ_ENV", "prod").lower() == "dev"

app = FastAPI(title="Bolsas Quissamã", version="3.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def cache_headers(request, call_next):
    response = await call_next(request)
    if DEV:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.url.path.startswith("/static/"):
        # assets versionados por ?v= — podem ser cacheados com folga
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.url.path.startswith("/api/"):
        # APIs de dados não devem ser cacheadas pelo navegador
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    else:
        # HTML: cacheável, mas sempre revalidado (o HTML embute números do dataset)
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.on_event("startup")
def startup():
    pre_carregar()


def _brl(v: float) -> str:
    """Formata em Real no padrão pt-BR (R$ 1.234,56) — igual ao toLocaleString do front."""
    s = f"{(v or 0):,.2f}"
    return "R$ " + s.replace(",", "_").replace(".", ",").replace("_", ".")


def _stat_card(label: str, value: str, color: str = "") -> str:
    style = f' style="color:{color}"' if color else ""
    return (f'<div class="stat-card"><div class="label">{label}</div>'
            f'<div class="value"{style}>{value}</div></div>')


def _seo_jsonld(d: dict) -> str:
    """Dados estruturados (schema.org) com os números agregados do dataset."""
    desc = ("Portal de transparência das bolsas de estudo de ensino superior e "
            "especialização concedidas pelo município de Quissamã/RJ.")
    blocos = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Bolsas Quissamã",
            "alternateName": "Transparência das Bolsas de Estudo de Quissamã",
            "url": SITE_URL + "/",
            "inLanguage": "pt-BR",
            "description": desc,
        },
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "Bolsas de estudo de Quissamã/RJ",
            "description": desc,
            "url": SITE_URL + "/",
            "inLanguage": "pt-BR",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "temporalCoverage": str(d.get("ano_roster", "")),
            "spatialCoverage": {"@type": "Place", "name": "Quissamã, Rio de Janeiro, Brasil"},
            "variableMeasured": [
                {"@type": "PropertyValue", "name": "Bolsistas", "value": d.get("total_alunos", 0)},
                {"@type": "PropertyValue", "name": "Total empenhado (R$)", "value": d.get("total_empenhado", 0)},
                {"@type": "PropertyValue", "name": "Total pago (R$)", "value": d.get("total_pago", 0)},
                {"@type": "PropertyValue", "name": "A receber (R$)", "value": d.get("total_a_pagar", 0)},
            ],
        },
    ]
    return json.dumps(blocos, ensure_ascii=False)


def _rank_list_ssr(items: list[dict], rotulo: str) -> str:
    """Pré-renderiza a lista de rankings para que seja indexável por bots SEO."""
    top = items[:10]
    resto = items[10:]
    max_emp = max(i["empenhado"] for i in top) if top else 0

    html = []
    for idx, i in enumerate(top):
        pct = (i["empenhado"] / max_emp * 100) if max_emp > 0 else 0
        html.append(
            f'<li class="rank-item">'
            f'  <div class="rank-top">'
            f'    <span class="rank-name"><span class="rank-pos">{idx + 1}</span>{i["nome"]}</span>'
            f'    <span class="rank-val">{_brl(i["empenhado"])}</span>'
            f'  </div>'
            f'  <div class="rank-bar"><div class="rank-bar-fill" style="width:{pct:.1f}%"></div></div>'
            f'  <div class="rank-meta">{i["alunos"]} bolsista{"s" if i["alunos"] != 1 else ""} · {_brl(i["pago"])} pagos</div>'
            f'</li>'
        )
    if resto:
        emp = sum(i["empenhado"] for i in resto)
        pago = sum(i["pago"] for i in resto)
        alunos = sum(i["alunos"] for i in resto)
        html.append(
            f'<li class="rank-item rank-resto">'
            f'  <div class="rank-top">'
            f'    <span class="rank-name">+{len(resto)} {rotulo}</span>'
            f'    <span class="rank-val">{_brl(emp)}</span>'
            f'  </div>'
            f'  <div class="rank-meta">{alunos} bolsista{"s" if alunos != 1 else ""} · {_brl(pago)} pagos</div>'
            f'</li>'
        )
    return "".join(html)


@app.get("/", response_class=HTMLResponse)
def index():
    d = resumo_geral()
    ano = f" em {d['ano_roster']}" if d.get("ano_roster") else ""
    pills = f'<span class="hs-pill">{d["total_alunos"]} bolsistas{ano}</span>'
    if d.get("data_atualizacao"):
        pills += f'<span class="hs-pill">Atualizado em: {d["data_atualizacao"]}</span>'
    # Espelha exatamente o renderHomeStats() do front (evita flash/layout shift)
    cards = (
        _stat_card("Total empenhado", _brl(d["total_empenhado"]))
        + _stat_card("Total pago", _brl(d["total_pago"]), "var(--md-sys-color-success)")
        + _stat_card("A receber", _brl(d["total_a_pagar"]), "var(--md-sys-color-error)")
        + _stat_card("Mensalidades pagas", f"{d['mensalidades_pagas']} / {d['total_mensalidades']}")
    )
    html = INDEX_HTML.read_text(encoding="utf-8")
    html = (html
            .replace("__SSR_PILLS__", pills)
            .replace("__SSR_CARDS__", cards)
            .replace("__SSR_INST__", _rank_list_ssr(d["por_instituicao"], "outras instituições"))
            .replace("__SSR_CURSOS__", _rank_list_ssr(d["por_curso"], "outros cursos"))
            .replace("__SSR_JSONLD__", _seo_jsonld(d)))
    return HTMLResponse(html)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /api/\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )


@app.get("/sitemap.xml")
def sitemap():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/api/nomes")
def api_nomes():
    return listar_nomes()


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


@app.get("/api/resumo-geral")
def api_resumo_geral():
    return resumo_geral()


@app.get("/api/saude")
def saude():
    return {"status": "ok", "fonte": "bolsas"}
