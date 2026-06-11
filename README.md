# Bolsas Quissamã

Portal público de transparência que permite aos **alunos bolsistas** de Quissamã/RJ
acompanharem, mês a mês, o pagamento da sua bolsa de estudos — usando exclusivamente
dados oficiais do Portal da Transparência da prefeitura.

🔗 **Produção:** https://bolsasquissama.com.br

O município repassa as bolsas com atraso recorrente e o portal oficial é difícil de
navegar (consulta por empenho, sem visão por aluno). Este projeto coleta esses dados,
reorganiza por estudante e por mês de referência, e os expõe numa interface de busca
simples — além de métricas agregadas (total pago, atrasos, prazos do processo).

> **Escopo:** bolsistas do **Ensino Superior** e **Especialização**, que são reembolsados
> individualmente e, por isso, têm empenho no nome do aluno. O Ensino Médio é pago de
> forma coletiva à instituição e não possui registro individual no portal.

---

## Destaques técnicos

- **Pipeline de dados desacoplado do app.** A coleta exige um navegador real (o portal
  usa reCAPTCHA invisível), então roda *offline* num home server e publica um JSON estático.
  O app de produção (Render free tier, sem navegador) só lê esse JSON — leve e sem `pandas`.
- **Scraping resiliente com Playwright.** O portal renderiza a grade de resultados mas
  nunca emite o evento de "navegação concluída", o que trava o auto-wait do Playwright. A
  coleta contorna isso com clique tolerante a timeout + polling do DOM, e re-tenta consultas
  até cobrir todos os empenhos esperados (anti-flakiness de rede).
- **Cache incremental por empenho.** Cada detalhe de empenho é cacheado em disco; o modo
  `--incremental` raspa apenas o que é novo e reprocessa o resto sem rede — um run diário
  leva segundos/minutos em vez de ~2h.
- **Casamento de nomes tolerante a erros.** O roster oficial (PDF) e o portal divergem em
  acentuação/grafia; os nomes são casados por subconjunto de tokens com *fallback* fuzzy
  (`difflib`, corte ≥ 0,88) para corrigir typos como "Sllva" → "Silva".
- **SSR + SEO.** Rankings e métricas são renderizados no servidor (Python) e injetados no
  HTML inicial; há Open Graph, Twitter Cards, JSON-LD (`Dataset`/`WebSite`), `robots.txt` e
  `sitemap.xml` dinâmicos — com as páginas individuais bloqueadas para indexação.
