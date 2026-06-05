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

let chartValores, chartAnos;
let selectedIndex = -1;

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
    const gridColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.1)';

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;
    Chart.defaults.font.family = "'Open Sans', sans-serif";

    [chartValores, chartAnos].forEach(chart => {
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
    const suf = p === "única" ? "— parcela única" : p ? `— ${p}ª parcela` : "";
    return periodo ? `Acordo ${suf} · ${periodo}` : `Acordo ${suf}`.trim();
  }
  if (tipo === "conjunto") return periodo ? `Pagamento conjunto · ${periodo}` : "Pagamento conjunto";
  if (ms.length === 1) return `Mensalidade de ${mesLabel(ms[0])}`;
  return "Mensalidade (mês não identificado)";
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

  const ctx = [d.percentual ? `${d.percentual}% de bolsa` : null, d.curso, d.instituicao].filter(Boolean).join(" · ");
  const hero = document.getElementById("heroWidget");
  hero.innerHTML = `
    <div class="label">${d.nome}</div>
    <div class="value">${brl(r.a_pagar)}</div>
    <div class="footer">${ctx || "Bolsa de estudo"} · saldo a receber (liquidado e não pago)</div>
  `;

  const grid = document.getElementById("statsGrid");
  grid.innerHTML = "";
  const stats = [
    { l: "Mensalidades", v: r.qtd },
    { l: "Total Empenhado", v: brl(r.empenhado) },
    { l: "Total Pago", v: brl(r.pago) },
    { l: "Pendente", v: brl(r.a_pagar), d: r.a_pagar > 0 }
  ];
  stats.forEach(s => {
    grid.innerHTML += `<div class="stat-card ${s.d ? 'danger' : ''}"><div class="label">${s.l}</div><div class="value">${s.v}</div></div>`;
  });

  updateChartThemes();

  if (chartValores) chartValores.destroy();
  chartValores = new Chart(document.getElementById("gValores"), {
    type: "bar",
    data: {
      labels: ["Empenhado", "Liquidado", "Pago", "A pagar"],
      datasets: [{ data: [r.empenhado, r.liquidado, r.pago, r.a_pagar], backgroundColor: [COR.chart1, COR.chart2, COR.chart3, COR.chart4], borderRadius: 8 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true } } },
  });

  const porMes = {};
  (d.mensalidades || []).forEach(m => {
    const ms = mesesDe(m);
    if (!ms.length) { porMes["sem"] = (porMes["sem"] || 0) + (m.pago || 0); return; }
    const share = (m.pago || 0) / ms.length;  // rateia o valor entre os meses cobertos
    ms.forEach(k => { porMes[k] = (porMes[k] || 0) + share; });
  });
  const chavesMes = Object.keys(porMes).sort();
  if (chartAnos) chartAnos.destroy();
  chartAnos = new Chart(document.getElementById("gAnos"), {
    type: "bar",
    data: {
      labels: chavesMes.map(k => k === "sem" ? "Sem mês" : mesLabel(k)),
      datasets: [
        { label: "Pago por mês de referência", data: chavesMes.map(k => porMes[k]), backgroundColor: COR.chart3, borderRadius: 4 }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true } } },
  });

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
  document.getElementById("comoConferir").innerHTML = `Fonte Oficial: <a href="${d.url}" target="_blank" style="color: var(--brand)">${d.fonte}</a>`;
  window._nomeAtual = d.nome;
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
        item.onclick = () => { input.value = nome; suggestionsCont.classList.remove("active"); document.body.classList.remove("searching"); buscar(nome); };
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
          if (nome) { input.value = nome; suggestionsCont.classList.remove("active"); buscar(nome); }
        } else if (e.key === "Escape") { suggestionsCont.classList.remove("active"); }
    }
  };

  document.onkeydown = (e) => {
    if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
    if (e.key.toLowerCase() === "t" && document.activeElement !== input) { document.getElementById("themeToggle").click(); }
    if (e.key === "Escape") {
      if (suggestionsCont.classList.contains("active")) suggestionsCont.classList.remove("active");
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

  document.getElementById("formBusca").onsubmit = (e) => {
    e.preventDefault();
    const n = input.value.trim();
    if (n.length > 3) {
      suggestionsCont.classList.remove("active");
      document.body.classList.remove("searching");
      buscar(n);
    }
  };

}

document.addEventListener("DOMContentLoaded", init);
