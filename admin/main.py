"""Painel administrativo do Bolsas Quissamã.

Roda NO CONTAINER de coleta, exposto só na rede privada (Tailscale/LAN) — não
tem autenticação por decisão explícita: a rede é a fronteira. NUNCA publique
esta porta na internet.

    uvicorn admin.main:app --host 0.0.0.0 --port 8080

Não compartilha processo nem dependências com o app público (`app.main`): este
importa pandas e Playwright indiretamente, o que o free tier do Render não
aguenta e não precisa.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import ajustes as aj
from . import config, db, roster, saude, ui
from .runner import MODOS, Ocupado, runner

app = FastAPI(title="Painel Bolsas Quissamã", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


@app.on_event("startup")
def _startup() -> None:
    config.ADMIN_DATA.mkdir(parents=True, exist_ok=True)
    db.init(config.RUNS_DB)


@app.middleware("http")
async def _sem_cache(request: Request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    # O painel mostra dado de roster; nenhum motor de busca ou embed tem o que fazer aqui.
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# --------------------------------------------------------------- utilitários

async def formulario(request: Request) -> dict[str, str]:
    """Lê um POST urlencoded sem depender de python-multipart.

    O painel só usa formulários simples; o único upload (roster) chega como
    corpo cru, então a biblioteca de multipart nunca é necessária.
    """
    corpo = (await request.body()).decode("utf-8", errors="replace")
    return dict(urllib.parse.parse_qsl(corpo, keep_blank_values=True))


def _flash(msg: str) -> str:
    return "?m=" + urllib.parse.quote(msg)


def _msg(request: Request) -> str:
    return ui.esc(request.query_params.get("m", ""))


def dataset_por_nome() -> dict:
    if not config.DATASET.exists():
        return {}
    try:
        d = json.loads(config.DATASET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {a["nome"]: a for a in d.get("alunos", [])}


# --------------------------------------------------------------- visão geral

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    ds = saude.dataset()
    prod = saude.producao()
    g = saude.git()
    dk = saude.disco()
    run = saude.ultimo_run()
    ck = saude.cache()
    cr = saude.cron()

    avisos = saude.alertas(ds, prod, g, dk, run)
    bloco_alertas = ("".join(ui.alerta(a["nivel"], a["texto"]) for a in avisos)
                     or ui.alerta("ok", "Nada exigindo atenção agora."))

    if ds.get("ok"):
        cartoes = (
            ui.cartao("Bolsistas", ui.num(ds["alunos"])) +
            ui.cartao("Mensalidades", f'{ui.num(ds["pagas"])} / {ui.num(ds["mensalidades"])}', "pagas / total") +
            ui.cartao("Empenhado", ui.brl(ds["empenhado"])) +
            ui.cartao("Pago", ui.brl(ds["pago"]), tom="bom") +
            ui.cartao("A receber", ui.brl(ds["a_pagar"]), tom="ruim") +
            ui.cartao("Atualizado em", ui.esc(ds["data_atualizacao"]),
                      f'há {ds["idade_dias"]} dia(s)' if ds.get("idade_dias") is not None else "")
        )
    else:
        cartoes = ui.cartao("Dataset", "indisponível", ui.esc(ds.get("erro", "")), tom="ruim")

    if prod.get("ok"):
        igual = prod.get("data_atualizacao") == ds.get("data_atualizacao")
        prod_html = (
            ui.cartao("Produção", "no ar", ui.esc(prod["url"]), tom="bom") +
            ui.cartao("Dataset publicado", ui.esc(prod["data_atualizacao"]),
                      "igual ao local" if igual else "DIFERENTE do local",
                      tom="bom" if igual else "atencao") +
            ui.cartao("Bolsistas em produção", ui.num(prod["alunos"]))
        )
    else:
        prod_html = ui.cartao("Produção", "sem resposta", ui.esc(prod.get("erro", "")), tom="ruim")

    git_html = (
        ui.cartao("Branch", ui.esc(g["branch"]),
                  f'{g["frente"]} à frente · {g["atras"]} atrás',
                  tom="atencao" if (g["frente"] or g["atras"]) else "") +
        ui.cartao("Árvore de trabalho", "limpa" if not g["sujo"] else f'{len(g["sujo"])} alterado(s)',
                  tom="" if not g["sujo"] else "atencao") +
        ui.cartao("HEAD", f'<span style="font-size:14px">{ui.esc(g["head"])}</span>')
    )

    if run.get("tem"):
        run_html = ui.cartao(
            "Último run pelo painel", ui.esc(run["modo"]),
            f'{ui.esc(run["quando"])} · {run["duracao_s"] or 0:.0f}s · {ui.esc(run["resumo"])}')
    else:
        run_html = ui.cartao("Último run pelo painel", "nenhum ainda",
                             "os runs do cron não passam por aqui")

    maquina = (
        run_html +
        ui.cartao("Cache de detalhes", ui.num(ck["arquivos"]), f'{ck["mb"]} MB') +
        ui.cartao("Disco", f'{dk["pct"]}%', f'{dk["usado_gb"]} de {dk["total_gb"]} GB',
                  tom="ruim" if dk["pct"] >= 85 else "atencao" if dk["pct"] >= 70 else "") +
        ui.cartao("Notificação ntfy", "configurada" if cr["ntfy"] else "ausente",
                  "variável NTFY_URL", tom="bom" if cr["ntfy"] else "atencao")
    )

    csv_linhas = [[ui.esc(c["nome"]), f'<span class="num">{c["mb"]} MB</span>', ui.esc(c["modificado"])]
                  for c in saude.csvs()]
    cron_html = (f'<pre style="font-size:12.5px;overflow-x:auto">{ui.esc(chr(10).join(cr["linhas"]))}</pre>'
                 if cr["linhas"] else '<p class="vazio">Nenhuma entrada de crontab visível para este usuário.</p>')

    corpo = (
        ui.secao("Precisa de atenção", bloco_alertas) +
        ui.secao("Dataset local", f'<div class="cartoes">{cartoes}</div>') +
        ui.secao("Produção", f'<div class="cartoes">{prod_html}</div>') +
        ui.secao("Repositório", f'<div class="cartoes">{git_html}</div>') +
        ui.secao("Máquina de coleta", f'<div class="cartoes">{maquina}</div>') +
        ui.secao("CSVs de movimentação diária",
                 ui.tabela(["Arquivo", "Tamanho", "Modificado"], csv_linhas,
                           "Nenhum CSV em movimentacao-diaria/.")) +
        ui.secao("Crontab", cron_html)
    )
    return HTMLResponse(ui.pagina("Visão geral", "/", corpo, _msg(request)))


# ------------------------------------------------------------------ pipeline

@app.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request):
    e = runner.estado()
    livre = runner.lock_livre()

    cards = ""
    for chave, m in MODOS.items():
        cards += (
            f'<div class="modo"><h3>{ui.esc(m["rotulo"])}</h3>'
            f'<p>{ui.esc(m["desc"])}</p>'
            f'<form class="disparo" method="post" action="/pipeline/run">'
            f'<input type="hidden" name="modo" value="{ui.esc(chave)}">'
            f'<button type="submit"{" disabled" if e["rodando"] else ""}>Executar</button>'
            f"</form></div>"
        )

    aviso_lock = ""
    if not livre and not e["rodando"]:
        aviso_lock = ui.alerta(
            "aviso", "A trava /tmp/scraper.lock está ocupada — o cron provavelmente "
                     "está rodando agora. Executar daqui vai ser recusado até ele terminar.")

    linhas_hist = []
    for r in db.listar(config.RUNS_DB, 25):
        tom = {"sucesso": "bom", "falha": "ruim", "cancelado": "atencao"}.get(r["status"], "")
        linhas_hist.append([
            f'<a href="/pipeline/run/{r["id"]}">#{r["id"]}</a>',
            ui.esc(MODOS.get(r["modo"], {}).get("rotulo", r["modo"])),
            ui.esc(str(r["iniciado_em"]).replace("T", " ")),
            f'<span class="num">{(r["duracao_s"] or 0):.0f}s</span>',
            ui.selo(r["status"], tom),
            ui.esc(r["resumo"]),
        ])

    console = (
        '<div class="status-run" id="statusRun">carregando…</div>'
        '<div style="margin:10px 0"><button id="btnCancelar" class="perigo" '
        'onclick="fetch(\'/pipeline/cancelar\',{method:\'POST\'})" disabled>Cancelar execução</button></div>'
        '<div id="console"></div>'
    )

    corpo = (
        aviso_lock +
        ui.secao("Executar", f'<div class="modos">{cards}</div>') +
        ui.secao("Console", console) +
        ui.secao("Histórico", ui.tabela(
            ["Run", "Modo", "Início", "Duração", "Status", "Resultado"], linhas_hist,
            "Nenhuma execução registrada pelo painel ainda."))
    )
    return HTMLResponse(ui.pagina("Pipeline", "/pipeline", corpo, _msg(request)))


@app.post("/pipeline/run")
async def pipeline_run(request: Request):
    dados = await formulario(request)
    modo = dados.get("modo", "")
    try:
        runner.iniciar(modo)
    except Ocupado as e:
        return RedirectResponse("/pipeline" + _flash(str(e)), status_code=303)
    except ValueError as e:
        return RedirectResponse("/pipeline" + _flash(str(e)), status_code=303)
    return RedirectResponse("/pipeline", status_code=303)


@app.post("/pipeline/cancelar")
def pipeline_cancelar():
    return JSONResponse({"cancelado": runner.cancelar()})


@app.get("/api/pipeline/log")
def pipeline_log(desde: int = 0):
    return JSONResponse({
        "linhas": runner.desde(desde),
        "proximo": len(runner.linhas),
        "estado": runner.estado(),
    })


@app.get("/pipeline/run/{run_id}", response_class=HTMLResponse)
def pipeline_run_detalhe(run_id: int, request: Request):
    r = db.obter(config.RUNS_DB, run_id)
    if not r:
        raise HTTPException(404, "run não encontrado")
    tom = {"sucesso": "bom", "falha": "ruim", "cancelado": "atencao"}.get(r["status"], "")
    meta = (
        ui.cartao("Modo", ui.esc(MODOS.get(r["modo"], {}).get("rotulo", r["modo"]))) +
        ui.cartao("Status", ui.selo(r["status"], tom), f'rc={r["rc"]}') +
        ui.cartao("Início", ui.esc(str(r["iniciado_em"]).replace("T", " "))) +
        ui.cartao("Duração", f'{(r["duracao_s"] or 0):.0f}s') +
        ui.cartao("Resultado", f'<span style="font-size:15px">{ui.esc(r["resumo"])}</span>')
    )
    corpo = (
        f'<p class="dica"><a href="/pipeline">← voltar ao pipeline</a></p>' +
        ui.secao(f"Run #{run_id}", f'<div class="cartoes">{meta}</div>'
                 f'<p class="dica" style="margin-top:12px"><code>{ui.esc(r["comando"])}</code></p>') +
        ui.secao("Log completo", f'<div id="logfixo" style="all:unset"></div>'
                 f'<pre style="background:#03070e;border:1px solid var(--border);border-radius:12px;'
                 f'padding:12px 14px;font-size:12.5px;overflow-x:auto;white-space:pre-wrap;'
                 f'word-break:break-word">{ui.esc(r["log"])}</pre>')
    )
    return HTMLResponse(ui.pagina(f"Run #{run_id}", "/pipeline", corpo))


# -------------------------------------------------------------------- roster

@app.get("/roster", response_class=HTMLResponse)
def roster_page(request: Request):
    upload = (
        '<p class="dica">O arquivo fica fora do Git por conter endereço residencial. '
        'O painel guarda um backup do anterior em <code>data/admin/roster-backup/</code> '
        'e nunca exibe a coluna de endereço.</p>'
        '<div class="linha-campos">'
        '<div class="campo"><label>Novo roster (CSV)</label>'
        '<input type="file" id="arqRoster" accept=".csv,text/csv"></div>'
        '<div class="campo"><button class="primario" onclick="enviarRoster()">Enviar</button></div>'
        "</div>"
        '<div id="uploadMsg" class="dica"></div>'
        "<script>"
        "async function enviarRoster(){"
        " const i=document.getElementById('arqRoster'), m=document.getElementById('uploadMsg');"
        " if(!i.files.length){m.textContent='Escolha um arquivo primeiro.';return;}"
        " m.textContent='Enviando…';"
        " const r=await fetch('/roster/upload',{method:'POST',body:i.files[0],"
        "   headers:{'Content-Type':'text/csv'}});"
        " const d=await r.json();"
        " m.textContent=d.mensagem;"
        " if(d.ok) setTimeout(()=>location.reload(),900);"
        "}"
        "</script>"
    )

    if not roster.existe():
        corpo = (
            ui.alerta("aviso",
                      "O roster não está presente. Sem ele o builder cai no fallback: "
                      "reprocessa quem já está no dataset, mas não enxerga bolsista novo.") +
            ui.secao("Enviar roster", upload)
        )
        return HTMLResponse(ui.pagina("Roster", "/roster", corpo, _msg(request)))

    d = roster.diagnostico()

    if d["erro"]:
        diag = ui.alerta("erro", f'Não consegui cruzar com o portal: {d["erro"]}')
    else:
        n_sem = len(d["sem_casamento"])
        diag = (
            f'<div class="cartoes">'
            + ui.cartao("Linhas no arquivo", ui.num(d["total"]))
            + ui.cartao("No escopo", ui.num(d["escopo"]), "Superior + Especialização")
            + ui.cartao("Casados no portal", ui.num(len(d["casados"])), tom="bom")
            + ui.cartao("Sem casamento", ui.num(n_sem), "não aparecem no site",
                        tom="ruim" if n_sem else "bom")
            + "</div>"
        )

    def form_nome(l: dict) -> str:
        return (
            f'<form method="post" action="/roster/nome" style="display:flex;gap:6px">'
            f'<input type="hidden" name="i" value="{l["i"]}">'
            f'<input type="text" name="nome" value="{ui.esc(l["nome"])}" style="min-width:220px">'
            f'<button type="submit">Salvar</button></form>'
        )

    sem_linhas = [[form_nome(l), ui.esc(l["nivel"]), ui.esc(l["curso"]), ui.esc(l["instituicao"])]
                  for l in d.get("sem_casamento", [])]
    casados_linhas = [[ui.esc(l["nome"]), ui.esc(l["canonico"]), ui.esc(l["nivel"]),
                       ui.esc(l["curso"]), ui.esc(l["instituicao"])]
                      for l in d.get("casados", [])]

    corpo = (
        ui.secao("Diagnóstico", diag) +
        ui.secao("Sem casamento no portal",
                 '<p class="dica">Estes nomes não bateram com nenhum credor. Quase sempre é '
                 'grafia: corrija aqui e rode o pipeline no modo completo para incorporá-los.</p>'
                 + ui.tabela(["Nome no roster (editável)", "Nível", "Curso", "Instituição"],
                             sem_linhas, "Todo mundo casou. 🎉")) +
        ui.secao("Casados", f'<details><summary>Ver os {len(casados_linhas)} bolsistas casados</summary>'
                 + ui.tabela(["Nome no roster", "Nome canônico no portal", "Nível", "Curso", "Instituição"],
                             casados_linhas) + "</details>") +
        ui.secao("Substituir o roster", upload)
    )
    return HTMLResponse(ui.pagina("Roster", "/roster", corpo, _msg(request)))


@app.post("/roster/nome")
async def roster_nome(request: Request):
    dados = await formulario(request)
    try:
        antigo = roster.corrigir_nome(int(dados.get("i", "-1")), dados.get("nome", ""))
    except (ValueError, OSError) as e:
        return RedirectResponse("/roster" + _flash(f"Não deu: {e}"), status_code=303)
    novo = dados.get("nome", "").strip()
    if antigo == novo:
        return RedirectResponse("/roster" + _flash("Nome inalterado."), status_code=303)
    return RedirectResponse(
        "/roster" + _flash(f"{antigo!r} → {novo!r}. Rode o pipeline completo para o portal ser reconsultado."),
        status_code=303)


@app.post("/roster/upload")
async def roster_upload(request: Request):
    conteudo = await request.body()
    if not conteudo:
        return JSONResponse({"ok": False, "mensagem": "Arquivo vazio."})
    _, problemas = roster.validar_upload(conteudo)
    bloqueantes = [p for p in problemas if not p.startswith("aviso:")]
    if bloqueantes:
        return JSONResponse({"ok": False, "mensagem": "Recusado — " + "; ".join(bloqueantes)})
    try:
        n, bkp = roster.gravar_upload(conteudo)
    except (ValueError, OSError) as e:
        return JSONResponse({"ok": False, "mensagem": f"Falha ao gravar: {e}"})
    extra = f" Backup do anterior: {bkp.name}." if bkp else ""
    aviso = (" " + "; ".join(problemas)) if problemas else ""
    return JSONResponse({"ok": True, "mensagem": f"Roster gravado com {n} linhas.{extra}{aviso}"})


# ------------------------------------------------------------------- ajustes

@app.get("/ajustes", response_class=HTMLResponse)
def ajustes_page(request: Request):
    d = aj.carregar(config.AJUSTES)
    por_nome = dataset_por_nome()
    alvo = request.query_params.get("aluno", "").strip()

    ano_form = (
        '<form method="post" action="/ajustes/ano" class="linha-campos">'
        '<div class="campo"><label>Ano do roster</label>'
        f'<input type="number" name="ano" value="{ui.esc(d.get("ano_roster") or "")}" '
        'placeholder="2026" min="2000" max="2100"></div>'
        '<div class="campo"><button type="submit">Salvar</button></div></form>'
        '<p class="dica">Entra no dataset como <code>ano_roster</code> e é o que o site '
        'mostra em “N bolsistas em ANO”. Em branco, vale a constante '
        '<code>ANO_ROSTER</code> de <code>app/bolsa_store.py</code>.</p>'
    )

    # busca de aluno
    opcoes = "".join(f'<option value="{ui.esc(n)}">' for n in sorted(por_nome))
    busca = (
        '<form method="get" action="/ajustes" class="linha-campos">'
        '<div class="campo"><label>Bolsista</label>'
        f'<input type="text" name="aluno" list="lstAlunos" value="{ui.esc(alvo)}" '
        'placeholder="comece a digitar o nome"></div>'
        '<div class="campo"><button type="submit">Abrir</button></div></form>'
        f'<datalist id="lstAlunos">{opcoes}</datalist>'
    )

    detalhe = ""
    if alvo:
        aluno = por_nome.get(alvo)
        if not aluno:
            detalhe = ui.alerta("aviso", f"{alvo!r} não está no dataset atual.")
        else:
            linhas = []
            for m in aluno.get("mensalidades", []):
                k = aj.chave(m.get("ano", ""), m.get("empenho", ""))
                ov = (d["mensalidades"] or {}).get(k, {})
                marca = ui.selo("ajustado", "atencao") if ov else ""
                tipos = "".join(
                    f'<option value="{t}"{" selected" if (ov.get("tipo") or m.get("tipo")) == t else ""}>{t}</option>'
                    for t in ("mensalidade", "conjunto", "acordo"))
                linhas.append([
                    f'<code>{ui.esc(m.get("ano"))}-{ui.esc(m.get("empenho"))}</code> {marca}',
                    f'<form method="post" action="/ajustes/mensalidade" style="display:grid;gap:6px;min-width:240px">'
                    f'<input type="hidden" name="aluno" value="{ui.esc(alvo)}">'
                    f'<input type="hidden" name="ano" value="{ui.esc(m.get("ano"))}">'
                    f'<input type="hidden" name="empenho" value="{ui.esc(m.get("empenho"))}">'
                    f'<input type="text" name="mes_referencia" placeholder="AAAA-MM" '
                    f'value="{ui.esc(ov.get("mes_referencia") or m.get("mes_referencia") or "")}">'
                    f'<select name="tipo">{tipos}</select>'
                    f'<input type="text" name="nota" placeholder="por que este ajuste?" '
                    f'value="{ui.esc(ov.get("nota") or "")}">'
                    f'<label style="text-transform:none;letter-spacing:0;display:flex;gap:6px;align-items:center">'
                    f'<input type="checkbox" name="excluir" value="1" style="width:auto"'
                    f'{" checked" if ov.get("excluir") else ""}> excluir do dataset</label>'
                    f'<button type="submit">Salvar ajuste</button></form>',
                    f'<span class="num">{ui.brl(m.get("empenhado"))}</span>',
                    f'<span class="num">{ui.brl(m.get("pago"))}</span>',
                    f'<span style="font-size:12.5px;color:var(--muted)">{ui.esc((m.get("descricao") or "")[:180])}</span>',
                ])
            detalhe = ui.secao(
                f'{alvo} — {len(aluno.get("mensalidades", []))} mensalidades',
                '<p class="dica">Só campos de <em>interpretação</em> são editáveis. Valores e datas '
                'vêm do CSV oficial e não são sobrescritos aqui — reescrevê-los falsearia a fonte.</p>'
                + ui.tabela(["Empenho", "Ajuste", "Empenhado", "Pago", "Descrição"], linhas))

    # ajustes ativos
    ativos = []
    for k, ov in sorted((d["mensalidades"] or {}).items()):
        campos = ", ".join(f"{c}={ov[c]!r}" for c in aj.CAMPOS_MENSALIDADE if c in ov)
        if ov.get("excluir"):
            campos = ("excluído" + (f" · {campos}" if campos else ""))
        ativos.append([
            f"<code>{ui.esc(k)}</code>", ui.esc(campos), ui.esc(ov.get("nota", "")),
            ui.esc(ov.get("em", "")),
            f'<form method="post" action="/ajustes/remover">'
            f'<input type="hidden" name="escopo" value="mensalidade">'
            f'<input type="hidden" name="chave" value="{ui.esc(k)}">'
            f'<button class="perigo" type="submit">Remover</button></form>',
        ])
    for nome, ov in sorted((d["alunos"] or {}).items()):
        campos = "oculto" if ov.get("ocultar") else ", ".join(
            f"{c}={ov[c]!r}" for c in ("curso", "instituicao", "nivel", "percentual") if c in ov)
        ativos.append([
            ui.esc(nome), ui.esc(campos), ui.esc(ov.get("nota", "")), ui.esc(ov.get("em", "")),
            f'<form method="post" action="/ajustes/remover">'
            f'<input type="hidden" name="escopo" value="aluno">'
            f'<input type="hidden" name="chave" value="{ui.esc(nome)}">'
            f'<button class="perigo" type="submit">Remover</button></form>',
        ])

    orf = aj.orfaos(por_nome, d)
    bloco_orf = ui.alerta("aviso", "Ajustes que não casam com nenhuma mensalidade atual (empenho "
                                   f'anulado ou aluno fora do roster): {", ".join(orf)}') if orf else ""

    aplicar = (
        '<form class="disparo" method="post" action="/ajustes/aplicar">'
        '<button class="primario" type="submit">Aplicar agora (reparsear)</button></form>'
    )

    corpo = (
        ui.alerta("info",
                  "Os ajustes são aplicados na gravação do dataset, então valem para qualquer "
                  "modo do builder e sobrevivem a reprocessamentos. Depois de editar, rode "
                  "“Aplicar agora” para vê-los no dataset local.") +
        bloco_orf +
        ui.secao("Configuração", ano_form) +
        ui.secao("Ajustar um bolsista", busca) +
        detalhe +
        ui.secao("Ajustes ativos",
                 ui.tabela(["Alvo", "Ajuste", "Nota", "Quando", ""], ativos,
                           "Nenhum ajuste manual registrado."),
                 aplicar)
    )
    return HTMLResponse(ui.pagina("Ajustes", "/ajustes", corpo, _msg(request)))


@app.post("/ajustes/ano")
async def ajustes_ano(request: Request):
    dados = await formulario(request)
    d = aj.carregar(config.AJUSTES)
    bruto = (dados.get("ano") or "").strip()
    if not bruto:
        d["ano_roster"] = None
    else:
        try:
            d["ano_roster"] = int(bruto)
        except ValueError:
            return RedirectResponse("/ajustes" + _flash("Ano inválido."), status_code=303)
    aj.salvar(config.AJUSTES, d)
    return RedirectResponse("/ajustes" + _flash("Ano do roster salvo."), status_code=303)


@app.post("/ajustes/mensalidade")
async def ajustes_mensalidade(request: Request):
    dados = await formulario(request)
    ano, empenho = dados.get("ano", ""), dados.get("empenho", "")
    if not ano or not empenho:
        return RedirectResponse("/ajustes" + _flash("Empenho não identificado."), status_code=303)

    mes = (dados.get("mes_referencia") or "").strip()
    campos: dict = {
        "mes_referencia": mes or None,
        "tipo": (dados.get("tipo") or "").strip() or None,
        "excluir": dados.get("excluir") == "1",
    }
    if mes and not (len(mes) == 7 and mes[4] == "-" and mes[:4].isdigit() and mes[5:].isdigit()):
        return RedirectResponse("/ajustes" + _flash(f"Mês {mes!r} fora do formato AAAA-MM."), status_code=303)

    d = aj.carregar(config.AJUSTES)
    k = aj.registrar_mensalidade(d, ano, empenho, campos, (dados.get("nota") or "").strip())
    aj.salvar(config.AJUSTES, d)
    volta = "/ajustes?aluno=" + urllib.parse.quote(dados.get("aluno", ""))
    sep = "&m="
    return RedirectResponse(volta + sep + urllib.parse.quote(
        f"Ajuste de {k} salvo. Rode “Aplicar agora” para refletir no dataset."), status_code=303)


@app.post("/ajustes/remover")
async def ajustes_remover(request: Request):
    dados = await formulario(request)
    d = aj.carregar(config.AJUSTES)
    ok = aj.remover(d, dados.get("escopo", ""), dados.get("chave", ""))
    aj.salvar(config.AJUSTES, d)
    return RedirectResponse(
        "/ajustes" + _flash("Ajuste removido." if ok else "Ajuste não encontrado."), status_code=303)


@app.post("/ajustes/aplicar")
def ajustes_aplicar():
    try:
        runner.iniciar("reparsear")
    except Ocupado as e:
        return RedirectResponse("/ajustes" + _flash(str(e)), status_code=303)
    return RedirectResponse("/pipeline", status_code=303)


@app.get("/api/saude")
def api_saude():
    return {"status": "ok", "painel": "bolsas-quissama"}
