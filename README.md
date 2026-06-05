# Bolsas Quissamã

Portal público para os **alunos bolsistas** de Quissamã/RJ acompanharem, mês a
mês, o pagamento da sua bolsa de estudos — com dados oficiais do Portal da
Transparência da prefeitura.

**Site Oficial:** https://bolsasquissama.com.br

> Cobertura: bolsistas do **Ensino Superior** e **Especialização** (que são
> reembolsados individualmente e, por isso, têm empenho no nome do aluno). O
> Ensino Médio é pago de forma coletiva à instituição e não tem registro
> individual no portal.

---

## Como funciona

```
relacao-bolsistas (roster)  ─┐
                             ├─►  scripts/coletar_bolsas.py  ─►  app/dados/bolsas_publicas.json  ─►  app (FastAPI)
movimentacao-diaria/*.csv  ──┘        (Playwright + portal)            (dataset público)               busca por nome
```

1. **Roster** — lista oficial dos bolsistas (a prefeitura publica em PDF;
   convertida para `relacao-bolsistas_padronizado.csv`).
2. **Coleta** — para cada aluno, o `coletar_bolsas.py` consulta o Portal da
   Transparência, abre o detalhe de cada empenho e extrai o **mês da
   mensalidade** (do texto do empenho) e a classificação (Função=Educação +
   Ação=Programa de Bolsas). Valores/datas/status vêm dos CSVs de Movimentação
   Diária. Resultado: `app/dados/bolsas_publicas.json`.
3. **App** — lê só esse dataset (leve, sem pandas) e mostra, por aluno, as
   mensalidades organizadas por mês de referência.

---

## Rodando o app

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # só fastapi + uvicorn
export BQ_ENV=dev                        # Desabilita o cache no navegador para desenvolvimento local
uvicorn app.main:app --reload            # http://127.0.0.1:8000
```

## Atualizando os dados (pipeline offline)

O scraping exige um navegador real (Playwright + Chromium do sistema), então roda **fora** do app de produção (o tier grátis do Render não suporta navegadores headless complexos). 

A arquitetura de atualização consiste em rodar o pipeline offline em um **home server** (ou máquina local) e enviar as atualizações automaticamente para o GitHub, o que dispara o deploy automático no Render.

### Automação Diária (Recomendado)

Criamos o script `scripts/atualizar_dados.py` para fazer todo o processo de uma vez:
1. Acessa o Portal da Transparência de Quissamã e faz o download do CSV de Movimentação Diária mais recente para o ano corrente.
2. Executa o parser/scraper (`coletar_bolsas.py`) para atualizar `app/dados/bolsas_publicas.json` e cachear novos empenhos em `data/cache/detalhe/`.
3. Se houver novas informações ou atualizações nos pagamentos, faz o commit e o push automático para o GitHub.

Para configurar no cron do seu home server para rodar diariamente às **06:00**:

```bash
# Instale as dependências na máquina/cron local
pip install -r requirements-coleta.txt
playwright install chromium

# Edite o crontab (crontab -e)
0 6 * * * cd /caminho/para/bolsas-quissama && /caminho/para/.venv/bin/python scripts/atualizar_dados.py >> /var/log/bolsas_update.log 2>&1
```

### Execução Manual do Scraper

Se preferir rodar apenas o scraper/parser manualmente sem fazer download do CSV ou commit/push:

```bash
python scripts/coletar_bolsas.py         # reconstrói app/dados/bolsas_publicas.json
# --limite N  → processa só os N primeiros alunos (validação)
```

Os detalhes continuam cacheados em `data/cache/detalhe/` offline, garantindo que execuções futuras sejam incrementais e muito rápidas.

---

## Estrutura

```
app/main.py              FastAPI: /api/buscar, /api/sugerir, /api/nomes
app/bolsa_store.py       loader do dataset (runtime, sem pandas)
app/csv_loader.py        parsing dos CSVs de Movimentação Diária (usado só pelo builder)
app/dados/bolsas_publicas.json   dataset público servido pelo app
scripts/coletar_bolsas.py        builder: roster + portal → dataset
movimentacao-diaria/*.csv        export bruto do portal (entrada do builder)
static/ templates/       interface mobile-first (Chart.js)
```

---

## Privacidade

O dataset publicado (`app/dados/bolsas_publicas.json`) contém apenas dados
públicos do portal: nome do aluno, curso/instituição/percentual da bolsa e os
empenhos (valores, datas, mês). **Não** inclui endereço nem CPF. O roster de
entrada (`relacao-bolsistas_padronizado.csv` / PDF), que traz endereços, fica
fora do versionamento (`.gitignore`).

---

## Deploy

`render.yaml` (Render) já configurado — deploy automático a cada push na `master`.
O app serve o dataset estático; para atualizar, rode o pipeline offline e faça commit
do JSON.

---

## Otimizações de SEO & Meta-tags

O portal foi projetado para conformidade com boas práticas de SEO e compartilhamento social:
*   **SSR (Server-Side Rendering)**: Rankings e métricas gerais são renderizados em Python no backend e inseridos diretamente no HTML inicial para completa indexação por robôs de busca.
*   **Metadados Sociais**: Suporte completo a tags Open Graph (Facebook/WhatsApp) e Twitter Cards, referenciando a imagem social oficial do portal (`static/og-image.png`).
*   **Dados Estruturados**: Injeção automática de JSON-LD (`WebSite` e `Dataset`) especificando o escopo espacial, temporal e licença de uso dos dados de transparência pública.
*   **Robots & Sitemap**: Rotas dinâmicas em `/robots.txt` e `/sitemap.xml` para controlar o crawling de buscadores, mantendo as páginas individuais protegidas (bloqueadas para rastreamento) conforme regras de privacidade, e apenas a página inicial ativa para indexação.
