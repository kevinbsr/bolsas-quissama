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

    [chartValores, chartProcessos, chartProcessosModal].forEach(chart => {
        if (chart) {
            chart.options.scales.x.ticks.color = textColor;
            chart.options.scales.y.ticks.color = textColor;
            chart.options.scales.x.grid.color = gridColor;
            chart.options.scales.y.grid.color = gridColor;
            if (chart.options.plugins.legend) {
                chart.options.plugins.legend.labels.color = textColor;
            }
            chart.update();
        }
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
  fetchNomes(); // pré-carrega em background
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

}

document.addEventListener("DOMContentLoaded", init);
