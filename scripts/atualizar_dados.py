"""Script de automação diária para o home server.

Este script:
1. Faz o download do CSV de Movimentação Diária do ano corrente do portal.
2. Executa o scraper `coletar_bolsas.py` para processar e extrair os detalhes.
3. Se houver alterações nos arquivos de dados, realiza o commit e push para o GitHub.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

HOST = "https://webapp1-quissama.cidade360.cloud"
URL = HOST + "/pronimtb/index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"

def download_csv(ano: str, saida: Path) -> None:
    print(f"[*] Iniciando download do CSV de Movimentação Diária para o ano {ano}...")
    saida.parent.mkdir(parents=True, exist_ok=True)
    
    with sync_playwright() as pw:
        # Tenta usar o Chromium do sistema
        try:
            b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        except Exception:
            # Fallback para o Chromium padrão do Playwright se o do sistema falhar/não existir
            print(f"[!] Aviso: Não foi possível iniciar o Chromium em '{CHROMIUM}'. Tentando padrão do Playwright...")
            b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            
        pg = b.new_page()
        pg.goto(URL, wait_until="networkidle", timeout=60000)
        pg.select_option("select[name=cmbAno]", ano)
        pg.fill("input[name=txtDataInicial]", f"01/01/{ano}")
        pg.fill("input[name=txtDataFinal]", f"31/12/{ano}")
        
        print("[*] Enviando consulta (clicando em 'Gerar')...")
        pg.click("input[value='Gerar']")
        pg.wait_for_timeout(6000)
        
        print("[*] Iniciando download (clicando em '#btExportarCSV')...")
        try:
            with pg.expect_download(timeout=180000) as dl_info:
                pg.click("#btExportarCSV")
            dl_info.value.save_as(str(saida))
            
            # Limpa o rodapé dinâmico do PRONIM (com timestamp) para evitar commits falsos
            try:
                conteudo = saida.read_text(encoding="latin-1")
                linhas = conteudo.splitlines()
                if linhas and "PRONIM" in linhas[-1]:
                    linhas.pop()
                    saida.write_text("\n".join(linhas) + "\n", encoding="latin-1")
                    print("[*] Rodapé dinâmico do PRONIM removido para evitar commits espúrios.")
            except Exception as e:
                print(f"[!] Aviso ao limpar o rodapé do CSV: {e}")

            tamanho = saida.stat().st_size
            print(f"[+] Download concluído com sucesso: {saida} ({tamanho:,} bytes)")
        except Exception as e:
            print(f"[-] Erro ao baixar o CSV: {e}")
            sys.exit(1)
            
        b.close()

def run_coleta() -> None:
    print("[*] Executando scripts/coletar_bolsas.py para processar e atualizar o dataset público...")
    res = subprocess.run([sys.executable, "scripts/coletar_bolsas.py"], cwd=str(BASE), capture_output=False)
    if res.returncode != 0:
        print("[-] Erro ao executar scripts/coletar_bolsas.py")
        sys.exit(res.returncode)
    print("[+] Dataset público atualizado com sucesso!")

def git_commit_push(ano: str, skip_push: bool) -> None:
    print("[*] Verificando alterações no git...")
    # Verifica status
    res = subprocess.run(["git", "status", "--porcelain"], cwd=str(BASE), capture_output=True, text=True)
    if not res.stdout.strip():
        print("[+] Nenhuma alteração de arquivo no git.")
        return
        
    print("[*] Estado do git:")
    print(res.stdout)
    
    # Verifica se os arquivos de dados foram modificados
    arquivos_interesse = [f"movimentacao-diaria/{ano}.csv", "app/dados/bolsas_publicas.json"]
    alterados = []
    for linha in res.stdout.splitlines():
        # formato do git status --porcelain: ' M caminho' ou '?? caminho'
        caminho = linha[3:].strip()
        if caminho in arquivos_interesse:
            alterados.append(caminho)
            
    if not alterados:
        print("[+] Nenhuma alteração relevante nos arquivos de dados.")
        return
        
    print(f"[*] Adicionando arquivos ao git: {alterados}")
    subprocess.run(["git", "add"] + alterados, cwd=str(BASE), check=True)
    
    commit_msg = f"data: atualização automática diária ({ano})"
    print(f"[*] Fazendo commit: {commit_msg}")
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(BASE), check=True)
    
    if skip_push:
        print("[*] Parâmetro --skip-push ativo. O push para o GitHub foi ignorado.")
    else:
        print("[*] Fazendo push para origin master (gatilho para auto-deploy no Render)...")
        subprocess.run(["git", "push", "origin", "master"], cwd=str(BASE), check=True)
        print("[+] Push concluído! Render deve iniciar o deploy em breve.")

def main() -> None:
    ano_atual = str(datetime.date.today().year)
    p = argparse.ArgumentParser(description="Script de automação diária do pipeline de bolsas (home server)")
    p.add_argument("--ano", default=ano_atual, help=f"Ano a coletar (padrão: {ano_atual})")
    p.add_argument("--skip-push", action="store_true", help="Faz a coleta e commit, mas pula o git push")
    args = p.parse_args()
    
    csv_saida = BASE / "movimentacao-diaria" / f"{args.ano}.csv"
    
    download_csv(args.ano, csv_saida)
    run_coleta()
    git_commit_push(args.ano, args.skip_push)

if __name__ == "__main__":
    main()
