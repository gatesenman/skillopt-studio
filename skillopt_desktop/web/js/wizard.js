// Beginner wizard: pick goal -> connect provider -> start.
import { get, post, toast, el, escapeHtml } from "./api.js";
import { t, getLang } from "./i18n.js";
import { icon } from "./icons.js";

const presetTitle = (p) => (getLang() === "en" && p.title_en) ? p.title_en : p.title;
const presetDesc = (p) => (getLang() === "en" && p.desc_en) ? p.desc_en : p.desc;

export async function render(root, ctx) {
  const [presets, backends] = await Promise.all([
    get("/api/presets"), get("/api/backends"),
  ]);
  const state = { step: 1, preset: null, backend: "", mock: !ctx.health?.live };

  const wrap = el(`<div></div>`);
  root.appendChild(wrap);

  function steps() {
    return `<div class="steps">
      ${[["1", t("wizard.s1")], ["2", t("wizard.s2")], ["3", t("wizard.s3")]].map(([n, l]) =>
        `<div class="step ${state.step == n ? "active" : ""}"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("")}
    </div>`;
  }

  function draw() {
    let body = "";
    if (state.step === 1) {
      body = `<div class="card"><h3>${t("wizard.q")}</h3>
        <p class="hint">${t("wizard.qHint")}</p>
        <div class="preset-grid">
          ${presets.map((p) => `
            <div class="preset ${state.preset?.id === p.id ? "selected" : ""}" data-id="${p.id}">
              <div class="t">${escapeHtml(presetTitle(p))}</div>
              <div class="d">${escapeHtml(presetDesc(p))}</div>
              <div class="tag"><span class="pill">${p.kind === "sleep" ? t("nav.sleep") : t("wizard.benchTag") + (p.env || "—")}</span></div>
            </div>`).join("")}
        </div>
        <div class="btn-row"><button class="btn primary" id="next1" ${state.preset ? "" : "disabled"}>${t("common.next")} →</button></div>
      </div>`;
    } else if (state.step === 2) {
      const apis = backends.filter((b) => b.kind === "api");
      body = `<div class="card"><h3>${t("wizard.connTitle")}</h3>
        <p class="hint">${t("wizard.connHint")}</p>
        <label class="field"><span>${t("common.backend")}</span>
          <select id="backendSel">
            <option value="">${t("wizard.demoOption")}</option>
            ${apis.map((b) => `<option value="${b.id}" ${state.backend === b.id ? "selected" : ""}>${b.name}${b.configured ? t("wizard.configuredMark") : ""}</option>`).join("")}
          </select>
        </label>
        <div id="credForm"></div>
        <div class="btn-row">
          <button class="btn ghost" id="back2">← ${t("common.prev")}</button>
          <button class="btn primary" id="next2">${t("common.next")} →</button>
        </div>
      </div>`;
    } else {
      body = `<div class="card"><h3>${t("wizard.confirmTitle")}</h3>
        <div class="kvs" style="margin:10px 0 18px">
          <div><div class="muted">${t("wizard.goal")}</div><b>${escapeHtml(presetTitle(state.preset))}</b></div>
          <div><div class="muted">${t("common.backend")}</div><b>${state.backend || t("common.demo")}</b></div>
          <div><div class="muted">${t("common.benchmark")}</div><b>${state.preset.env || "—"}</b></div>
        </div>
        <p class="hint">${t("wizard.confirmHint")}</p>
        <div class="btn-row">
          <button class="btn ghost" id="back3">← ${t("common.prev")}</button>
          <button class="btn primary" id="startBtn">${icon("play")} ${t("wizard.start")}</button>
        </div>
      </div>`;
    }
    wrap.innerHTML = steps() + body;
    bind();
  }

  function bind() {
    if (state.step === 1) {
      wrap.querySelectorAll(".preset").forEach((c) => c.onclick = () => {
        state.preset = presets.find((p) => p.id === c.dataset.id);
        state.backend = state.backend || (state.preset.recommended_backend !== "mock" ? "" : "");
        draw();
      });
      const n = wrap.querySelector("#next1");
      if (n) n.onclick = () => { if (state.preset?.kind === "sleep") { ctx.go("sleep"); return; } state.step = 2; draw(); };
    }
    if (state.step === 2) {
      const sel = wrap.querySelector("#backendSel");
      sel.onchange = () => { state.backend = sel.value; drawCred(); };
      drawCred();
      wrap.querySelector("#back2").onclick = () => { state.step = 1; draw(); };
      wrap.querySelector("#next2").onclick = () => { state.step = 3; draw(); };
    }
    if (state.step === 3) {
      wrap.querySelector("#back3").onclick = () => { state.step = 2; draw(); };
      wrap.querySelector("#startBtn").onclick = start;
    }
  }

  function drawCred() {
    const host = wrap.querySelector("#credForm");
    if (!host) return;
    if (!state.backend) { host.innerHTML = `<p class="hint">${t("wizard.noCred")}</p>`; return; }
    const b = backends.find((x) => x.id === state.backend);
    host.innerHTML = b.fields.map((f) => `
      <label class="field"><span>${f.label}${f.required ? " *" : ""} ${f.set ? `<span class="badge ok">${t("common.saved")}</span>` : ""}</span>
        <input data-key="${f.key}" type="${f.secret ? "password" : "text"}" placeholder="${f.placeholder || ""}" />
      </label>`).join("") +
      `<div class="btn-row"><button class="btn" id="testBtn">${t("common.test")}</button><button class="btn" id="saveBtn">${t("wizard.saveCred")}</button></div>`;
    const creds = () => Object.fromEntries([...host.querySelectorAll("input")].map((i) => [i.dataset.key, i.value]));
    host.querySelector("#testBtn").onclick = async () => {
      try { const r = await post("/api/backends/test", { backend: state.backend, creds: creds() });
        toast(r.message, r.ok ? "ok" : "err"); } catch (e) { toast(e.message, "err"); }
    };
    host.querySelector("#saveBtn").onclick = async () => {
      try { await post("/api/backends", { backend: state.backend, creds: creds() });
        toast(t("common.saved"), "ok"); b.fields.forEach((f) => f.set = true); } catch (e) { toast(e.message, "err"); }
    };
  }

  async function start() {
    try {
      const r = await post("/api/train/start", {
        preset_id: state.preset.id, backend: state.backend,
        overrides: state.preset.overrides || {}, mock: !state.backend,
      });
      ctx.currentRun = r.run_id;
      toast(t("wizard.started"), "ok");
      ctx.go("monitor");
    } catch (e) { toast(e.message, "err"); }
  }

  draw();
  return {};
}
