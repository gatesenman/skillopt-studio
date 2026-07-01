# SkillOpt Studio — 资深 AI 开发工程师视角的功能差距分析

> 目标：以"实际使用者"身份跑一遍原仓库 `microsoft/SkillOpt`（训练 / 评估 / Sleep / WebUI / 插件）
> 与当前 `SkillOpt Studio`，找出**本应具备但缺失**的功能，并特别标注那些会
> **丢失原仓库核心要解决问题**的地方（技能像训练神经网络一样被优化：
> rollout→reflect→aggregate→select→update→evaluate + held-out gate，
> 由一个独立 optimizer 模型对 frozen target 模型的技能文档做有界 add/delete/replace 编辑）。

分析基于真实代码核对（已在 VM 上跑通 Studio 与原引擎）。每条给出：**缺什么 / 为何重要 / 证据 / 建议补法**。

---

## 修复进度（本轮已完成）

| 项 | 状态 | 说明 |
|----|------|------|
| **P0-1 超参 key 映射 + 未知 key 校验** | ✅ 已修复 | Pro 模式 override 走 `configspec.py` 规范化到真实 schema；提交前预检未知 key 并告警（`/api/config/validate`）。 |
| **P0-2 optimizer / target 拆分** | ✅ 已修复 | `_build_argv` 支持 `model.optimizer_backend` 独立于 `model.target_backend`；UI 暴露独立后端/模型字段。 |
| **P0-3 训练纪律旋钮** | ✅ 已修复 | Pro 模式暴露 `lr_scheduler / use_slow_update / use_meta_skill / use_gate / skill_update_mode / min_lr`。 |
| **P1-5 运行历史 / 结果浏览** | ✅ 已修复 | `GET /api/runs` + 运行历史页（状态、分数、产物路径）。 |
| **P1-6 编辑轨迹可视化** | ✅ 已修复 | `GET /api/train/{id}/trajectory` + 每步 action / score_before→after / gate accept/reject。 |
| **P1-7 技能库一键评测** | ✅ 已修复 | 技能详情页一键评测；基准默认规范化到技能对应 benchmark；**留空后端=演示模式，模拟 held-out 评测而非调用真实 env-heavy `eval_only`**（修复了此前在 alfworld 上的崩溃）。 |

> P2 级（MCP 多编辑器集成、Sleep 定时、部署回路等）保留在下方未修复列表，按需后续推进。

---

## P0 — 直接削弱原仓库核心方法的缺陷（最该先修）

### P0-1. 专家模式的超参 key 写错，被引擎静默忽略 ❗
- **缺什么**：Pro 模式把"学习率 / minibatch / group_size / holdout"这几个最核心的旋钮发给后端，但 key 名与真实 config schema 不一致。
- **证据**：
  - Studio 发送：`optimizer.lr` / `gradient.minibatch` / `train.group_size` / `evaluation.holdout`
    （`skillopt_desktop/web/js/pro.js:52-56`）
  - 真实 schema：`optimizer.learning_rate` / `gradient.minibatch_size` /（无 group_size，应是 `gradient.merge_batch_size`）/ `evaluation.use_gate`（`~/SkillOpt/configs/_base_/default.yaml`）
  - `apply_overrides()` 对未知 key **不报错、直接塞进 config**（`~/SkillOpt/skillopt/config.py:236-258`），所以这些值被写进 dict 但训练引擎从不读取。
- **为何重要**：用户以为在"调 DL 式优化器"，实际这些设置**全部无效**——恰恰把 SkillOpt 的灵魂（可控的学习率 / 验证门控）弄丢了。
- **建议**：把 Pro 旋钮一一映射到真实 key；并加一个"未知 key 校验"（对照 `flatten_config` 的合法键集合，UI 给红色提示），从根上杜绝静默失效。

### P0-2. 强制 optimizer 模型 == target 模型，无法表达方法的核心设定 ❗
- **缺什么**：无法分别设置"优化器模型"和"目标模型"（以及各自的 model 名/reasoning effort）。
- **证据**：`training.py:_build_argv` 把同一个 backend 同时写给
  `model.target_backend` 和 `model.optimizer_backend`；Pro UI 只有一个 backend 下拉、无 model 名输入（`pro.js:18-22`）。
- **为何重要**：SkillOpt 的整篇论文前提是"**独立 optimizer 模型**为 frozen target 模型改写技能"。强行二者相等，等于阉割了方法本身（也无法复现"小模型 target + 强模型 optimizer"这类关键用法）。
- **建议**：Pro 模式拆成 target / optimizer 两组（backend + model + reasoning_effort），分别映射 `model.target*` / `model.optimizer*`。

### P0-3. 缺少"训练纪律"旋钮，连上游 Gradio WebUI 都不如
- **缺什么**：`lr_scheduler`(cosine/linear/constant/autonomous)、`use_slow_update`、`use_meta_skill`、`use_gate`、`min_learning_rate`、`skill_update_mode`(patch/rewrite/full_rewrite)。
- **证据**：原 WebUI 已暴露 LR scheduler / slow update / meta skill / gate 四个开关
  （`~/SkillOpt/skillopt_webui/app.py:495-516`）；Studio Pro 只有 epochs/batch/group/lr/minibatch/holdout + 一个 raw 文本框。
- **为何重要**：这些正是"让技能训练稳定"的 SkillOpt 招牌机制；新手在 Studio 里根本看不到，等于把专业能力藏没了（raw 框要求用户自己背 key，不算可用）。
- **建议**：Pro 模式补这组开关（带中英文 tooltip 解释 DL 类比），下沉为"高级"折叠区。

---

## P1 — 阻断"真实（非演示）使用"的工作流缺口

