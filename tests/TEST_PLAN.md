# SkillOpt Studio — E2E Test Plan

App under test: `skillopt-studio --no-window --port 8765` (running locally), opened in Chrome at `http://127.0.0.1:8765/`. Demo mode is used (no provider credentials), which exercises the full pipeline via `TrainingService._run_mock`.

## Test 1 — Beginner wizard runs a full optimization (primary flow)
Steps:
1. On 向导模式, click the **优化文档问答技能 (DocVQA)** preset card.
   - PASS: card gets selected (indigo border), 下一步 button enabled.
2. Click 下一步 → on 连接厂商 leave provider as **演示模式**, click 下一步.
3. On 开始优化, summary shows 目标=优化文档问答技能, 厂商=演示模式. Click **🚀 开始优化**.
   - PASS: toast "已启动优化", auto-navigates to 训练监控.

## Test 2 — Monitor shows live pipeline + completion
4. On 训练监控:
   - PASS: the 6 stage chips (rollout→reflect→aggregate→select→update→gate) highlight in sequence; progress bar grows from 0→100%; epoch/step counters increment; **best held-out** shows a number that increases (e.g. ~0.45→~0.6+).
   - PASS: log box streams coloured lines incl. `[rollout] ...`, `held-out score: 0.xxx`, and ends with `[demo] exported best_skill.md (N tokens)`.
   - PASS: run state badge flips from 运行中 → 完成; stop button disables.
   - FAIL if: stages never highlight, progress stuck at 0, or no `exported best_skill.md` line.

## Test 3 — Skill library shows the produced artifact
5. Click 技能库.
   - PASS: at least one row with 来源=训练, 基准=docvqa (or demo), tokens > 0.
6. Click the row.
   - PASS: detail panel shows the `# Skill for ...` markdown content with "When to use" / "Procedure" sections.
   - FAIL if: table is empty or detail content is blank.

## Test 4 — ACP integration surface
7. Click ACP 接入.
   - PASS: shows a launch command containing `skillopt-acp` (or `python -m skillopt_acp.server`); shows the editor config snippet JSON with `agent_servers.skillopt`; commands table lists `optimize`, `sleep`, `skills`, `help`.

## Already-verified (shell, not recorded)
- `pytest -q`: 10 passed (ACP agent dispatch/stream/error + API health/presets/benchmarks/backends/demo-train/sleep/acp).
- ACP stdio: piped initialize + session/new + prompt("skills") → valid JSON-RPC responses with protocolVersion=1 and session/update streaming.
