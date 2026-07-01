// SkillOpt-Sleep: nightly self-evolution preview, gate result, adopt.
import { get, post, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";
import { icon } from "./icons.js";

export async function render(root, ctx) {
  root.innerHTML = `
    <div class="card">
      <h3>${t("sleep.title")}</h3>
      <p class="hint">${t("sleep.hint")}</p>
      <div class="grid cols-3">
        <label class="field"><span>${t("sleep.proj")}</span><input id="proj" placeholder="/path/to/your/project" /></label>
        <label class="field"><span>${t("common.backend")}</span>
          <select id="backend"><option value="mock">${t("sleep.demoMock")}</option>
            <option value="claude_code_exec">Claude Code CLI</option>
            <option value="codex_exec">Codex CLI</option></select></label>
        <label class="field"><span>${t("sleep.maxTasks")}</span><input id="maxt" type="number" value="40" /></label>
      </div>
      <div class="btn-row">
        <button class="btn" id="dry">${icon("search")} ${t("sleep.dry")}</button>
        <button class="btn primary" id="run">${icon("moon")} ${t("sleep.run")}</button>
        <button class="btn ghost" id="adopt">${icon("check")} ${t("sleep.adopt")}</button>
      </div>
    </div>
    <div class="card" id="report" style="display:none"></div>`;

  const q = (s) => root.querySelector(s);
  const body = () => ({ project: q("#proj").value, backend: q("#backend").value, max_tasks: +q("#maxt").value });

  async function call(path, extra) {
    try {
      const r = await post(path, { ...body(), ...extra });
      drawReport(r); toast(r.ok ? t("common.done") : t("common.fail"), r.ok ? "ok" : "err");
    } catch (e) { toast(e.message, "err"); }
  }

  q("#dry").onclick = () => call("/api/sleep/run", { dry_run: true });
  q("#run").onclick = () => call("/api/sleep/run", { dry_run: false });
  q("#adopt").onclick = () => call("/api/sleep/adopt", {});

  function drawReport(r) {
    const box = q("#report"); box.style.display = "block";
    const delta = (r.candidate != null && r.baseline != null) ? (r.candidate - r.baseline) : null;
    box.innerHTML = `
      <h3>${t("sleep.report")} · ${t("sleep.nightPre")}${r.night}${t("sleep.night")} ${r.adopted ? `<span class="badge ok">${t("sleep.adopted")}</span>` : r.accepted ? `<span class="badge ok">${t("sleep.passed")}</span>` : `<span class="badge off">${t("sleep.notAdopted")}</span>`}</h3>
      <div class="kvs" style="margin:12px 0 18px">
        <div><div class="muted">${t("sleep.baseline")}</div><b>${r.baseline ?? "—"}</b></div>
        <div><div class="muted">${t("sleep.candidate")}</div><b>${r.candidate ?? "—"}</b></div>
        <div><div class="muted">${t("sleep.gain")}</div><b style="color:${delta > 0 ? "var(--ok)" : "var(--muted)"}">${delta != null ? (delta > 0 ? "+" : "") + delta.toFixed(3) : "—"}</b></div>
        <div><div class="muted">${t("sleep.nTasks")}</div><b>${r.n_tasks}</b></div>
        <div><div class="muted">${t("sleep.nSessions")}</div><b>${r.n_sessions}</b></div>
      </div>
      <h3>${t("sleep.edits")} (${(r.edits || []).length})</h3>
      ${(r.edits || []).map((e) => `<div class="codeblock" style="margin-bottom:8px">[${e.op}] ${escapeHtml(e.target)}\n${escapeHtml(e.content)}</div>`).join("") || `<p class="hint">${t("common.none")}</p>`}
      ${(r.rejected_edits || []).length ? `<h3>${t("sleep.rejected")} (${r.rejected_edits.length})</h3>
        ${r.rejected_edits.map((e) => `<div class="codeblock" style="margin-bottom:8px;opacity:.7">[${e.op}] ${escapeHtml(e.target)}\n${escapeHtml(e.content)}</div>`).join("")}` : ""}
      ${r.staging_dir ? `<p class="hint">${t("sleep.stagingDir")}${escapeHtml(r.staging_dir)}</p>` : ""}`;
    box.scrollIntoView({ behavior: "smooth" });
  }
  return {};
}
