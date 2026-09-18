# Plugin layout

Every plugin in `plugins/<name>/` is one directory that four clients can load.
The portable parts follow [Agent Plugins 1.0](https://agent-plugins.org/specification);
the vendor-specific parts sit where each client already looks, and each client
ignores the others' files.

```
plugins/<name>/
├── plugin.json                  # Agent Plugins 1.0 manifest. Source of truth for name/version/description.
├── .claude-plugin/plugin.json   # Claude Code manifest  (same name/version/description)
├── .codex-plugin/plugin.json    # Codex manifest        (same, plus "skills": "./skills/" and "interface")
├── .cursor-plugin/plugin.json   # Cursor manifest       (same, plus "skills", "agents", "hooks" paths)
├── skills/<skill>/SKILL.md      # Portable. Loaded by all four clients.
├── mcp.json                     # Portable MCP servers (Agent Plugins format), optional
├── agents/*.md                  # Subagents for Claude Code and Cursor (shared frontmatter subset)
├── hooks/hooks.json             # Claude Code + Codex hooks (Claude format), optional
├── com.github.copilot/          # Copilot-only: agents/*.agent.md, hooks/hooks.json, commands/
├── README.md, CHANGELOG.md, LICENSE
```

## What each client reads

| Component | Claude Code | Codex | Copilot | Cursor |
| --- | --- | --- | --- | --- |
| Manifest | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` | root `plugin.json` (`$schema` present → Agent Plugins mode) | `.cursor-plugin/plugin.json` when present, else root `plugin.json` |
| Skills | `skills/` | `skills/` | `skills/` | `skills/` |
| MCP | `.mcp.json` | `.mcp.json` or `mcp.json` | `mcp.json` | `mcp.json` |
| Subagents | `agents/*.md` | not bundled in plugins | `com.github.copilot/agents/*.agent.md` (root `agents/` is read too) | `agents/*.md` |
| Hooks | `hooks/hooks.json` | `hooks/hooks.json` (Claude format) | `com.github.copilot/hooks/hooks.json` (Copilot format) | path set in `.cursor-plugin/plugin.json` (Cursor format) |

Rules that keep this working:

- Root `plugin.json` may only contain the keys the spec allows (`$schema`, `name`,
  `version`, `description`, `author`, `homepage`, `repository`, `license`,
  `keywords`, `extensions`). Put vendor catalog hints under `extensions`, e.g.
  `"extensions": {"com.openai.codex": {"category": "Engineering"}}`.
- `name`, `version`, and `description` must be identical across all four manifests.
  `scripts/build_marketplaces.py --check` enforces this.
- Skill directory name must equal the `name:` in its `SKILL.md` frontmatter.
- Bump `version` in all four manifests on every release; clients cache by version.
- Agent frontmatter shared by Claude and Cursor: `name`, `description`, `model`,
  `tools` (Claude), `readonly` (Cursor). Each client ignores the other's keys.
- Hook formats differ by vendor. Do not point Cursor or Copilot at a Claude-format
  `hooks/hooks.json`; give them their own file.

## Adding a plugin

1. Create `plugins/<name>/` with the four manifests and at least one skill.
2. Run `python3 scripts/build_marketplaces.py` to regenerate the four catalogs.
3. Run `claude plugin validate .` and, from a scratch project, install from the
   local checkout with each CLI you have (see the README's local development section).
4. Commit the regenerated catalogs with the plugin.
