# Bolsas Quissamã

Portal público para acompanhamento dos empenhos e pagamentos de bolsas de estudo do município de Quissamã/RJ, com dados oficiais extraídos do Portal da Transparência.

**Demo:** https://bolsas-quissama.onrender.com

---

## O que o portal exibe

- **Valor a receber** — saldo oficial baseado em empenhos liquidados e não pagos
- **Extrato de empenhos** — cada processo com status (Empenhado / Liquidado / Pago), valores e datas
- **Gráficos** — fluxo financeiro e frequência de empenhos por ano
- **Busca por nome** — autocomplete com os credores presentes nos dados oficiais

---

## Fonte dos dados

Os dados vêm dos CSVs exportados pelo Portal da Transparência de Quissamã (Cidade360/IPM):

**Portal → Despesas → Movimentação Diária → Exportar Dados**

Os arquivos exportados devem ser salvos em `movimentacao-diaria/` com o ano no nome do arquivo (ex: `2025.csv`). O sistema detecta o ano automaticamente.

---

## Rodando localmente

```bash
git clone https://github.com/SEU_USUARIO/bolsas-quissama.git
cd bolsas-quissama

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload
# acesse http://127.0.0.1:8000
```

---

## Atualizando os dados

1. Exporte o CSV do Portal da Transparência
2. Salve em `movimentacao-diaria/` (ex: `2026.csv`)
3. Chame o endpoint de recarga:

```bash
curl -X POST "https://bolsas-quissama.onrender.com/api/recarregar?secret=SEU_RELOAD_SECRET"
```

O `RELOAD_SECRET` está configurado nas variáveis de ambiente do Render.

---

## Estrutura

```
app/
  main.py          API FastAPI — endpoints de busca, sugestão e recarga
  csv_loader.py    Leitura, parsing e cache dos CSVs em memória
static/
  style.css        Interface Material 3, mobile-first
  app.js           Lógica do frontend (busca, gráficos, tema)
templates/
  index.html       Página principal
movimentacao-diaria/
  2022.csv         CSVs exportados do Portal da Transparência
  2023.csv
  ...
render.yaml        Configuração de deploy (Render.com)
```

---

## API

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/sugerir?q=nome` | Autocomplete de credores |
| `GET` | `/api/buscar?nome=nome` | Empenhos de um credor |
| `POST` | `/api/recarregar?secret=xxx` | Invalida o cache de CSVs |
| `GET` | `/api/saude` | Health check |

---

## Deploy

O projeto está configurado para o [Render.com](https://render.com) via `render.yaml`. Qualquer push na branch principal dispara um novo deploy automaticamente.

**Variáveis de ambiente necessárias:**

| Variável | Descrição |
|----------|-----------|
| `RELOAD_SECRET` | Token para proteger o endpoint `/api/recarregar` |

---

## Privacidade

Os dados exibidos (nome e CPF do credor) são públicos no Portal da Transparência.
