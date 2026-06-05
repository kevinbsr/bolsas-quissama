# Bolsas Quissamã

Portal público para os **alunos bolsistas** de Quissamã/RJ acompanharem, mês a
mês, o pagamento da sua bolsa de estudos — com dados oficiais do Portal da
Transparência da prefeitura.

**Demo:** https://bolsas-quissama.onrender.com

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
uvicorn app.main:app --reload            # http://127.0.0.1:8000
```

## Atualizando os dados (pipeline offline)

O scraping exige um navegador real (Playwright + Chromium do sistema), então roda
**fora** do app — localmente ou num cron na Oracle Always Free (VM de verdade;
o tier grátis do Render não roda navegador).

```bash
pip install -r requirements-coleta.txt   # pandas, playwright, pypdf
python scripts/coletar_bolsas.py         # reconstrói app/dados/bolsas_publicas.json
# --limite N  → processa só os N primeiros alunos (validação)
```

Os detalhes são cacheados em `data/cache/detalhe/`, então reexecuções só buscam o
que falta. Depois, faça commit do `bolsas_publicas.json` atualizado.

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
