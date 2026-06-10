const COR = {
  brand:    "#7ec2ff",
  success:  "#34d399",
  danger:   "#fb7185",
  muted:    "#98b8d4",
  chart1:   "rgba(126, 194, 255, 0.85)",
  chart2:   "rgba(126, 194, 255, 0.45)",
  chart3:   "rgba(52,  211, 153, 0.78)",
  chart4:   "rgba(251, 113, 133, 0.75)",
  bg_pago:  "rgba(52,  211, 153, 0.14)",
  bg_liq:   "rgba(96,  165, 250, 0.14)",
  bg_emp:   "rgba(122, 148, 184, 0.13)",
  bg_danger:"rgba(251, 113, 133, 0.15)",
};

let chartValores, chartProcessos, chartProcessosModal;
let chartPercentual, chartStatus, chartDesembolso;
let _resumoGeral = null;
let _rankDesktop = window.matchMedia("(min-width: 769px)").matches;
let _mensalidadesAtual = [];
let chartProcessosView = "anual";
let selectedIndex = -1;

function getGridColor() {
  return document.documentElement.getAttribute("data-theme") === "light"
    ? "rgba(0,0,0,0.1)" : "rgba(255,255,255,0.15)";
}

function brl(v) { return (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }
function el(t, c, h) { const e = document.createElement(t); if (c) e.className = c; if (h !== undefined) e.innerHTML = h; return e; }

function estado(msg, tipo) {
  const container = document.getElementById("estado");
  if (!container) return;
  if (!msg) { container.innerHTML = ""; return; }
  const fechar = tipo === "erro"
    ? `<button class="aviso-fechar" onclick="estado('')" aria-label="Fechar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
       </button>`
    : "";
  container.innerHTML = `<div class="aviso-box ${tipo || ""}">${msg}${fechar}</div>`;
}

function updateChartThemes() {
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const textColor = isDark ? '#f1f5f9' : '#1e293b';
    const gridColor = getGridColor();

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;
    Chart.defaults.font.family = "'Open Sans', sans-serif";

    [chartValores, chartProcessos, chartProcessosModal,
     chartPercentual, chartStatus, chartDesembolso].forEach(chart => {
        if (!chart) return;
        if (chart.options.scales?.x) {
            chart.options.scales.x.ticks.color = textColor;
            chart.options.scales.x.grid.color = gridColor;
        }
        if (chart.options.scales?.y) {
            chart.options.scales.y.ticks.color = textColor;
            chart.options.scales.y.grid.color = gridColor;
        }
        if (chart.options.plugins?.legend) {
            chart.options.plugins.legend.labels.color = textColor;
        }
        chart.update();
    });
}

const MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
function mesValido(ref) { return ref && /^\d{4}-\d{2}$/.test(ref); }
function mesLabel(ref) {
  if (!mesValido(ref)) return "Mês não identificado";
  const [a, m] = ref.split("-");
  return `${MESES_PT[parseInt(m, 10) - 1]}/${a}`;
}
// Cada empenho cobre uma lista de meses: 1 = mensalidade única; vários = intervalo/acordo.
function mesesDe(x) {
  return (x.meses && x.meses.length) ? x.meses : (mesValido(x.mes_referencia) ? [x.mes_referencia] : []);
}
function periodoLabel(ms) {
  const nome = k => MESES_PT[parseInt(k.split("-")[1], 10) - 1];
  const ano = k => k.split("-")[0];
  const seq = k => { const [a, m] = k.split("-"); return parseInt(a, 10) * 12 + parseInt(m, 10); };
  const contig = ms.every((k, i) => i === 0 || seq(k) === seq(ms[i - 1]) + 1);
  const ini = ms[0], fim = ms[ms.length - 1];
  if (contig) {
    return ano(ini) === ano(fim)
      ? `${nome(ini)} a ${nome(fim)}/${ano(fim)}`
      : `${nome(ini)}/${ano(ini)} a ${nome(fim)}/${ano(fim)}`;
  }
  return ms.map(k => `${nome(k)}/${ano(k)}`).join(", ");
}
function mensalidadeLabel(x) {
  const ms = mesesDe(x);
  const periodo = ms.length ? periodoLabel(ms) : null;
  const tipo = x.tipo || "mensalidade";
  if (tipo === "acordo") {
    const p = x.parcela;
    const suf = p === "única" ? "— parcela única" : p ? (p.includes(" a ") ? `— parcelas ${p}` : `— ${p}ª parcela`) : "";
    return periodo ? `Acordo ${suf} · ${periodo}` : `Acordo ${suf}`.trim();
  }
  if (tipo === "conjunto") return periodo ? `Pagamento conjunto · ${periodo}` : "Pagamento conjunto";
  if (ms.length === 1) return `Mensalidade de ${mesLabel(ms[0])}`;
  return "Mensalidade (mês não identificado)";
}

function dateKey(dateStr, view) {
  if (!dateStr) return null;
  const p = dateStr.split("/");
  if (p.length !== 3) return null;
  return view === "anual" ? p[2] : `${p[2]}-${p[1]}`;
}

function fetchResumoGeral() {
  fetch("/api/resumo-geral?t=" + Date.now())
    .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
    .then(d => {
      if (!d || typeof d.total_alunos !== "number") return Promise.reject("resposta sem dados — servidor desatualizado?");
      renderHomeStats(d);
    })
    .catch(e => console.error("resumo-geral:", e));
}

function renderRankList(elId, items, rotuloDemais) {
  const ul = document.getElementById(elId);
  if (!ul) return;
  const all = items || [];
  const limite = window.matchMedia("(min-width: 769px)").matches ? 10 : 5;
  const top = all.slice(0, limite);
  const resto = all.slice(limite);
  const max = top.length ? Math.max(...top.map(i => i.empenhado)) : 0;
  let html = top.map((i, idx) => {
    const pct = max > 0 ? (i.empenhado / max * 100) : 0;
    return `<li class="rank-item">
      <div class="rank-top">
        <span class="rank-name"><span class="rank-pos">${idx + 1}</span>${i.nome}</span>
        <span class="rank-val">${brl(i.empenhado)}</span>
      </div>
      <div class="rank-bar"><div class="rank-bar-fill" style="width:${pct}%"></div></div>
      <div class="rank-meta">${i.alunos} bolsista${i.alunos !== 1 ? "s" : ""} · ${brl(i.pago)} pagos</div>
    </li>`;
  }).join("");

  if (resto.length) {
    const emp = resto.reduce((s, i) => s + (i.empenhado || 0), 0);
    const pago = resto.reduce((s, i) => s + (i.pago || 0), 0);
    const alunos = resto.reduce((s, i) => s + (i.alunos || 0), 0);
    html += `<li class="rank-item rank-resto">
      <div class="rank-top">
        <span class="rank-name">+${resto.length} ${rotuloDemais}</span>
        <span class="rank-val">${brl(emp)}</span>
      </div>
      <div class="rank-meta">${alunos} bolsista${alunos !== 1 ? "s" : ""} · ${brl(pago)} pagos</div>
    </li>`;
  }
  ul.innerHTML = html;
}

function renderHomeStats(d) {
  const gc = getGridColor();

  // A — pills acima da busca
  const hsM = document.getElementById("hsMetrics");
  if (hsM) {
    const ano = d.ano_roster ? ` em ${d.ano_roster}` : "";
    let html = `<span class="hs-pill">${d.total_alunos} bolsistas${ano}</span>`;
    if (d.data_atualizacao) {
      html += `<span class="hs-pill">Atualizado em: ${d.data_atualizacao}</span>`;
    }
    hsM.innerHTML = html;
  }

  // B — cards de resumo
  const hsC = document.getElementById("hsCards");
  if (hsC) {
    hsC.innerHTML = [
      { l: "Total empenhado",       v: brl(d.total_empenhado), color: "" },
      { l: "Total pago",            v: brl(d.total_pago),       color: "var(--md-sys-color-success)" },
      { l: "A receber",             v: brl(d.total_a_pagar),    color: "var(--md-sys-color-error)" },
      { l: "Mensalidades pagas",    v: `${d.mensalidades_pagas} / ${d.total_mensalidades}`, color: "" },
    ].map(s => `<div class="stat-card">
      <div class="label">${s.l}</div>
      <div class="value"${s.color ? ` style="color:${s.color}"` : ""}>${s.v}</div>
    </div>`).join("");
  }

  // B — listas de ranking (instituições e cursos)
  _resumoGeral = d;
  renderRankList("rankInstituicoes", d.por_instituicao, "outras instituições");
  renderRankList("rankCursos", d.por_curso, "outros cursos");

  // C — percentual de bolsa (doughnut)
  const percs = Object.entries(d.por_percentual).sort(([a], [b]) => Number(b) - Number(a));
  if (chartPercentual) chartPercentual.destroy();
  chartPercentual = new Chart(document.getElementById("gPercentual"), {
    type: "doughnut",
    data: {
      labels: percs.map(([k]) => `${k}%`),
      datasets: [{ data: percs.map(([, v]) => v),
        backgroundColor: [COR.chart1, COR.chart2, COR.chart3, COR.chart4], borderWidth: 0 }]
    },
    options: { responsive: true, maintainAspectRatio: false, cutout: "65%",
      plugins: { legend: { display: true, position: "bottom" } } }
  });

  // C — status das mensalidades (doughnut)
  const pagas = d.mensalidades_pagas;
  const total = d.total_mensalidades;
  if (chartStatus) chartStatus.destroy();
  chartStatus = new Chart(document.getElementById("gStatus"), {
    type: "doughnut",
    data: {
      labels: ["Pagas", "Pendentes"],
      datasets: [{ data: [pagas, total - pagas],
        backgroundColor: [COR.chart3, COR.chart4], borderWidth: 0 }]
    },
    options: { responsive: true, maintainAspectRatio: false, cutout: "65%",
      plugins: { legend: { display: true, position: "bottom" } } }
  });

  // D — insights de pagamentos gerais
  const generalContainer = document.getElementById("generalInsights");
  if (generalContainer && d.cadencia && d.cadencia.length) {
    let totalDelays = 0;
    let totalCount = 0;
    d.cadencia.forEach(c => {
      totalDelays += c.atraso_medio * c.total_mensalidades;
      totalCount += c.total_mensalidades;
    });
    const avgDelay = totalCount > 0 ? (totalDelays / totalCount).toFixed(1) : "0.0";
    const quitacaoPct = d.total_mensalidades > 0 ? ((d.mensalidades_pagas / d.total_mensalidades) * 100).toFixed(0) : "0";
    const liqNP = d.liquidado_nao_pago || { valor: 0, parcelas: 0 };
    const acordos = d.acordos || { alunos: 0, valor: 0 };

    generalContainer.innerHTML = `
      <div class="insight-card">
        <div class="insight-header">
          <div class="insight-icon brand">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
          <span class="insight-label">Atraso Médio</span>
        </div>
        <div class="insight-value">${avgDelay} meses</div>
        <div class="insight-desc">Média de tempo que a prefeitura leva entre o mês de estudo e a liberação efetiva do dinheiro.</div>
      </div>

      <div class="insight-card">
        <div class="insight-header">
          <div class="insight-icon success">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
              <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
          </div>
          <span class="insight-label">Parcelas Pagas</span>
        </div>
        <div class="insight-value">${quitacaoPct}%</div>
        <div class="insight-desc">Porcentagem de todas as parcelas empenhadas em 2025/2026 que já foram pagas aos bolsistas ativos.</div>
      </div>

      <div class="insight-card">
        <div class="insight-header">
          <div class="insight-icon danger">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="3" y1="10" x2="21" y2="10"></line>
            </svg>
          </div>
          <span class="insight-label">Frequência</span>
        </div>
        <div class="insight-value">Por Lote</div>
        <div class="insight-desc">O fluxo de pagamento não é mensal constante. O município acumula as parcelas e as paga em lotes conjuntos.</div>
      </div>

      <div class="insight-card">
        <div class="insight-header">
          <div class="insight-icon danger">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path>
            </svg>
          </div>
          <span class="insight-label">Aguardando Pagamento</span>
        </div>
        <div class="insight-value">${brl(liqNP.valor)}</div>
        <div class="insight-desc">Valor já liquidado (reconhecido formalmente pela prefeitura) em ${liqNP.parcelas} parcelas, mas ainda não pago aos bolsistas.</div>
      </div>

      <div class="insight-card">
        <div class="insight-header">
          <div class="insight-icon brand">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="9" y1="15" x2="15" y2="15"></line>
            </svg>
          </div>
          <span class="insight-label">Acordos de Pagamento</span>
        </div>
        <div class="insight-value">${acordos.alunos} bolsistas</div>
        <div class="insight-desc">Têm parcelas em regime de acordo (dívida renegociada), somando ${brl(acordos.valor)} empenhados.</div>
      </div>
    `;
  }

  renderDesembolso(d.desembolso_mensal || []);
  renderPrazos(d.prazos || {});

  updateChartThemes();
}

// Item 1 — desembolso mês a mês (barras): mostra os pagamentos saindo em lotes
function renderDesembolso(lista) {
  const cv = document.getElementById("gDesembolso");
  if (!cv) return;
  const dados = lista.slice(-14); // últimos ~14 meses
  const labels = dados.map(x => mesLabel(x.mes));
  const valores = dados.map(x => x.pago);
  if (chartDesembolso) chartDesembolso.destroy();
  chartDesembolso = new Chart(cv, {
    type: "bar",
    data: { labels, datasets: [{
      label: "Pago no mês",
      data: valores,
      backgroundColor: COR.chart3,
      borderRadius: 6,
      maxBarThickness: 48,
    }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => brl(ctx.parsed.y) } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { callback: v => "R$ " + (v / 1000) + "k" } },
      },
    },
  });
}

