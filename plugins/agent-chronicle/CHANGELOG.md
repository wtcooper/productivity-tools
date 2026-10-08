# Changelog

## 0.1.0 — 2026-10-07

- Initial release. `chronicle` skill: agentsview + git extraction (worktree merging, subagent folding,
  prompt cleanup, secret redaction, commit-to-session linking, signals, token-budgeted digests), a
  deterministic audit ledger, an evidence gate for all model output, and rendering of `chronicle.html`
  (storyboard with Present mode) and `brief.md`.
- `dev-coach` skill: an 8-dimension rubric scored against real prompts and the user's own CLAUDE.md
  rules, rendered as `coach.html` with a trend against earlier runs.
- Artifacts are written to the project's `.agent-chronicle/` folder; session-derived data stays in
  `~/.agent-chronicle/` and agentsview, never in a project.
- `archive.py`: gzip copies of every raw session file agentsview indexes, kept indefinitely, so sessions
  survive agent retention sweeps and can be re-parsed later.
- `session-digester`, `story-editor`, and `practice-coach` subagents; a `SessionEnd` hook that runs
  `agentsview sync` and the archive; manifests for Agent Plugins 1.0, Claude Code, Codex, Cursor, and GitHub Copilot.
