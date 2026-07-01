# SkillOpt ACP agent

SkillOpt Studio ships an **Agent Client Protocol** (ACP) agent so any
ACP-compatible editor or AI dev agent (e.g. Zed) can drive SkillOpt's skill
optimization over JSON-RPC on stdio — cross-vendor, no code changes.

## Launch command

```
skillopt-acp
# fallback if the console script is not on PATH:
python -m skillopt_acp.server
```

## Register in an editor (Zed example)

Add to `~/.config/zed/settings.json` (the desktop app's **ACP 接入** tab can do
this for you with one click):

```json
{
  "agent_servers": {
    "skillopt": { "command": "skillopt-acp", "args": [], "env": {} }
  }
}
```

## Commands (sent as a prompt turn)

| Command | Description |
| --- | --- |
| `optimize <benchmark|config.yaml> [key=value ...]` | Train & export a skill |
| `sleep <run|dry-run|adopt|status> [project=DIR backend=mock]` | Run SkillOpt-Sleep |
| `skills [list]` | List skill artifacts |
| `help` | Usage |

Progress streams back as `session/update` notifications; each turn ends with a
`stopReason`.