// Item 2 — funil de prazos do processo (medianas em dias)
function renderPrazos(p) {
  const cont = document.getElementById("prazosFunil");
  if (!cont) return;
  const dias = n => `${n} ${n === 1 ? "dia" : "dias"}`;
  const etapas = [
    { lab: "Empenho → Liquidação", val: p.empenho_liquidacao,
      desc: "Tempo até a prefeitura reconhecer formalmente a dívida (liquidação) após registrar o empenho.", icon: "brand" },
    { lab: "Liquidação → Pagamento", val: p.liquidacao_pagamento,
      desc: "Tempo entre o reconhecimento da dívida e o dinheiro de fato cair na conta do bolsista.", icon: "danger" },
    { lab: "Total (Empenho → Pagamento)", val: p.empenho_pagamento,
      desc: "Tempo total do processo, do empenho ao pagamento efetivo.", icon: "success" },
  ];
  cont.innerHTML = etapas.map(e => `
    <div class="insight-card">
      <div class="insight-header">
        <div class="insight-icon ${e.icon}">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
        </div>
        <span class="insight-label">${e.lab}</span>
      </div>
      <div class="insight-value">${dias(e.val)}</div>
      <div class="insight-desc">${e.desc}</div>
    </div>
  `).join("");
}

function buildProcessosData(mensalidades, view) {
  const emp = {}, pag = {};
  mensalidades.forEach(m => {
    const ek = dateKey(m.data_empenho, view);
    if (ek) emp[ek] = (emp[ek] || 0) + 1;
    if ((m.pago || 0) > 0) {
      const pk = dateKey(m.data_pagamento, view);
      if (pk) pag[pk] = (pag[pk] || 0) + 1;
    }
  });
  const keys = [...new Set([...Object.keys(emp), ...Object.keys(pag)])].sort();
  const labels = view === "anual" ? keys : keys.map(k => mesLabel(k));
  return { labels, emp: keys.map(k => emp[k] || 0), pag: keys.map(k => pag[k] || 0) };
}

