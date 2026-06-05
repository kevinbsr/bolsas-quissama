"""Exporta empenhos do Portal da Transparência de Quissamã (Cidade360/IPM) em XML.

Navega a consulta pública de Empenhos (acao=3&item=11), aplica os filtros de ano
(e opcionalmente nome do credor) e aciona o botão "Exportar XML", salvando o
arquivo resultante. O XML traz, por empenho, a classificação estruturada
(Função/SubFunção/Programa/Ação) e a descrição livre (campo Item) — base para
identificar bolsas de estudo e o mês da mensalidade.

Uso:
    # export de um ano inteiro (todos os credores)
    python scripts/exportar_empenhos.py --ano 2025
    # export filtrado por nome (validação)
    python scripts/exportar_empenhos.py --ano 2025 --nome "FULANO DE TAL"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

HOST = "https://webapp1-quissama.cidade360.cloud"
URL = HOST + "/pronimtb/index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"
EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"


def exportar(ano: str, nome: str | None, saida: Path) -> Path:
    saida.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        pg.goto(URL, wait_until="networkidle", timeout=60000)
        pg.select_option("select[name=cmbAno]", ano)
        pg.fill("input[name=txtDataInicial]", f"01/01/{ano}")
        pg.fill("input[name=txtDataFinal]", f"31/12/{ano}")
        if nome:
            pg.fill("input[name=txtNomeFornecedor]", nome)
        # roda a consulta primeiro — o botão "Exportar XML" só aparece com resultados
        pg.click("input[value='Gerar']")
        pg.wait_for_timeout(6000)
        with pg.expect_download(timeout=180000) as dl_info:
            pg.click("input[name=exportarXML]")
        dl_info.value.save_as(str(saida))
        b.close()
    return saida


def main() -> None:
    p = argparse.ArgumentParser(description="Exporta empenhos (XML) do portal de Quissamã")
    p.add_argument("--ano", required=True)
    p.add_argument("--nome", default=None, help="filtra por nome do credor (opcional)")
    p.add_argument("--saida", default=None, help="caminho do XML de saída")
    args = p.parse_args()

    saida = Path(args.saida) if args.saida else EXPORT_DIR / f"empenhos-{args.ano}.xml"
    out = exportar(args.ano, args.nome, saida)
    tamanho = out.stat().st_size
    print(f"Gravado: {out}  ({tamanho:,} bytes)")


if __name__ == "__main__":
    main()
