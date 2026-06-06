# Anotações, Infraestrutura e Gerenciamento do Sistema

Este documento serve como manual operacional e documentação oficial da arquitetura do projeto **Bolsas Quissamã**, integrando as especificações declarativas de infraestrutura, detalhes de segurança e o pipeline automatizado de dados no servidor local.

---

## 1. Camada de Infraestrutura como Código (IaC)

A infraestrutura do contêiner de coleta é definida de forma declarativa via **Terraform** no diretório [infra/](file:///home/kevin/Work/personal/bolsas-quissama/infra/) usando o provider `bpg/proxmox`.

*   **Host Físico:** Proxmox VE local (host: `ragnar`, datastore: `local` / `local-lvm`).
*   **Template de Sistema:** Download automatizado do template oficial do **Debian 12 Standard** (`.tar.zst`).
*   **Recurso de Contêiner (`proxmox_virtual_environment_container`):**
    *   **VM ID:** `102` (hostname: `scraper-bolsas`).
    *   **Segurança:** Configurado como **`unprivileged = true`** (isolando o root do container do root do host físico).
    *   **Recursos:** 1 Core de CPU, 1 GB de Memória RAM (0 swap), 8 GB de armazenamento alocado.
    *   **Rede:** Interface `veth0` atrelada à bridge padrão `vmbr0`, com IP obtido dinamicamente via DHCP.
    *   **Acesso:** Injeção automática da chave pública SSH em tempo de provisionamento, sem senhas.

---

## 2. Configuração do Ambiente e Dependências (LXC)

O ecossistema interno do contêiner Debian 12 foi configurado para suportar o scraper headless:

1.  **Ambiente Virtual Python (Venv):** Inicializado em `/app/bolsas-quissama/` para isolamento de pacotes e dependências (Pandas, Playwright).
2.  **Playwright Headless:** Instalado com dependências de sistema nativas do Linux para renderização em background sem interface gráfica ativa:
    ```bash
    pip install -r requirements-coleta.txt
    playwright install --with-deps chromium
    ```
3.  **Segurança de Comunicação (Deploy Key):** Geramos uma chave SSH dedicada (`id_ed25519`) dentro do container e a vinculamos como **Deploy Key** (com permissão de escrita) no repositório do GitHub. Isso restringe o acesso em caso de comprometimento da máquina.
4.  **Git Config:** A identidade de commit do Git no servidor está configurada como:
    ```bash
    git config --global user.email "kb.kevinbenevides@gmail.com"
    git config --global user.name "Kevin Benevides"
    ```

---

## 3. Pipeline de Dados e Lista de Alunos (Roster)

```
relacao-bolsistas (roster)  ─┐
                             ├─►  scripts/coletar_bolsas.py  ─►  app/dados/bolsas_publicas.json
movimentacao-diaria/*.csv  ──┘        (Playwright + portal)            (dataset público)
```

### O Roster de Entrada
O arquivo `relacao-bolsistas_padronizado.csv` contém o mapeamento de cursos/instituições e endereços. 
> [!IMPORTANT]
> O arquivo de roster original contém dados pessoais residenciais. Por esse motivo, ele está listado no `.gitignore` e **nunca deve ser enviado para o repositório público**.

### Mecanismo de Fallback Automático
O scraper [scripts/coletar_bolsas.py](file:///home/kevin/Work/personal/bolsas-quissama/scripts/coletar_bolsas.py) possui um fallback inteligente:
1.  **Com Roster Presente:** Varre o portal para todos os alunos filtrados da planilha.
2.  **Sem Roster Presente:** Se o arquivo `.csv` estiver ausente (padrão após um novo clone), o script emite um aviso e lê as informações básicas de nível, curso e instituição diretamente da base consolidada existente [app/dados/bolsas_publicas.json](file:///home/kevin/Work/personal/bolsas-quissama/app/dados/bolsas_publicas.json).
    *   **Vantagem:** O pipeline do cron job continua atualizando pagamentos de todos os alunos existentes no piloto automático sem requerer arquivos privados no servidor.

### Atualização Manual do Roster
Para cadastrar novos bolsistas integrando o programa:
```bash
# Copiar o roster atualizado da máquina local para o contêiner LXC
scp relacao-bolsistas_padronizado.csv root@scraper-bolsas:/app/bolsas-quissama/
```

---

## 4. Automação e Resiliência (Cron & `flock`)

Para lidar com quedas de energia e oscilações de internet, configuramos janelas de execução múltiplas no Crontab do contêiner (`crontab -e`):

```cron
0 3,8,14,20 * * * /usr/bin/flock -n /tmp/scraper.lock /app/bolsas-quissama/venv/bin/python /app/bolsas-quissama/scripts/atualizar_dados.py >> /var/log/scraper.log 2>&1
```

*   **Janelas Periódicas (3h, 8h, 14h, 20h):** Garante a execução logo no próximo horário útil caso o servidor estivesse desligado durante a madrugada.
*   **Controle de Concorrência com `flock`:** Evita travamentos concorrentes e corrupção de arquivos. O utilitário `/usr/bin/flock` cria uma trava atômica no arquivo `/tmp/scraper.lock`. Se um disparo anterior ainda estiver rodando (por lentidão do portal ou timeout longo), a nova execução é abortada silenciosamente sem iniciar processos duplicados.
*   **Prevenção de Commits Espúrios (Normalização do CSV):** O script [scripts/atualizar_dados.py](file:///home/kevin/Work/personal/bolsas-quissama/scripts/atualizar_dados.py) remove a última linha do CSV baixado (rodapé com carimbo dinâmico do PRONIM). Assim, se não houver novas movimentações de fato, o Git reconhece o arquivo como inalterado e pula a etapa de commit e push.
*   **Timeout de Proteção:** O subprocesso de coleta possui timeout interno de **10 minutos** (`timeout=600`) para forçar o fechamento do Chromium caso ocorra algum congelamento a nível de rede no Playwright.

---

## 5. Histórico de Manutenção e Troubleshooting (Gestão de Crise)

*   **Falha de Espaço em Disco no Host:** Durante o provisionamento IaC inicial, o Proxmox acusou erro HTTP 500 (`write to temporary file failed`).
*   **Diagnóstico:** A partição raiz (`/dev/mapper/pve-root`) do Proxmox estava com **100% de uso (94GB ocupados)**.
*   **Causa Raiz:** A pasta local `/tank/backups/kevin` estava alocando 68GB de backups redundantes diretamente no disco raiz do host físico.
*   **Resolução:** Limpeza manual e expurgo dos diretórios, reduzindo o uso para **29% (64GB livres)**. Também foi removido o template do Debian corrompido pela metade e executado um `terraform refresh` para recuperar o estado e aplicar a infraestrutura com sucesso.

---

## 6. Deploy e Monitoramento

*   **Hospedagem:** FastAPI rodando no **Render**. O auto-deploy automático é acionado em cada push na branch `master` do GitHub.
*   **Keep-Alive (UptimeRobot):** Como o Render suspende instâncias no plano gratuito por inatividade, um monitor HTTP no **UptimeRobot** dispara requisições a cada 5 minutos para `https://bolsasquissama.com.br` mantendo o site ativo e com respostas rápidas para os cidadãos.