- **Privacidade por design.** O dataset publicado nunca inclui endereço ou CPF; as fontes
  com dados pessoais ficam fora do versionamento (ver [Privacidade](#privacidade)).

**Stack:** Python · FastAPI · Playwright · pandas (só na coleta) · JS vanilla + Chart.js ·
Render (deploy) · Terraform (provisão do home server).

---

## Arquitetura

```
relacao-bolsistas (roster, PDF→CSV)  ─┐
                                      ├─►  scripts/coletar_bolsas.py  ─►  app/dados/bolsas_publicas.json  ─►  app (FastAPI)
movimentacao-diaria/*.csv  ───────────┘     (Playwright + portal)              (dataset público)              busca por nome
   (export do portal)                       valores/datas ← CSV                  + cache em data/cache/         + métricas (SSR)
                                            mês/classificação ← detalhe
```

1. **Roster** — lista oficial dos bolsistas (a prefeitura publica em PDF; convertida
   manualmente para `relacao-bolsistas_padronizado.csv`). Define *quem* é bolsista.
2. **Coleta** — para cada aluno, o `coletar_bolsas.py` consulta o portal, abre o detalhe de
   cada empenho e extrai o **mês de referência** e a classificação (Função = Educação +
   Ação = Programa de Bolsas). **Valores, datas e status** vêm dos CSVs de Movimentação
   Diária. Resultado: `app/dados/bolsas_publicas.json`.
3. **App** — lê apenas esse dataset e mostra, por aluno, as mensalidades organizadas por
   mês, mais um painel de indicadores agregados.

---

## Rodando o app localmente

Requer apenas o dataset versionado (`app/dados/bolsas_publicas.json`) — **não** precisa de
navegador nem da etapa de coleta.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # fastapi + uvicorn

export BQ_ENV=dev                        # desabilita o cache de navegador em dev
uvicorn app.main:app --reload            # http://127.0.0.1:8000
```

### Principais rotas

| Rota | Descrição |
|---|---|
| `GET /` | Página inicial (HTML com métricas via SSR) |
| `GET /api/buscar?nome=` | Mensalidades de um aluno |
| `GET /api/sugerir?q=` | Autocomplete de nomes |
| `GET /api/nomes` | Lista de nomes disponíveis |
| `GET /api/resumo-geral` | Indicadores agregados |
| `GET /api/saude` | Health check |
| `POST /api/recarregar?secret=` | Recarrega o dataset em produção sem redeploy (exige `RELOAD_SECRET`) |

---

## Atualizando os dados

A coleta usa Playwright + Chromium do sistema, então roda **fora** do app de produção.
Instale as dependências extras na máquina de coleta:

```bash
pip install -r requirements-coleta.txt   # + pandas, playwright, pypdf
playwright install chromium              # ou use o Chromium do sistema (/usr/bin/chromium)
```

### Pipeline completo (download + coleta + publicação)

`scripts/atualizar_dados.py` executa o fluxo de ponta a ponta: baixa o CSV de Movimentação
Diária do ano corrente, roda a coleta, e — havendo mudanças — faz commit e push para o
GitHub (o que dispara o deploy automático no Render).

```bash
python scripts/atualizar_dados.py                 # diário: rápido (incremental) + push
python scripts/atualizar_dados.py --full          # semanal: re-raspa todos (--forcar, ~2h)
python scripts/atualizar_dados.py --skip-push      # faz tudo, menos commit/push (dry-run)
python scripts/atualizar_dados.py --ano 2025       # coleta outro ano
```

Notifica sucesso/falha via [ntfy.sh](https://ntfy.sh) se a variável `NTFY_URL` estiver
definida no ambiente.

### Só o coletor (sem download de CSV nem push)

`scripts/coletar_bolsas.py` reconstrói o dataset a partir dos CSVs já presentes em
`movimentacao-diaria/` e do cache de detalhes.

| Comando | O que faz |
|---|---|
| `python scripts/coletar_bolsas.py` | Reconstrói, **pulando** alunos já no dataset |
| `… --incremental` | Raspa só empenhos novos (fora do cache) + reprocessa tudo. **Modo diário** |
| `… --forcar` | Re-raspa **todos** os alunos do portal (verificação completa) |
| `… --reparsear` | Sem rede: reaplica o parser ao cache existente (após melhorar o parser) |
| `… --limite N` | Processa só os N primeiros alunos (validação rápida) |
| `… --alunos "Fulano;Beltrano"` | Coleta só os nomes informados |

Os detalhes ficam cacheados em `data/cache/detalhe/`, garantindo que execuções futuras
sejam incrementais e rápidas.

### Atualizando a lista de bolsistas (roster)

Quando a prefeitura divulga uma nova lista (novo edital/ano):

1. Substitua o PDF oficial (`lista-bolsistas-2026.pdf`) e gere o CSV padronizado
   `relacao-bolsistas_padronizado.csv` com as colunas: **Nível, Nº, Aluno, Endereço,
   Percentual, Curso, Instituição, Valor**. (Ambos ficam fora do Git por conterem endereços.)
2. Só entram alunos cujo **Nível** começa com `Superior` ou `Especialização`
   (`NIVEIS_INCLUSOS` em `coletar_bolsas.py`).
3. Rode `python scripts/coletar_bolsas.py --forcar` para reconstruir o dataset do zero.
   Verifique a saída: alunos "sem casamento" indicam nomes que não bateram com o portal
   (corrija a grafia no CSV) — o app só exibe quem casa com um credor do portal.

> Sem o roster, o coletor cai num *fallback* que reaproveita os nomes do dataset já
> publicado — útil para reprocessar, mas não adiciona alunos novos.

---

## Automação

Em produção, o pipeline roda num container LXC (home server) via cron:

```cron
# verificação rápida diária (incremental)
0 3,8,14,20 * * * .../python scripts/atualizar_dados.py
# verificação completa semanal (--forcar), domingo de madrugada
0 4 * * 0        .../python scripts/atualizar_dados.py --full
```

Um `flock` compartilhado impede que dois runs se sobreponham, e o cold-start do Render free
tier é mantido vivo com um ping externo (UptimeRobot).

---

## Estrutura

```
app/main.py                      FastAPI: rotas, SSR, SEO
app/bolsa_store.py               loader do dataset em runtime (sem pandas)
app/csv_loader.py                parsing dos CSVs de Movimentação Diária (só no builder)
app/dados/bolsas_publicas.json   dataset público servido pelo app  (versionado)
scripts/coletar_bolsas.py        builder: roster + portal → dataset
scripts/atualizar_dados.py       pipeline ponta a ponta (download → coleta → push)
movimentacao-diaria/*.csv        export bruto do portal (entrada do builder)
static/ · templates/             interface mobile-first (Chart.js)
infra/                           Terraform do home server de coleta
render.yaml                      configuração de deploy (Render)
```

---

## Privacidade

O dataset publicado (`app/dados/bolsas_publicas.json`) contém **apenas dados públicos** do
portal: nome do aluno, curso/instituição/percentual da bolsa e os empenhos (valores, datas,
mês de referência). **Não** inclui endereço nem CPF. As fontes de entrada que trazem
endereços (`lista-bolsistas-2026.pdf` e `relacao-bolsistas_padronizado.csv`) ficam fora do
versionamento (`.gitignore`). Detalhes legais em [`LEGAL.md`](LEGAL.md).

---

## Deploy

`render.yaml` configura o serviço no Render com **deploy automático a cada push na
`master`**. O app serve o dataset estático; para atualizar os dados, rode o pipeline
offline e faça commit do JSON (ou chame `POST /api/recarregar` com o `RELOAD_SECRET` para
recarregar sem um novo deploy).
