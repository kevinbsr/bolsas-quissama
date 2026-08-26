/* Console ao vivo do pipeline.
   Polling simples em vez de SSE/WebSocket: é um painel de um usuário só na rede
   local, e polling sobrevive a proxy, reload e suspensão do notebook sem
   reconexão manual. */

(function () {
  const consoleEl = document.getElementById("console");
  if (!consoleEl) return;

  const statusEl = document.getElementById("statusRun");
  const btnCancelar = document.getElementById("btnCancelar");
  const forms = document.querySelectorAll("form.disparo");

  let desde = 0;
  let colado = true;   // só rola sozinho se o usuário não subiu para ler

  consoleEl.addEventListener("scroll", () => {
    colado = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
  });

  function classe(linha) {
    if (linha.startsWith("[painel]") || linha.startsWith("$ ")) return "l-painel";
    if (/^\s*(\[!\]|!!)/.test(linha)) return "l-aviso";
    if (/(Traceback|Error|Erro|falhou|FALHOU|expirou)/.test(linha)) return "l-erro";
    if (/^\s*\[\+\]/.test(linha)) return "l-ok";
    return "";
  }

  function anexar(linhas) {
    if (!linhas.length) return;
    const frag = document.createDocumentFragment();
    for (const l of linhas) {
      const div = document.createElement("div");
      const c = classe(l);
      if (c) div.className = c;
      div.textContent = l;
      frag.appendChild(div);
    }
    consoleEl.appendChild(frag);
    if (colado) consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function pintarStatus(e) {
    if (!statusEl) return;
    if (e.rodando) {
      statusEl.innerHTML =
        '<span class="pulso"></span><strong>' + (e.rotulo || e.modo) + "</strong>" +
        '<span class="selo atencao">rodando' +
        (e.decorrido ? " · " + Math.round(e.decorrido) + "s" : "") + "</span>";
    } else if (e.status && e.status !== "ocioso") {
      const tom = e.status === "sucesso" ? "bom" : e.status === "cancelado" ? "atencao" : "ruim";
      statusEl.innerHTML =
        "<strong>" + (e.rotulo || e.modo || "") + "</strong>" +
        '<span class="selo ' + tom + '">' + e.status + "</span>" +
        (e.run_id ? ' <a href="/pipeline/run/' + e.run_id + '">ver registro</a>' : "");
    } else {
      statusEl.textContent = "Nenhuma execução em andamento.";
    }
    forms.forEach((f) => { const b = f.querySelector("button"); if (b) b.disabled = e.rodando; });
    if (btnCancelar) btnCancelar.disabled = !e.rodando;
  }

  let parado = false;

  async function tique() {
    try {
      const r = await fetch("/api/pipeline/log?desde=" + desde, { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      anexar(d.linhas || []);
      desde = d.proximo;
      pintarStatus(d.estado);
      parado = !d.estado.rodando;
    } catch (e) {
      /* rede caiu ou o painel reiniciou; o próximo tique tenta de novo */
    }
    setTimeout(tique, parado ? 3000 : 800);
  }

  tique();

  forms.forEach((f) => {
    f.addEventListener("submit", () => {
      consoleEl.textContent = "";
      desde = 0;
      colado = true;
      parado = false;
    });
  });
})();
