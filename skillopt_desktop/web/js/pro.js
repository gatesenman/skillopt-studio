// Pro mode: full config control (benchmark, separate optimizer/target models,
// training-discipline knobs, raw overrides). Keys map 1:1 to SkillOpt's schema.
import { get, post, toast } from "./api.js";
import { t } from "./i18n.js";
import { icon } from "./icons.js";

const SCHEDULERS = ["", "cosine", "linear", "constant", "autonomous"];
const UPDATE_MODES = ["", "patch", "rewrite_from_suggestions", "full_rewrite_minibatch"];
const EFFORTS = ["", "low", "medium", "high"];

export async function render(root, ctx) {
  const [benchmarks, backends] = await Promise.all([
    get("/api/benchmarks"), get("/api/backends"),
  ]);
  const backendOpts = (sel) =>
    `<option value="">${t("pro.demoMock")}</option>` +
    backends.map((b) => `<option value="${b.id}"${b.id === sel ? " selected" : ""}>` +
      `${b.name}${b.configured ? " ✓" : ""}</option>`).join("");
  const optList = (arr) => arr.map((v) =>
    `<option value="${v}">${v || t("pro.inherit")}</option>`).join("");

  root.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>${t("pro.cfgTitle")}</h3>
        <p class="hint">${t("pro.cfgHint")} <code>--cfg-options</code>.</p>
        <label class="field"><span>${t("pro.benchEnv")}</span>
          <select id="bench">${benchmarks.map((b) => `<option>${b}</option>`).join("")}</select></label>

        <h4 class="sec">${t("pro.modelsTitle")}</h4>
        <p class="hint">${t("pro.modelsHint")}</p>
        <div class="grid cols-2">
          <label class="field"><span>model.target_backend</span>
            <select id="targetBackend">${backendOpts("")}</select></label>
          <label class="field"><span>model.optimizer_backend</span>
            <select id="optimizerBackend">${backendOpts("")}</select></label>
        </div>
        <div class="grid cols-2">
          <label class="field"><span>model.target ${t("pro.modelNameHint")}</span>
            <input id="targetModel" type="text" placeholder="${t("pro.optional")}" /></label>
          <label class="field"><span>model.optimizer ${t("pro.modelNameHint")}</span>
            <input id="optimizerModel" type="text" placeholder="${t("pro.optional")}" /></label>
        </div>
        <label class="field"><span>model.reasoning_effort</span>
          <select id="reasoning">${optList(EFFORTS)}</select></label>

        <h4 class="sec">${t("pro.trainTitle")}</h4>
        <div class="grid cols-3">
          <label class="field"><span>train.num_epochs</span><input id="epochs" type="number" value="4" min="1" /></label>
          <label class="field"><span>train.batch_size</span><input id="batch" type="number" value="40" min="1" /></label>
          <label class="field"><span>gradient.merge_batch_size</span><input id="merge" type="number" value="8" min="1" /></label>
        </div>
        <div class="grid cols-3">
          <label class="field"><span>optimizer.learning_rate ${t("pro.lrHint")}</span><input id="lr" type="text" placeholder="${t("pro.optional")}" /></label>
          <label class="field"><span>gradient.minibatch_size</span><input id="mb" type="text" placeholder="${t("pro.optional")}" /></label>
          <label class="field"><span>optimizer.min_learning_rate</span><input id="minLr" type="text" placeholder="${t("pro.optional")}" /></label>
        </div>

        <h4 class="sec">${t("pro.disciplineTitle")}</h4>
        <p class="hint">${t("pro.disciplineHint")}</p>
        <div class="grid cols-2">
          <label class="field"><span>optimizer.lr_scheduler</span>
            <select id="lrSched">${optList(SCHEDULERS)}</select></label>
          <label class="field"><span>optimizer.skill_update_mode</span>
            <select id="updMode">${optList(UPDATE_MODES)}</select></label>
        </div>
        <div class="toggles">
          <label class="chk"><input id="useGate" type="checkbox" checked /> <span>evaluation.use_gate ${t("pro.gateHint")}</span></label>
          <label class="chk"><input id="slowUpdate" type="checkbox" /> <span>optimizer.use_slow_update</span></label>
          <label class="chk"><input id="metaSkill" type="checkbox" /> <span>optimizer.use_meta_skill</span></label>
        </div>

        <label class="field"><span>${t("pro.raw")}</span>
          <textarea id="raw" placeholder="train.seed=0&#10;env.max_steps=30"></textarea></label>
        <label class="field"><span>${t("pro.evalSkill")}</span>
          <input id="evalSkill" type="text" placeholder="${t("pro.evalSkillPh")}" /></label>
        <div class="btn-row">
          <button class="btn primary" id="train">${icon("play")} ${t("pro.startTrain")}</button>
          <button class="btn ghost" id="evalBtn">${t("pro.evalOnly")}</button>
        </div>
      </div>
      <div class="card">
        <h3>${t("pro.preview")}</h3>
        <p class="hint">${t("pro.previewHint")}</p>
        <div class="codeblock" id="cfgPreview">${t("common.loading")}</div>
        <div id="validateBox" class="validate-box"></div>
      </div>
    </div>`;

  const q = (id) => root.querySelector(id);
  const val = (id) => q(id).value.trim();
  const num = (id) => +q(id).value;

  function overrides() {
    const o = {
      "train.num_epochs": num("#epochs"),
      "train.batch_size": num("#batch"),
      "gradient.merge_batch_size": num("#merge"),
      "evaluation.use_gate": q("#useGate").checked,
      "optimizer.use_slow_update": q("#slowUpdate").checked,
      "optimizer.use_meta_skill": q("#metaSkill").checked,
    };
    if (val("#targetBackend")) o["model.target_backend"] = val("#targetBackend");
    if (val("#optimizerBackend")) o["model.optimizer_backend"] = val("#optimizerBackend");
    if (val("#targetModel")) o["model.target"] = val("#targetModel");
    if (val("#optimizerModel")) o["model.optimizer"] = val("#optimizerModel");
    if (val("#reasoning")) o["model.reasoning_effort"] = val("#reasoning");
    if (val("#lr")) o["optimizer.learning_rate"] = val("#lr");
    if (val("#minLr")) o["optimizer.min_learning_rate"] = val("#minLr");
    if (val("#mb")) o["gradient.minibatch_size"] = val("#mb");
    if (val("#lrSched")) o["optimizer.lr_scheduler"] = val("#lrSched");
    if (val("#updMode")) o["optimizer.skill_update_mode"] = val("#updMode");
    val("#raw").split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => {
      const i = l.indexOf("="); if (i > 0) o[l.slice(0, i).trim()] = l.slice(i + 1).trim();
    });
    return o;
  }
  function configPath() { return `configs/${q("#bench").value}/default.yaml`; }
  // The "run backend" used to auto-fill any backend the user left on demo/mock.
  function runBackend() { return val("#targetBackend") || val("#optimizerBackend"); }

  async function preview() {
    const o = overrides();
    q("#cfgPreview").textContent = `# ${configPath()}\n${t("pro.previewNote")}\n` +
      Object.entries(o).map(([k, v]) => `${k}: ${v}`).join("\n");
    // Pre-flight: flag any override key SkillOpt would silently ignore.
    try {
      const r = await post("/api/config/validate", { config_path: configPath(), overrides: o });
      const box = q("#validateBox");
      if (!r.checked) { box.className = "validate-box"; box.textContent = ""; return; }
      if (r.unknown.length) {
        box.className = "validate-box warn";
        box.innerHTML = `${t("pro.unknownKeys")}<br><code>${r.unknown.join("</code> <code>")}</code>`;
      } else {
        box.className = "validate-box ok";
        box.textContent = t("pro.allKeysOk");
      }
    } catch { /* validation is best-effort */ }
  }

  root.querySelectorAll("input, select, textarea").forEach((n) => {
    n.addEventListener(n.tagName === "SELECT" || n.type === "checkbox" ? "change" : "input", preview);
  });
  preview();

  q("#train").onclick = async () => {
    try {
      const r = await post("/api/train/start", { config_path: configPath(),
        backend: runBackend(), overrides: overrides(), mock: !runBackend() });
      ctx.currentRun = r.run_id; toast(t("pro.trainStarted"), "ok"); ctx.go("monitor");
    } catch (e) { toast(e.message, "err"); }
  };
  q("#evalBtn").onclick = async () => {
    try {
      const skill = val("#evalSkill");
      if (runBackend() && !skill) { toast(t("pro.evalNeedsSkill"), "err"); return; }
      const r = await post("/api/eval/start", { config_path: configPath(),
        backend: runBackend(), mock: !runBackend(), overrides: overrides(),
        skill_path: skill });
      ctx.currentRun = r.run_id; toast(t("pro.evalStarted"), "ok"); ctx.go("monitor");
    } catch (e) { toast(e.message, "err"); }
  };
  return {};
}