function renderModalChart(view) {
  const { labels, emp, pag } = buildProcessosData(_mensalidadesAtual, view);
  const gc = getGridColor();
  if (chartProcessosModal) chartProcessosModal.destroy();
  chartProcessosModal = new Chart(document.getElementById("gProcessosModal"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Empenhados", data: emp, backgroundColor: COR.chart1, borderRadius: 4 },
        { label: "Pagos",      data: pag, backgroundColor: COR.chart3, borderRadius: 4 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true } },
      scales: {
        x: { grid: { display: false }, ticks: { display: false } },
        y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 }, grid: { color: gc } }
      }
    }
  });
  document.querySelectorAll(".ct-modal-btn").forEach(btn =>
    btn.classList.toggle("active", btn.dataset.view === view)
  );
}

function renderChartProcessos(view) {
  chartProcessosView = view;
  const { labels, emp, pag } = buildProcessosData(_mensalidadesAtual, view);
  const gc = getGridColor();
  if (chartProcessos) chartProcessos.destroy();
  chartProcessos = new Chart(document.getElementById("gProcessos"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Empenhados", data: emp, backgroundColor: COR.chart1, borderRadius: 4 },
        { label: "Pagos",      data: pag, backgroundColor: COR.chart3, borderRadius: 4 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true } },
      scales: {
        x: { grid: { display: false }, ticks: { display: false } },
        y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 }, grid: { color: gc } }
      }
    }
  });
  document.querySelectorAll(".ct-btn").forEach(btn =>
    btn.classList.toggle("active", btn.dataset.view === view)
  );
}

