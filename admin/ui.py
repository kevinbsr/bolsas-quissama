"""Montagem do HTML do painel.

Sem motor de template: o app principal já constrói HTML com f-strings
(`_stat_card` em app/main.py) e o painel tem quatro páginas — introduzir Jinja
aqui adicionaria uma dependência ao container só para isso.
"""

from __future__ import annotations

import html

ABAS = (
    ("/", "Visão geral"),
    ("/pipeline", "Pipeline"),
    ("/roster", "Roster"),
    ("/ajustes", "Ajustes"),
)


def esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def brl(v: float | None) -> str:
    return "R$ " + f"{(v or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def num(v: int | float | None) -> str:
    return f"{(v or 0):,}".replace(",", ".")


def pagina(titulo: str, ativo: str, corpo: str, aviso: str = "") -> str:
    nav = "".join(
        f'<a href="{esc(href)}" class="aba{" ativa" if href == ativo else ""}">{esc(rot)}</a>'
        for href, rot in ABAS
    )
    banner = f'<div class="flash">{aviso}</div>' if aviso else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(titulo)} · Painel Bolsas Quissamã</title>
<link rel="stylesheet" href="/static/admin.css?v=1">
</head>
<body>
<header class="topo">
  <div class="marca"><span class="ponto"></span>Painel · Bolsas Quissamã</div>
  <nav>{nav}</nav>
</header>
<main>{banner}{corpo}</main>
<script src="/static/admin.js?v=1" defer></script>
</body>
</html>"""


def cartao(rotulo: str, valor: str, nota: str = "", tom: str = "") -> str:
    cls = f" {tom}" if tom else ""
    extra = f'<div class="c-nota">{nota}</div>' if nota else ""
    return (f'<div class="cartao{cls}"><div class="c-rotulo">{esc(rotulo)}</div>'
            f'<div class="c-valor">{valor}</div>{extra}</div>')


def secao(titulo: str, conteudo: str, acoes: str = "") -> str:
    return (f'<section class="secao"><div class="s-topo"><h2>{esc(titulo)}</h2>'
            f'<div class="s-acoes">{acoes}</div></div>{conteudo}</section>')


def tabela(colunas: list[str], linhas: list[list[str]], vazio: str = "Nada aqui.") -> str:
    if not linhas:
        return f'<p class="vazio">{esc(vazio)}</p>'
    th = "".join(f"<th>{esc(c)}</th>" for c in colunas)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in ln) + "</tr>" for ln in linhas)
    return f'<div class="rolagem"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def alerta(nivel: str, texto: str) -> str:
    icone = {"erro": "✕", "aviso": "!", "info": "i", "ok": "✓"}.get(nivel, "i")
    return f'<div class="alerta {esc(nivel)}"><span class="a-ic">{icone}</span><span>{esc(texto)}</span></div>'


def selo(texto: str, tom: str = "") -> str:
    return f'<span class="selo {esc(tom)}">{esc(texto)}</span>'
