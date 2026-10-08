# agent-chronicle

The story of how your coding agents built a project, and how you can direct them better.

Every project built with agents leaves two records: the session transcripts, which say why each piece of
work happened, and git, which says what landed. Nobody reads either end to end. `agent-chronicle` joins
them and writes these artifacts to the project's `.agent-chronicle/` folder (commit them or not, your call;
session data itself never goes there):

| Output | For | What it shows |
|---|---|---|
| `chronicle.html` | Leadership, stakeholders, new teammates | A storyboard from the original problem and intent, through chapters, episodes, and pivots, to what shipped. Has a **Present** mode (arrow keys, one chapter per frame). Self-contained, so you can email it. |
| `brief.md` | Anyone | A one-page written version of the story. Can be handed to `pptx-brand` for an on-brand deck. |
| `audit.md` / `audit.csv` | You, reviewers | One row per session: intent, files, commits, tests, interrupts, corrections, compactions, health, flags, plus commits no session explains. No model involved. |
| `coach.html` (+ `coach-history.json`) | You | Your framing, planning, context, verification, steering, session hygiene, version control, and delegation, scored 1-4 against a rubric and your own CLAUDE.md rules. Quotes your real prompts, rewrites weak ones, picks 3 habits to change, and shows the trend since the last run. |

Works in Claude Code, OpenAI Codex, GitHub Copilot, and Cursor. Install instructions are in the
[repository README](../../README.md#install); substitute `agent-chronicle` for the plugin name.

## How it works

```
agentsview index ─┐
                  ├─ extract.py ─ timeline · signals · digests ─┬─ audit.py ──────────────────────────── audit.md/.csv
git history ──────┘   (no model)                                ├─ session-digester ─ cards ─ story-editor ─ render ─ chronicle.html, brief.md
                                                                └─ practice-coach ─ render ──────────── coach.html
                                         every model step is gated by check_evidence.py
```

- **[agentsview](https://github.com/kenn-io/agentsview) is the index.** It reads 60+ agents' session formats
  (Claude Code, Codex, Copilot, Cursor, Gemini, and more) into one local SQLite database. This plugin reads it
  only through its JSON CLI.
- **Nothing is ever dropped.** agentsview has no automatic pruning and keeps a session after its source file is
  deleted. It stores parsed rows, not raw files, so `archive.py` adds a gzip copy of every raw transcript it
  indexes to `~/.agent-chronicle/archive/`. That archive is only added to or refreshed, never trimmed, so any
  session can be re-parsed later for something the index missed.
- **Scripts compute the facts.** `extract.py` merges git worktrees into their repo, folds subagent sessions
  into their parents, strips harness-injected text from prompts, redacts secrets, links commits to the session
  that made them (time window, `git commit` calls, file overlap, `Co-Authored-By` trailers), and counts signals:
  plan before code, tests run and failed, interrupts, corrections, churn, rollbacks, compactions, subagent use.
- **The model writes only the narrative**, in your own agent session, so no API key is needed. Sessions are
  reduced to token-budgeted digests (~12k tokens each). `session-digester` turns each digest into a card, and
  `story-editor` turns the cards into `story.json`. Cards are cached by digest hash, so re-runs only process new sessions.
- **Every claim cites evidence.** `check_evidence.py` fails a run on any unknown evidence id, any quote that is
  not verbatim, a missing required field, or anything that looks like a secret. Dates and counts are never
  model-written; rendering adds them from computed data.

## Requirements

| Need | For |
|---|---|
| [agentsview](https://agentsview.io) v0.44+ (`brew install --cask agentsview`) | Everything. Its read commands start a local server on 127.0.0.1:8080; `agentsview daemon stop` stops it |
| Python 3.10+ and [`uv`](https://docs.astral.sh/uv/) (or plain `python3`) | The scripts; standard library only |
| git | Commit history (optional, but the story is much weaker without it) |

## Use

Ask in a session, from inside the project:

- "Tell the story of how this project was built" → `chronicle`
- "Audit the agent sessions behind this repo" → `chronicle` (audit only, no model cost)
- "Make a leadership presentation of how we built this" → `chronicle`, then Present mode or `pptx-brand`
- "Coach me on how I direct agents in this project" → `dev-coach`

Or run the deterministic parts yourself from `skills/chronicle/`:

```bash
uv run scripts/doctor.py                        # prerequisites, storage policy, archive, retention risk
uv run scripts/extract.py --list                # every project agentsview knows about
uv run scripts/extract.py --project ~/code/app  # pull, join, digest
uv run scripts/audit.py --project ~/code/app    # ~/code/app/.agent-chronicle/audit.md + audit.csv
```

Cost: the map step reads each pending digest once. `extract.py` prints the estimate; a project with a
week of heavy sessions is roughly 120k input tokens. Use `--since YYYY-MM-DD` to narrow it.

## Data and privacy

- Everything stays on your machine except the digest text sent to the model you are already using. Nothing is
  uploaded anywhere (agentsview's own hosted `raw-sync` is not used).
- Session data lives outside your projects: agentsview's `~/.agentsview/sessions.db`, plus
  `$AGENT_CHRONICLE_HOME` (default `~/.agent-chronicle`) with `archive/` (raw transcripts) and `work/<project>/`
  (timeline, digests, prompts, cards; regenerable).
- Only the artifacts above are written into a project, in `.agent-chronicle/`. The plugin never commits them.
- Prompts, commands, and agent text are redacted for common secret formats before they are written anywhere.
- `chronicle.html` and `brief.md` contain no prompt or agent text by default; `render.py chronicle --quotes`
  adds excerpts. `audit.md` and `coach.html` quote your prompts; treat them as private.

## Keep your history

Claude Code deletes transcripts older than `cleanupPeriodDays` (default **30**), including subagent
transcripts and plans; Gemini CLI also defaults to 30 days. Whatever agentsview and the archive saw before
that is kept indefinitely. This plugin's `SessionEnd` hook runs `agentsview sync` and then `archive.py` in the
background after every Claude Code session; the sync also starts the agentsview server, which keeps watching
for new sessions from every agent. `extract.py` runs both too. `doctor.py` checks agentsview's
`archive_content` setting (must stay `"full"`), the archive, and your Claude retention. To keep originals in
place as well, add `"cleanupPeriodDays": 3650` to `~/.claude/settings.json`.

## Limitations

- History deleted before agentsview indexed it is gone. The audit lists commits that predate the first
  captured session, so the gap is visible rather than silent.
- Commit-to-session links are heuristic. Commits made by hand or outside a session's time window stay unlinked
  and are listed separately.
- Codex runs commands and edits inside `exec` scripts; the plugin parses those, but test detection there is coarser.
- The hook is Claude Code format (Codex reads the same file but has no `SessionEnd` event). On other clients,
  keep the agentsview server running or run `agentsview sync` yourself.