### P1-4. 没有数据准备流程 → 真实训练几乎跑不起来
- **缺什么**：真实 benchmark 需要数据集与 split（`env.split_dir` / `data_path`，如 `data/searchqa_split`）。Studio 无任何"导入数据/生成 split"的引导。
- **为何重要**：面向"非技术能人/小白"是产品定位，但没有数据，向导跑出来的只有 mock 演示；一旦切真实 backend 就缺数据而失败。
- **建议**：向导加"数据来源"步骤（内置样例数据集下载 / 选本地目录 / 调 `scripts/materialize_*`），并做存在性预检。

### P1-5. 没有运行历史 / 结果浏览器
- **缺什么**：历史 run 列表、每步 score 曲线、多 run 对比。
- **证据**：原 WebUI 有 Results 标签扫描 `outputs/`（run/bench/score/steps，`skillopt_webui/app.py` Results tab）；Studio 无 `/api/runs` 列表（仅靠 `best_skill.md` 反推技能列表）。
- **建议**：加 `GET /api/runs` + 结果页（步进 score 曲线、状态、产物路径、对比）。

### P1-6. 看不到技能"编辑轨迹"——丢了方法最有辨识度的可视化
- **缺什么**：accept/reject 的有界编辑、rejected-edit buffer、before/after diff、held-out gate 决策。
- **为何重要**：SkillOpt 区别于"一次性让 LLM 写技能"的关键就是"**每个编辑被 held-out 严格门控接受/拒绝**"。Studio 只展示最终 `best_skill.md` + 一条 score 曲线（`skills.py:164-179`），看不到优化过程，专业用户无法判断/复盘。
- **建议**：解析 run 的 jsonl，渲染"每步编辑 + 门控分数 + 接受/拒绝"时间线与 diff。

### P1-7. eval-only 不好用
- **缺什么**：从技能库"一键在 benchmark X 上评测这个技能"。当前 Pro 的 eval 需手填 skill 路径（`pro.js:35-36,81-88`）。
- **建议**：技能库每个技能加"评测"按钮，自动带入 skill 路径 + 选 benchmark。

---

## P2 — 集成与体验（锦上添花，但属"本应有"）

### P2-8. 编辑器/智能体集成只做了 ACP，漏掉原仓库已有的 MCP 生态
- **证据**：原仓库自带 Copilot / Devin / Claude Code / Codex / openclaw 的插件与 MCP server
  （`~/SkillOpt/plugins/*`）；Studio 只做了 ACP（Zed）注册。
- **建议**：ACP 页扩成"接入中心"，一键安装/生成这些已存在的 MCP 配置（复用上游插件，不重造轮子）。

### P2-9. Sleep 只暴露了少量旋钮，且不能"定时"
- **证据**：`skillopt_sleep` CLI 支持 `scope(all/invoked)`、`source(claude/codex/auto)`、`lookback-hours`、`edit-budget`、`tasks-file`(审阅后回放)、`dry-run`、cron 调度（`plugins/run-sleep.sh`、openclaw scheduler）；Studio sleep 仅传 `backend/max-tasks/auto-adopt`（`services/sleep.py:198-213`）。
- **为何重要**：Sleep 的卖点就是"**夜间自动**自进化"；没有定时与 tasks-file 审阅闭环，等于只剩手动点一下。
- **建议**：补 scope/source/lookback/edit-budget 选项 + "排程每晚运行" + "审阅挖到的任务再回放"。

### P2-10. 真实训练前缺预检与成本守护
- **证据**：原 WebUI 有 `validate_training_config` 预检（端点可达、key 存在等）；Studio 有 backend 连通性测试，但未与"本次 run"绑定（数据是否就绪、gate 配置是否合理、预计调用量/费用）。
- **建议**：launch 前做一次性预检弹窗（数据/凭据/关键配置 + 预估调用次数与花费提示）。

### P2-11. 训练产物的"部署落地"闭环不完整
- **缺什么**：`best_skill.md` 训出来后怎么"立刻用"——作为 system prompt 复制、挂到某个 target 模型/harness、或直接喂给 ACP agent。
- **现状**：技能库能导出到项目 `SKILL.md`（`skills.py:106`），但没有"现在就用它对话/验证提升"的回路。
- **建议**：技能详情页加"用此技能试一句"（带/不带技能对比）+ "复制为系统提示" + "设为 ACP agent 默认技能"。

---

## 不能丢的核心（已具备，务必保留）✅
- 训练管线 6 阶段 + held-out gate 的真实接入（`training.py` 走 `scripts/train.py --config/--cfg-options`）。
- 跨厂商后端：OpenAI / Azure / Claude / Qwen / MiniMax / Codex CLI / Claude Code CLI（`backends.py`）。
- 6 个可用 benchmark（alfworld/docvqa/livemathematicianbench/officeqa/searchqa/spreadsheetbench）。
- Sleep 夜间自进化真实 CLI 接入（offline mock 可零 key 跑通）。
- ACP Agent（JSON-RPC stdio）+ 一键写编辑器配置。
- 中英文 i18n、字体矢量图标、三端兼容（UTF-8、跨平台路径）。

---

## 建议修复顺序
1. **P0-1 / P0-2 / P0-3**（核心保真，工作量小、收益最大；本质是 key 映射 + 增加几个字段/开关）。
2. **P1-5 / P1-6**（运行历史 + 编辑轨迹，让"优化过程"可见，这是产品说服力来源）。
3. **P1-4**（数据准备，打通真实训练）。
4. **P2-9 / P2-8 / P2-11 / P1-7 / P2-10**（自动化、集成、落地闭环）。