function render(d) {
  if (d.encontrado === false) {
    estado(`"${d.nome}" não está na lista de bolsistas do Ensino Superior / Especialização.`, "erro");
    document.getElementById("loading").classList.add("hidden");
    return;
  }
  const r = d.resumo || {};
  document.body.classList.remove("initial-state");
  document.body.classList.remove("searching");
  document.body.classList.add("data-visible");
  document.getElementById("inputNome").blur();
  const resCont = document.getElementById("resultado");
  resCont.classList.remove("hidden");

  const hero = document.getElementById("heroWidget");
  const qtdPagas = (d.mensalidades || []).filter(m => (m.pago || 0) > 0).length;
  const tagPerc = d.percentual ? `<span class="hero-tag">${d.percentual}% de bolsa</span>` : '';
  hero.innerHTML = `
    <div class="hero-id">
      <div class="hero-nome">${d.nome}</div>
      <div class="hero-curso">${d.curso || 'Ensino Superior'}</div>
      <div class="hero-inst">${d.instituicao || ''}</div>
      <div class="hero-tags">${tagPerc}</div>
    </div>
    <div class="hero-sep"></div>
    <div class="hero-fin">
      <div class="hero-pago">
        <div class="hero-plbl">A receber</div>
        <div class="hero-pval">${brl(r.a_pagar)}</div>
        <span class="hero-tag" style="margin-top: 10px; display: inline-flex;">${qtdPagas}/${r.qtd} mensalidades pagas</span>
      </div>
      <div class="hero-badges">
        <div class="hero-status recebido"><div class="hero-sv">${brl(r.pago)}</div><div class="hero-sl">total recebido</div></div>
        <div class="hero-status empenhado"><div class="hero-sv">${brl(r.empenhado)}</div><div class="hero-sl">total empenhado</div></div>
      </div>
    </div>
  `;

  updateChartThemes();

  const gc = getGridColor();

  if (chartValores) chartValores.destroy();
  chartValores = new Chart(document.getElementById("gValores"), {
    type: "bar",
    data: {
      labels: ["Liquidado", "Pago", "A pagar"],
      datasets: [{ data: [r.liquidado, r.pago, r.a_pagar], backgroundColor: [COR.chart2, COR.chart3, COR.chart4], borderRadius: 8 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: gc } } } },
  });

  // Calcular insights individuais
  const individualContainer = document.getElementById("individualInsights");
  if (individualContainer) {
    const listRefMonths = [];
    (d.mensalidades || []).forEach(m => {
      const refs = mesesDe(m);
      refs.forEach(ref => {
        if (!ref) return;
        
        const empDate = m.data_empenho;
        if (!empDate) return;
        const partsEmp = empDate.split("/");
        if (partsEmp.length !== 3) return;
        const empDay = Number(partsEmp[0]);
        const empMonth = Number(partsEmp[1]);
        const empYear = Number(partsEmp[2]);
        
        let delay = 0;
        let isPaid = (m.pago || 0) > 0;
        let dateText = "";
        
        if (isPaid && m.data_pagamento) {
          const parts = m.data_pagamento.split("/");
          if (parts.length === 3) {
            const pDay = Number(parts[0]);
            const pMonth = Number(parts[1]);
            const pYear = Number(parts[2]);
            delay = (pYear - empYear) * 12 + (pMonth - empMonth);
            dateText = `${m.data_pagamento}`;
          } else {
            const hoje = new Date();
            const pYear = hoje.getFullYear();
            const pMonth = hoje.getMonth() + 1;
            delay = (pYear - empYear) * 12 + (pMonth - empMonth);
            dateText = "sem data registrada";
          }
        } else {
          const hoje = new Date();
          const pYear = hoje.getFullYear();
          const pMonth = hoje.getMonth() + 1;
          delay = (pYear - empYear) * 12 + (pMonth - empMonth);
          dateText = "pendente";
        }
        delay = Math.max(0, delay);
        listRefMonths.push({
          ref,
          refYear: Number(ref.split("-")[0]),
          refMonth: Number(ref.split("-")[1]),
          delay,
          isPaid,
          dateText,
          dataEmpenho: m.data_empenho,
          dataPagamento: m.data_pagamento,
          valor: (m.pago > 0 ? m.pago : m.empenhado) || 0
        });
      });
    });

    function parseDmy(dStr) {
      if (!dStr) return 0;
      const p = dStr.split("/");
      if (p.length !== 3) return 0;
      return new Date(Number(p[2]), Number(p[1]) - 1, Number(p[0])).getTime();
    }

    // 1. Atraso médio de TODAS as parcelas (pagas + pendentes contadas até hoje),
    //    para que a espera ainda em aberto também pese no número.
    const paidMonths = listRefMonths.filter(m => m.isPaid);
    const avgAllDelay = listRefMonths.length > 0
      ? (listRefMonths.reduce((s, m) => s + m.delay, 0) / listRefMonths.length).toFixed(1)
      : null;
    const temPendente = listRefMonths.some(m => !m.isPaid);

    // 2. Parcela mais antiga pendente (ordena pela data de empenho mais antiga)
    const pendingMonths = listRefMonths.filter(m => !m.isPaid).sort((a, b) => {
      return parseDmy(a.dataEmpenho) - parseDmy(b.dataEmpenho);
    });
    const oldestPending = pendingMonths.length > 0 ? pendingMonths[0] : null;

    // 3. Última parcela recebida (ordena pela data de pagamento mais recente)
    const sortedPaid = [...paidMonths].sort((a, b) => {
      return parseDmy(b.dataPagamento) - parseDmy(a.dataPagamento);
    });
    const latestPaid = sortedPaid.length > 0 ? sortedPaid[0] : null;

    // Montar os HTML cards
    let card1Html = "";
    if (avgAllDelay !== null) {
      const descAtraso = temPendente
        ? "Tempo médio de espera por parcela, somando as já pagas e as ainda pendentes (contadas até hoje)."
        : "Tempo médio que o município levou para creditar as parcelas deste bolsista.";
      card1Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon brand">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
            </div>
            <span class="insight-label">Atraso Médio</span>
          </div>
          <div class="insight-value">${avgAllDelay} meses</div>
          <div class="insight-desc">${descAtraso}</div>
        </div>
      `;
    } else {
      card1Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon brand">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
            </div>
            <span class="insight-label">Atraso Médio</span>
          </div>
          <div class="insight-value">Sem registros</div>
          <div class="insight-desc">Não há registro de recebimento registrado para este bolsista.</div>
        </div>
      `;
    }

    let card2Html = "";
    if (oldestPending) {
      const mesesSuf = oldestPending.delay === 1 ? "mês" : "meses";
      card2Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon danger">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
            </div>
            <span class="insight-label">Mais Antiga Pendente</span>
          </div>
          <div class="insight-value">${mesLabel(oldestPending.ref)}</div>
          <div class="insight-desc">Esta mensalidade está atualmente pendente há <b>${oldestPending.delay} ${mesesSuf}</b>.</div>
        </div>
      `;
    } else {
      card2Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon success">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
              </svg>
            </div>
            <span class="insight-label">Pendências</span>
          </div>
          <div class="insight-value">Nenhuma</div>
          <div class="insight-desc">Todas as parcelas registradas deste bolsista foram pagas.</div>
        </div>
      `;
    }

    let card3Html = "";
    if (latestPaid) {
      const delaySuf = latestPaid.delay === 1 ? "mês" : "meses";
      const delayText = latestPaid.delay > 0 ? `com ${latestPaid.delay} ${delaySuf} de atraso` : "no prazo";
      card3Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon success">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="4" width="20" height="16" rx="2" ry="2"></rect>
                <line x1="12" y1="10" x2="12" y2="10"></line>
                <line x1="2" y1="8" x2="22" y2="8"></line>
              </svg>
            </div>
            <span class="insight-label">Último Recebido</span>
          </div>
          <div class="insight-value">${mesLabel(latestPaid.ref)}</div>
          <div class="insight-desc">Pago em <b>${latestPaid.dateText}</b> ${delayText}.</div>
        </div>
      `;
    } else {
      card3Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon danger">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="4" width="20" height="16" rx="2" ry="2"></rect>
                <line x1="12" y1="10" x2="12" y2="10"></line>
                <line x1="2" y1="8" x2="22" y2="8"></line>
              </svg>
            </div>
            <span class="insight-label">Último Recebido</span>
          </div>
          <div class="insight-value">Nenhum</div>
          <div class="insight-desc">Não há registro de recebimento registrado para este bolsista.</div>
        </div>
      `;
    }

    // Item 7 — maior atraso já enfrentado (entre as parcelas já pagas)
    const worstPaid = paidMonths.length
      ? paidMonths.reduce((a, b) => (b.delay > a.delay ? b : a))
      : null;
    let card4Html = "";
    if (worstPaid && worstPaid.delay > 0) {
      const suf = worstPaid.delay === 1 ? "mês" : "meses";
      card4Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon danger">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                <line x1="12" y1="9" x2="12" y2="13"></line>
                <line x1="12" y1="17" x2="12.01" y2="17"></line>
              </svg>
            </div>
            <span class="insight-label">Maior Atraso</span>
          </div>
          <div class="insight-value">${worstPaid.delay} ${suf}</div>
          <div class="insight-desc">Maior espera já enfrentada para uma parcela ser paga — referente a ${mesLabel(worstPaid.ref)}.</div>
        </div>
      `;
    } else {
      card4Html = `
        <div class="insight-card">
          <div class="insight-header">
            <div class="insight-icon success">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
              </svg>
            </div>
            <span class="insight-label">Maior Atraso</span>
          </div>
          <div class="insight-value">Sem atraso</div>
          <div class="insight-desc">As parcelas pagas a este bolsista saíram dentro do mês do empenho.</div>
        </div>
      `;
    }

    individualContainer.innerHTML = card1Html + card2Html + card3Html + card4Html;
  }

  _mensalidadesAtual = d.mensalidades || [];
  renderChartProcessos(chartProcessosView);

  const list = document.getElementById("transacoes");
  list.innerHTML = "";
  (d.mensalidades || []).forEach(x => {
    const pendente = Math.max((x.liquidado || 0) - (x.pago || 0), 0);
    let chipHtml = "";
    if (x.pago > 0 && pendente <= 0) chipHtml = `<span class="status-pill" style="font-size: 0.65rem; padding: 6px 12px; border-radius: 8px; font-weight: 800; background: ${COR.bg_pago}; color: ${COR.success};">PAGO</span>`;
    else if (x.liquidado > 0) chipHtml = `<span class="status-pill" style="font-size: 0.65rem; padding: 6px 12px; border-radius: 8px; font-weight: 800; background: ${COR.bg_danger}; color: ${COR.danger};">A PAGAR</span>`;
    else chipHtml = `<span class="status-pill" style="font-size: 0.65rem; padding: 6px 12px; border-radius: 8px; font-weight: 800; background: ${COR.bg_emp}; color: var(--text);">EMPENHADO</span>`;

    list.innerHTML += `
      <div class="transaction-item">
        <div class="tr-head">
          <div class="tr-amount">${brl(x.empenhado)}</div>
          ${chipHtml}
        </div>
        <div class="tr-body">
          <span class="tr-name">${mensalidadeLabel(x)}</span>
          <div class="tr-dates">
            <span>EMP <b>${x.data_empenho || '—'}</b></span>
            <span>LIQ <b>${x.data_liquidacao || '—'}</b></span>
            <span>PAG <b>${x.data_pagamento || '—'}</b></span>
          </div>
        </div>
        <div class="tr-foot">
          <span class="tr-ref">#${x.empenho}</span>
          <span class="tr-year">· ${x.ano}</span>
        </div>
      </div>`;
  });
  document.getElementById("comoConferir").innerHTML = `
    Fonte Oficial: <a href="${d.url}" target="_blank" style="color: var(--brand)">${d.fonte}</a><br>
    <span style="display: inline-block; margin-top: 8px; opacity: 0.85;">
      Histórico limitado a partir de 2022 (restrição do portal municipal).
      Para dados anteriores, solicite à prefeitura via e-SIC ou Ouvidoria.
    </span>
  `;
  window._nomeAtual = d.nome;
  window._dadosAtual = d;
  document.getElementById("btnExportPDF").onclick = () => exportPDF(d);
}

function exportPDF(d) {
  const r = d.resumo || {};
  const agora = new Date();
  const dataFmt = agora.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: "numeric" });
  const dataHora = agora.toLocaleString("pt-BR");

  document.getElementById("pdNome").textContent = d.nome;
  document.getElementById("pdCurso").textContent = d.curso || "—";
  document.getElementById("pdInst").textContent = d.instituicao || "—";
  document.getElementById("pdPerc").textContent = d.percentual ? `${d.percentual}%` : "—";
  document.getElementById("pdData").textContent = dataFmt;
  document.getElementById("pdDataFull").textContent = dataHora;
  document.getElementById("pdUrl").textContent = d.url || "";
  document.getElementById("pdEmp").textContent = brl(r.empenhado);
  document.getElementById("pdLiq").textContent = brl(r.liquidado);
  document.getElementById("pdPago").textContent = brl(r.pago);
  document.getElementById("pdRec").textContent = brl(r.a_pagar);
  const qtdPagas = (d.mensalidades || []).filter(m => (m.pago || 0) > 0).length;
  document.getElementById("pdQtd").textContent = `${qtdPagas}/${r.qtd} pagas`;

  const tbody = document.getElementById("pdRows");
  tbody.innerHTML = "";
  (d.mensalidades || []).forEach((m, i) => {
    const pendente = Math.max((m.liquidado || 0) - (m.pago || 0), 0);
    const status = (m.pago > 0 && pendente <= 0) ? "Pago" : m.liquidado > 0 ? "A pagar" : "Empenhado";
    const tr = document.createElement("tr");
    if (m.pago > 0 && pendente <= 0) tr.className = "pd-row-pago";
    else if (m.liquidado > 0) tr.className = "pd-row-pendente";
    tr.innerHTML = `
      <td>#${m.empenho}</td>
      <td>${mensalidadeLabel(m)}</td>
      <td>${brl(m.empenhado)}</td>
      <td>${brl(m.pago)}</td>
      <td><span class="pd-status ${status === 'Pago' ? 'pd-ok' : status === 'A pagar' ? 'pd-warn' : ''}">${status}</span></td>
      <td>${m.data_empenho || "—"}</td>
      <td>${m.data_pagamento || "—"}</td>
    `;
    tbody.appendChild(tr);
  });

  const tituloOriginal = document.title;
  const nomeArquivo = `Bolsa_${d.nome.replace(/\s+/g, "_")}_${agora.getFullYear()}`;
  document.title = nomeArquivo;
  window.print();
  document.title = tituloOriginal;
}

function buscar(nome) {
  document.getElementById("loading").classList.remove("hidden");
  document.getElementById("resultado").classList.add("hidden");
  fetch(`/api/buscar?nome=${encodeURIComponent(nome)}`)
    .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || "Erro")))
    .then(d => { document.getElementById("loading").classList.add("hidden"); render(d); })
    .catch(e => { estado(`Erro: ${e}`, "erro"); document.getElementById("loading").classList.add("hidden"); });
}


function initTheme() {
  const toggle = document.getElementById("themeToggle");
  const icon = document.getElementById("themeIcon");
  const sun = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
  const moon = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';

  const setTheme = (t) => {
    document.body.classList.add("theme-transition");
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("theme", t);
    if (icon) icon.innerHTML = t === "dark" ? sun : moon;
    updateChartThemes();
    setTimeout(() => {
        document.body.classList.remove("theme-transition");
    }, 500);
  };

  const stored = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(stored || (prefersDark ? "dark" : "light"));

  if (toggle) {
    toggle.onclick = (e) => { e.preventDefault(); setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"); };
  }
}

const NOMES_CACHE_KEY = "bolsas_nomes";
const NOMES_CACHE_TTL = 3600 * 1000;

function normJS(s) {
  return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toUpperCase().replace(/\s+/g, " ").trim();
}

function getNomesCache() {
  try {
    const raw = localStorage.getItem(NOMES_CACHE_KEY);
    if (!raw) return null;
    const { nomes, ts } = JSON.parse(raw);
    return Date.now() - ts < NOMES_CACHE_TTL ? nomes : null;
  } catch { return null; }
}

function setNomesCache(nomes) {
  try { localStorage.setItem(NOMES_CACHE_KEY, JSON.stringify({ nomes, ts: Date.now() })); } catch {}
}

let _nomesPromise = null;
function fetchNomes() {
  if (_nomesPromise) return _nomesPromise;
  const cached = getNomesCache();
  if (cached) { _nomesPromise = Promise.resolve(cached); return _nomesPromise; }
  _nomesPromise = fetch("/api/nomes").then(r => r.json()).then(nomes => { setNomesCache(nomes); return nomes; });
  return _nomesPromise;
}

function init() {
  initTheme();
  fetchNomes();
  fetchResumoGeral();

  // re-renderiza as listas ao cruzar o breakpoint (top 5 mobile / top 10 desktop)
  window.addEventListener("resize", () => {
    const desktop = window.matchMedia("(min-width: 769px)").matches;
    if (desktop !== _rankDesktop && _resumoGeral) {
      _rankDesktop = desktop;
      renderRankList("rankInstituicoes", _resumoGeral.por_instituicao, "outras instituições");
      renderRankList("rankCursos", _resumoGeral.por_curso, "outros cursos");
    }
  });
  const input = document.getElementById("inputNome");
  const suggestionsCont = document.getElementById("sugestoes");
  const btnHome = document.getElementById("btnHome");

  const updateSelection = () => {
    const items = suggestionsCont.querySelectorAll(".sugestao-item");
    items.forEach((item, i) => {
      if (i === selectedIndex) {
        item.classList.add("selected");
        const containerHeight = suggestionsCont.offsetHeight;
        const itemTop = item.offsetTop;
        const itemHeight = item.offsetHeight;
        const scrollCurrent = suggestionsCont.scrollTop;
        if (itemTop < scrollCurrent) suggestionsCont.scrollTop = itemTop;
        else if (itemTop + itemHeight > scrollCurrent + containerHeight) suggestionsCont.scrollTop = itemTop + itemHeight - containerHeight;
      }
      else item.classList.remove("selected");
    });
  };

  input.onfocus = () => { if (!document.body.classList.contains("initial-state")) document.body.classList.add("searching"); };
  input.onblur = (e) => {
    setTimeout(() => {
        if (!document.activeElement || !document.activeElement.closest(".busca-wrapper")) {
            document.body.classList.remove("searching");
            suggestionsCont.classList.remove("active");
        }
    }, 200);
  };

  input.oninput = (e) => {
    const q = e.target.value.trim();
    if (q.length < 2) { suggestionsCont.classList.remove("active"); return; }
    fetchNomes().then(nomes => {
      const tokens = normJS(q).split(" ").filter(Boolean);
      const list = nomes.filter(n => tokens.every(t => normJS(n).includes(t))).slice(0, 10);
      if (list.length === 0) { suggestionsCont.classList.remove("active"); return; }
      suggestionsCont.innerHTML = "";
      selectedIndex = -1;
      list.forEach(nome => {
        const item = el("div", "sugestao-item", nome.replace(new RegExp(q, "gi"), "<b>$&</b>"));
        item.onclick = () => { suggestionsCont.classList.remove("active"); document.body.classList.remove("searching"); input.value = ""; buscar(nome); };
        suggestionsCont.appendChild(item);
      });
      suggestionsCont.classList.add("active");
    });
  };

  input.onkeydown = (e) => {
    const items = suggestionsCont.querySelectorAll(".sugestao-item");
    if (suggestionsCont.classList.contains("active")) {
        if (e.key === "ArrowDown") { e.preventDefault(); selectedIndex = (selectedIndex + 1) % items.length; updateSelection(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); selectedIndex = (selectedIndex - 1 + items.length) % items.length; updateSelection(); }
        else if (e.key === "Enter") {
          e.preventDefault();
          const nome = selectedIndex > -1 ? items[selectedIndex].textContent : (items.length > 0 ? items[0].textContent : null);
          if (nome) { suggestionsCont.classList.remove("active"); input.value = ""; buscar(nome); }
        } else if (e.key === "Escape") { suggestionsCont.classList.remove("active"); }
    }
  };

  document.onkeydown = (e) => {
    if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
    if (e.key.toLowerCase() === "t" && document.activeElement !== input) { document.getElementById("themeToggle").click(); }
    if (e.key === "Escape") {
      if (!document.getElementById("chartModal")?.classList.contains("hidden")) document.getElementById("btnCloseModal").click();
      else if (suggestionsCont.classList.contains("active")) suggestionsCont.classList.remove("active");
      else btnHome.click();
    }
  };

  document.onclick = (e) => { if (!e.target.closest(".busca-wrapper")) suggestionsCont.classList.remove("active"); };

  btnHome.onclick = (e) => {
    e.preventDefault();
    const res = document.getElementById("resultado");
    res.style.opacity = "0";
    setTimeout(() => {
      document.body.classList.add("initial-state");
      document.body.classList.remove("searching");
      document.body.classList.remove("data-visible");
      res.classList.add("hidden");
      res.style.opacity = "";
      input.value = "";
      estado("");
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 300);
  };

  document.querySelectorAll(".ct-btn").forEach(btn => {
    btn.onclick = () => renderChartProcessos(btn.dataset.view);
  });

  const expandBtn = document.getElementById("btnExpandProcessos");
  const closeModalBtn = document.getElementById("btnCloseModal");
  const chartModal = document.getElementById("chartModal");

  const openModal = () => {
    chartModal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    renderModalChart(chartProcessosView);
  };
  const closeModal = () => {
    chartModal.classList.add("hidden");
    document.body.style.overflow = "";
    if (chartProcessosModal) { chartProcessosModal.destroy(); chartProcessosModal = null; }
  };

  if (expandBtn) expandBtn.onclick = openModal;
  if (closeModalBtn) closeModalBtn.onclick = closeModal;
  chartModal.addEventListener("click", e => { if (e.target === chartModal) closeModal(); });

  document.querySelectorAll(".ct-modal-btn").forEach(btn => {
    btn.onclick = () => { chartProcessosView = btn.dataset.view; renderModalChart(chartProcessosView); renderChartProcessos(chartProcessosView); };
  });

  document.getElementById("formBusca").onsubmit = (e) => {
    e.preventDefault();
    const n = input.value.trim();
    if (n.length > 3) {
      suggestionsCont.classList.remove("active");
      document.body.classList.remove("searching");
      input.value = "";
      buscar(n);
    }
  };

  const scrollDownBtn = document.getElementById("scrollDownBtn");
  if (scrollDownBtn) {
    scrollDownBtn.onclick = (e) => {
      e.preventDefault();
      const homeStats = document.getElementById("homeStats");
      if (homeStats) {
        homeStats.scrollIntoView({ behavior: "smooth" });
      }
    };
  }
}

document.addEventListener("DOMContentLoaded", init);
