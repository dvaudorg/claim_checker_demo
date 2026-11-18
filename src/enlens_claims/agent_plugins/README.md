# ENLENS for the agent CLIs of other providers (stage 2)

ENLENS writes these files into each CLI's own places when the person presses *Add ENLENS to Codex* or *Add ENLENS to
Antigravity* in Settings → AI (agentcli.py). The helpers' instructions are the same as Claude Code's
(`claude_plugin/agents/*.md`, their bodies); only the orchestrating skill differs.

- `codex-SKILL.md`: the skill `$enlens-run`, written to `~/.agents/skills/enlens-run/SKILL.md`; the helpers become
  `~/.codex/agents/enlens-<helper>.toml`; the connector is added with `codex mcp add enlens …`.
- `antigravity/`: the plugin written to `<ENLENS data folder>/agy-plugin/enlens-run/` (`plugin.json`, the skill,
  `agents/*.md`, `mcp_config.json`) and installed with `agy plugin install`.

*Start Codex* and *Start Antigravity* in the app do not use the skill: ENLENS starts one CLI process per helper itself,
with the helper's instructions as its prompt (agentcli.start_run).

Placeholders: `{{VERSION}}`, `{{TITLE}}` (Codex, Antigravity).
