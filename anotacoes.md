# Anotações e Gerenciamento do Sistema

Este manual reúne as instruções de operação, infraestrutura e fluxo de atualização do pipeline de dados do Portal de Bolsas Quissamã.

---

## 1. Atualização da Lista de Alunos (Roster)

O arquivo `relacao-bolsistas_padronizado.csv` (roster) contém a lista de alunos de Ensino Superior e Especialização que possuem o benefício de reembolso.

### Privacidade de Dados
> [!IMPORTANT]
> O arquivo de roster original contém dados pessoais dos estudantes (como endereços residenciais). Por esse motivo, ele está listado no `.gitignore` e **nunca deve ser enviado para o repositório público do GitHub**.

### Comportamento do Scraper (Fallback Automático)
O script de scraping foi projetado para ser robusto em ambientes de produção (como o servidor de scraper no Proxmox):
1. **Com Roster Presente**: O script lê `relacao-bolsistas_padronizado.csv`, filtra os níveis incluídos e busca novas informações no portal para cada aluno listado.
2. **Sem Roster Presente (Mecanismo de Fallback)**: Se o CSV não for encontrado no servidor, o script emitirá um aviso e carregará a lista de alunos do dataset público atualizado [app/dados/bolsas_publicas.json](file:///home/kevin/Work/personal/bolsas-quissama/app/dados/bolsas_publicas.json).
   * **Vantagem**: O cron job diário continua funcionando em produção mesmo sem o arquivo original do roster, atualizando pagamentos e empenhos de todos os alunos cadastrados anteriormente.

### Atualização Manual do Roster
Se houver novos bolsistas integrando o programa ou se o roster for alterado, você deve realizar o upload manual do arquivo da sua máquina de desenvolvimento local para o servidor de produção usando `scp`:

```bash
# Copiar o arquivo atualizado para o servidor Proxmox LXC
scp relacao-bolsistas_padronizado.csv root@scraper-bolsas:/app/bolsas-quissama/
```

Após copiar o arquivo, reexecute o script no servidor para forçar o scraping dos novos alunos:
```bash
python scripts/atualizar_dados.py
```

---

## 2. Infraestrutura do Servidor de Scraper

A execução periódica do Playwright requer um navegador completo rodando em background (Chromium), o que consome memória e recursos não suportados na hospedagem grátis do Render. A infraestrutura de coleta consiste em:

*   **Virtualização**: Rodando em um contêiner LXC Debian 12 no Proxmox VE local (host: `ragnar`, VM ID: `102`, hostname: `scraper-bolsas`).
*   **Gerenciamento**: A infraestrutura do LXC é definida e provisionada via Terraform no diretório [infra/](file:///home/kevin/Work/personal/bolsas-quissama/infra/).

---

## 3. Configuração do Script e Cron Job

O pipeline de dados é atualizado automaticamente todos os dias às **06:00** através de um cron job no contêiner LXC.

### Instalação no Servidor (Setup Inicial)
No contêiner `/app/bolsas-quissama/`:
```bash
# Instalar dependências de coleta (Playwright, Pandas, etc.)
pip install -r requirements-coleta.txt

# Instalar o navegador Chromium gerenciado pelo Playwright
playwright install chromium
```

### Configuração do Cron Job
Abra as tarefas agendadas do sistema no servidor:
```bash
crontab -e
```
Adicione a seguinte linha (ajustando o caminho para o seu ambiente virtual do python):
```cron
0 6 * * * cd /app/bolsas-quissama && /app/bolsas-quissama/.venv/bin/python scripts/atualizar_dados.py >> /var/log/bolsas_update.log 2>&1
```

### Logs de Automação
A saída de cada execução diária é salva no arquivo de log do sistema:
*   `/var/log/bolsas_update.log`

---

## 4. Deploy e Monitoramento

```
[Home Server LXC] ───(git push se houver dados novos)───► [GitHub] ───(Auto-Deploy)───► [Render Production]
```

### Auto-Deploy
O deploy da aplicação FastAPI é hospedado no **Render**. O arquivo [render.yaml](file:///home/kevin/Work/personal/bolsas-quissama/render.yaml) configura o auto-deploy. Assim que o scraper diário executa na LXC e detecta alterações, ele faz o `git push` das movimentações atualizadas. O Render detecta o novo commit no GitHub e faz o deploy do app automaticamente.

### Monitoramento de Disponibilidade (UptimeRobot)
Como a aplicação no Render é desligada após períodos de inatividade no plano gratuito, utilizamos um monitor do **UptimeRobot** para manter o serviço sempre ativo.
*   **Tipo**: HTTPS
*   **Frequência**: A cada 5 minutos
*   **URL**: `https://bolsasquissama.com.br` (ou `https://bolsas-quissama.onrender.com`)
