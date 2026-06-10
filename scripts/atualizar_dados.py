"""Script de automação diária para o home server.

Este script:
1. Faz o download do CSV de Movimentação Diária do ano corrente do portal.
2. Executa o scraper `coletar_bolsas.py` para processar e extrair os detalhes.
3. Se houver alterações nos arquivos de dados, realiza o commit e push para o GitHub.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

HOST = "https://webapp1-quissama.cidade360.cloud"
URL = HOST + "/pronimtb/index.asp?acao=3&item=11"
CHROMIUM = "/usr/bin/chromium"
DATASET = BASE / "app" / "dados" / "bolsas_publicas.json"

# Notificações via ntfy.sh — defina NTFY_URL no ambiente do cron, ex.:
#   NTFY_URL=https://ntfy.sh/<um-topico-secreto-seu>
# Sem isso (ex.: testes locais), as notificações são silenciosamente ignoradas.
NTFY_URL = os.getenv("NTFY_URL", "").strip()


def notificar(mensagem: str, titulo: str = "Bolsas Quissama", prioridade: str = "default", tags: str = "") -> None:
    """Envia um push via ntfy.sh. No-op se NTFY_URL não estiver definida.
    OBS: o header Title deve ser ASCII (emojis vão no corpo / via `tags`)."""
    if not NTFY_URL:
        print("[!] NTFY_URL não definida; notificação ignorada.")
        return
    try:
        req = urllib.request.Request(
            NTFY_URL, data=mensagem.encode("utf-8"), method="POST",
            headers={"Title": titulo, "Priority": prioridade, "Tags": tags},
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[!] Falha ao enviar notificação ntfy: {e}")


def _data_atualizacao() -> str:
    try:
        return json.loads(DATASET.read_text(encoding="utf-8")).get("data_atualizacao", "?")
    except Exception:
        return "?"

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
        # domcontentloaded (não networkidle): a página tem scripts de reCAPTCHA que mantêm
        # a rede "ocupada", então networkidle fica lento/trava. O form já existe no DOM.
        pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        pg.select_option("select[name=cmbAno]", ano)
        pg.fill("input[name=txtDataInicial]", f"01/01/{ano}")
        pg.fill("input[name=txtDataFinal]", f"31/12/{ano}")
        
        print("[*] Enviando consulta (clicando em 'Gerar')...")
        try:
            pg.click("input[value='Gerar']", timeout=10000)
        except Exception:
            # Depois do 'Gerar' (reCAPTCHA invisível) a página renderiza a grade mas NÃO
            # emite o evento de "navegação concluída" que o Playwright espera — então o
            # auto-wait do clique estoura. Ignoramos e validamos a grade por polling.
            print("[!] Clique não 'concluiu navegação' (esperado); validando a grade por polling...")
        print("[*] Aguardando a grade carregar (botão de export aparecer)...")
        # polling com .count() não dispara auto-wait de navegação (que travaria aqui)
        grade_ok = False
        for _ in range(90):
            if pg.locator("#btExportarCSV").count() > 0:
                grade_ok = True
                break
            pg.wait_for_timeout(1000)
        if not grade_ok:
            sys.exit("A grade não carregou após o 'Gerar' (timeout de 90s).")
        pg.wait_for_timeout(1000)

        print("[*] Iniciando download (clicando em '#btExportarCSV')...")
        try:
            with pg.expect_download(timeout=180000) as dl_info:
                try:
                    pg.click("#btExportarCSV", timeout=10000)
                except Exception:
                    pass  # nav-wait pode estourar; o expect_download captura o download
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
            b.close()
            sys.exit(f"Erro ao baixar o CSV: {e}")

        b.close()

def run_coleta() -> None:
    print("[*] Executando scripts/coletar_bolsas.py --forcar (re-coleta TODOS os alunos)...")
    # --forcar é essencial: sem ele o modo padrão PULA quem já está no dataset e nada
    # de pagamento/empenho novo dos alunos existentes é atualizado. Com --forcar o
    # scraper re-raspa os 97 do portal e reconstrói com o CSV fresco (não depende de
    # cache pré-existente). Timeout maior (30 min) porque agora raspa todo mundo.
    try:
        res = subprocess.run([sys.executable, "scripts/coletar_bolsas.py", "--forcar"],
                             cwd=str(BASE), capture_output=False, timeout=2700)
        if res.returncode != 0:
            sys.exit(f"coletar_bolsas.py falhou (rc={res.returncode}).")
    except subprocess.TimeoutExpired:
        sys.exit("coletar_bolsas.py --forcar expirou o limite de 45 minutos.")
    print("[+] Dataset público atualizado com sucesso!")

def git_sync() -> None:
    """Converge com a master remota ANTES de gerar dados. O repositório também recebe
    commits manuais do desenvolvedor; sem isso, o push no fim seria rejeitado
    (non-fast-forward) e a produção nunca atualizaria. Tree limpo aqui (início do run)."""
    print("[*] Sincronizando com a master remota (git pull --rebase origin master)...")
    res = subprocess.run(["git", "pull", "--rebase", "origin", "master"], cwd=str(BASE))
    if res.returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=str(BASE))
        sys.exit("Falha no 'git pull --rebase'; repositório precisa de atenção manual.")


def git_commit_push(ano: str, skip_push: bool) -> str:
    """Retorna um resumo do que aconteceu (usado na notificação de sucesso)."""
    print("[*] Verificando alterações no git...")
    res = subprocess.run(["git", "status", "--porcelain"], cwd=str(BASE), capture_output=True, text=True)
    if not res.stdout.strip():
        print("[+] Nenhuma alteração de arquivo no git.")
        return "sem alterações"

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
        return "sem alterações nos dados"

    if skip_push:
        # dry-run de verdade: NÃO commita (evita poluir o git do container com commits
        # locais que depois conflitam no 'git pull --rebase'). As mudanças ficam no tree.
        print(f"[*] --skip-push ativo: alterações detectadas em {alterados}, mas NÃO vou commitar/push.")
        return f"alterações detectadas (não commitado; --skip-push): {', '.join(alterados)}"

    print(f"[*] Adicionando arquivos ao git: {alterados}")
    subprocess.run(["git", "add"] + alterados, cwd=str(BASE), check=True)

    commit_msg = f"data: atualização automática diária ({ano})"
    print(f"[*] Fazendo commit: {commit_msg}")
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(BASE), check=True)

    print("[*] Fazendo push para origin master (gatilho para auto-deploy no Render)...")
    subprocess.run(["git", "push", "origin", "master"], cwd=str(BASE), check=True)
    print("[+] Push concluído! Render deve iniciar o deploy em breve.")
    return "dados novos enviados para produção"


def main() -> None:
    ano_atual = str(datetime.date.today().year)
    p = argparse.ArgumentParser(description="Script de automação diária do pipeline de bolsas (home server)")
    p.add_argument("--ano", default=ano_atual, help=f"Ano a coletar (padrão: {ano_atual})")
    p.add_argument("--skip-push", action="store_true", help="Faz a coleta e commit, mas pula o git push")
    args = p.parse_args()

    csv_saida = BASE / "movimentacao-diaria" / f"{args.ano}.csv"

    try:
        if not args.skip_push:
            git_sync()
        download_csv(args.ano, csv_saida)
        run_coleta()
        status = git_commit_push(args.ano, args.skip_push)
        notificar(
            f"✅ Run OK ({args.ano}) — {status}.\nDataset: {_data_atualizacao()}.",
            titulo="Bolsas Quissama - scraper OK",
            tags="white_check_mark",
        )
    except SystemExit as e:
        # falhas controladas (sys.exit("mensagem")) — e.code carrega a mensagem
        if e.code not in (0, None):
            notificar(
                f"❌ Run FALHOU ({args.ano}):\n{e.code}",
                titulo="Bolsas Quissama - scraper FALHOU",
                prioridade="high", tags="rotating_light",
            )
        raise
    except BaseException as e:
        import traceback
        notificar(
            f"❌ Run FALHOU ({args.ano}): {type(e).__name__}: {e}\n\n{traceback.format_exc()[-1200:]}",
            titulo="Bolsas Quissama - scraper FALHOU",
            prioridade="high", tags="rotating_light",
        )
        raise


if __name__ == "__main__":
    main()
