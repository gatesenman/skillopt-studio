// Run history (P1-5) + per-step edit/gate trajectory (P1-6).
// Lists past + live runs; clicking one shows the held-out score curve and the
// accept/reject trajectory that is SkillOpt's most distinctive signal.
import { get, post, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";
import { icon } from "./icons.js";

const ACCEPT = new Set(["accept", "accept_new_best", "force_accept"]);

function fmtScore(v) { return v == null ? "—" : (+v).toFixed(3); }
function fmtTime(ts) { return ts ? new Date(ts * 1000).toLocaleString() : "—"; }

export async function render(root, ctx) {
  root.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <div class="row-between">
          <h3>${t("hist.runsTitle")}</h3>
          <button class="btn ghost sm" id="refresh">${icon("search")} ${t("hist.refresh")}</button>
        </div>
        <p class="hint">${t("hist.runsHint")}</p>
        <div id="runs">${t("common.loading")}</div>
      </div>
      <div class="card">
        <h3>${t("hist.trajTitle")}</h3>
        <p class="hint">${t("hist.trajHint")}</p>
        <div id="traj"><p class="hint">${t("hist.pickRun")}</p></div>
      </div>
    </div>`;

  const q = (s) => root.querySelector(s);

  async function loadRuns() {
    let runs = [];
    try { runs = await get("/api/runs"); } catch (e) { toast(e.message, "err"); }
    if (!runs.length) { q("#runs").innerHTML = `<p class="hint">${t("hist.empty")}</p>`; return; }
    q("#runs").innerHTML = `<table class="tbl">
      <thead><tr><th>${t("hist.run")}</th><th>${t("hist.status")}</th>
        <th>${t("hist.best")}</th><th>${t("hist.steps")}</th><th></th></tr></thead>
      <tbody>${runs.map((r) => `
        <tr data-run="${escapeHtml(r.run_id)}" class="run-row">
          <td><code>${escapeHtml(r.run_id)}</code><div class="muted">${fmtTime(r.mtime)}</div></td>
          <td>${statusBadge(r)}</td>
          <td>${fmtScore(r.best_score)}</td>
          <td>${r.n_steps ?? "—"}</td>
          <td><button class="btn ghost sm view" data-run="${escapeHtml(r.run_id)}">${t("hist.view")}</button>
              ${r.has_skill ? `<button class="btn ghost sm eval" data-run="${escapeHtml(r.run_id)}">${t("hist.eval")}</button>` : ""}</td>
        </tr>`).join("")}</tbody></table>`;
    root.querySelectorAll(".view").forEach((b) =>
      b.onclick = () => showTrajectory(b.dataset.run));
    root.querySelectorAll(".eval").forEach((b) =>
      b.onclick = () => { ctx.evalRun = b.dataset.run; ctx.go("skills"); });
  }

  function statusBadge(r) {
    if (r.running) return `<span class="badge run">${t("hist.running")}</span>`;
    if (r.returncode && r.returncode !== 0) return `<span class="badge err">${t("hist.failed")}</span>`;
    return `<span class="badge ok">${t("hist.done")}</span>`;
  }

  async function showTrajectory(runId) {
    root.querySelectorAll(".run-row").forEach((r) =>
      r.classList.toggle("active", r.dataset.run === runId));
    q("#traj").innerHTML = t("common.loading");
    let data;
    try { data = await get(`/api/train/${runId}/trajectory`); }
    catch (e) { q("#traj").innerHTML = `<p class="hint">${escapeHtml(e.message)}</p>`; return; }
    const steps = data.steps || [];
    if (!steps.length) {
      q("#traj").innerHTML = `<p class="hint">${t("hist.noTraj")}</p>`; return;
    }
    const nAcc = steps.filter((s) => ACCEPT.has(s.action)).length;
    const nRej = steps.filter((s) => s.action === "reject").length;
    q("#traj").innerHTML = `
      <div class="traj-head">
        <code>${escapeHtml(runId)}</code>
        <span class="badge ok">${t("hist.accepts")}: ${nAcc}</span>
        <span class="badge err">${t("hist.rejects")}: ${nRej}</span>
      </div>
      ${sparkline(steps)}
      <div class="traj-list">
        ${steps.map((s) => stepRow(s)).join("")}
      </div>`;
  }

  function sparkline(steps) {
    const W = 320, H = 60, n = steps.length;
    const ys = steps.map((s) => s.current_score ?? s.best_score ?? 0);
    const lo = Math.min(...ys, 0), hi = Math.max(...ys, 1);
    const pts = ys.map((y, i) =>
      `${(i / Math.max(1, n - 1)) * W},${H - ((y - lo) / (hi - lo || 1)) * H}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2"/></svg>`;
  }

  function stepRow(s) {
    const acc = ACCEPT.has(s.action);
    const cls = acc ? "ok" : (s.action === "reject" ? "err" : "muted");
    const arrow = (s.score_before != null && s.score_after != null)
      ? `${fmtScore(s.score_before)} → ${fmtScore(s.score_after)}` : "";
    return `<div class="traj-row ${cls}">
      <span class="t-step">#${s.step ?? "?"}</span>
      <span class="badge ${cls}">${escapeHtml(s.action)}</span>
      <span class="t-score">${arrow}</span>
      ${s.edit_budget != null ? `<span class="muted">${t("hist.budget")} ${s.edit_budget}</span>` : ""}
      ${s.skill_len != null ? `<span class="muted">${s.skill_len} ch</span>` : ""}
    </div>`;
  }

  q("#refresh").onclick = loadRuns;
  await loadRuns();
  // Deep-link from Monitor / Skills ("view this run's trajectory").
  if (ctx.trajRun) { showTrajectory(ctx.trajRun); ctx.trajRun = null; }
  return {};
}
