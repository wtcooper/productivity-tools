# Plan: `agent-chronicle` plugin

Status: v0.1.0 built (phases 0-4) · 2026-10-07. Code: [plugins/agent-chronicle](../../plugins/agent-chronicle/).

## As built: Phase 0 results and changes to this plan

agentsview v0.44 was a **go** as the index. Its JSON CLI (`session list`, `session messages`) covers everything the plan needs:

- prompts, with `source_subtype` marking task notifications, queued commands, and compaction boundaries
- full tool inputs and results
- `subagent_session_id` and `parent_session_id`
- compaction summaries
- per-session quality counters and health

Things the spike found:

- **The daemon.** agentsview read commands need its local daemon and start it automatically. `AGENTSVIEW_NO_DAEMON=1` disables reads.
- **Pagination.** `session messages` returns at most 1000 messages per page. `session list` paginates with `next_cursor`.
- **Codex.** Codex runs commands and `apply_patch` inside JavaScript `exec` calls, so commands and edited files are regex-parsed from that code.
- **Permission mode.** agentsview doesn't expose it, so the audit doesn't show it.

Simplifications against the plan below:

- **Scripts.** The planned `resolve_project` / `source_agentsview` / `git_link` became:
  - `source_agentsview.py`, the only file that calls agentsview
  - `gitlog.py`
  - `extract.py`, which also does project resolution and commit linking
  - `signals.py`
  - `digest.py`
  - `bundle.py`, which feeds the story-editor
- **Not built:**
  - `projects.json` aliases
  - recovering lost transcripts from `history.jsonl`; instead, commits that predate the first captured session are reported as a visible gap
- **Hook.** The `SessionEnd` hook runs `agentsview sync` inline. Codex has no `SessionEnd` event, so it gets no capture hook.
- **Templates.** Both report templates (`chronicle.html`, `coach.html`) live in `skills/chronicle/templates/`.
- **Artifacts and retention** (changed after review):
  - Artifacts go to `<project>/.agent-chronicle/`, not `~/.agent-chronicle/reports/`; session-derived data never goes into a project.
  - agentsview keeps parsed sessions indefinitely: there is no automatic pruning, and sessions survive the deletion of their source file. It does not keep raw files, and its `raw-sync` feature uploads them to a hosted server, so it is not used.
  - `archive.py` keeps local gzip copies of every raw source instead.

## 1. Purpose

Turn the agent sessions behind a project into three things a developer can use:

| Output | Reader | Job |
| --- | --- | --- |
| **Chronicle** (storyboard) | Leadership, stakeholders, new teammates | Show how the project went from its original intent to what shipped: chapters, milestones, pivots, and why. Presentable as-is. |
| **Audit ledger** | The developer, reviewers | Every session with what it asked for, what the agent did, files and commits touched, backtracks, and permission and safety notes. Each row links to its evidence. |
| **Coach report** | The developer | Score how the work was framed, planned, prompted, verified, and steered against a best-practice rubric. Quote real prompts, show better rewrites, and track the trend across runs. |

Questions a finished run must answer, each with cited evidence:

1. What was the original problem statement and intent? How far did it drift, and when?
2. How was the work planned and prompted? Where was that strong or weak against best practice?
3. What was built, in what order, and why?
4. Where did the work backtrack (reverted, re-planned, abandoned, thrashed), why, and what did it cost?
5. What should the developer do differently on the next project?

Non-goals: building another session browser or search UI (agentsview does that), cost dashboards (ccusage, agentsview), and team or cloud sync.

## 2. Findings that shape the design

- **History is being deleted now.** Claude Code's `cleanupPeriodDays` defaults to 30 and is unset on this machine. The sweep also deletes subagent transcripts, file history, and plans. `craftmetrics` has only `sessions-index.json` left, and the oldest surviving transcript is from 2026-09-08. Capture has to happen before any analysis, and `cleanupPeriodDays` should be raised today regardless of this plugin.
- **The raw logs are too large to replay.** The largest local session has 9,322 JSONL lines and auto-compacted twice at about 970k tokens. The model can only read deterministic digests. The compaction summaries (`isCompactSummary`) already in the logs are free pre-made summaries.
- **The log formats are internal and change.** Claude Code's docs call the JSONL format internal and version-dependent. Codex, Gemini, Copilot, and Cursor each use a different format. Writing our own parsers means maintaining them indefinitely.
- **agentsview already solves capture and indexing.** Repo: [kenn-io/agentsview](https://github.com/kenn-io/agentsview) (MIT, v0.44, active).
  - Reads 60+ agent formats and indexes them into SQLite + FTS5 at `~/.agentsview/sessions.db`.
  - Keeps sessions after their source file is deleted.
  - Already computes prompt-quality counters per session: `unstructured_start`, `missing_success_criteria_count`, `missing_verification_count`, `edit_churn_count`, `runaway_tool_loop_count`, `duplicate_prompt_count`, plus health scores.
  - Exposes JSON CLI exports, a REST API, and a read-only MCP server.
  - Does **not** build a per-project narrative or a leadership story. That gap is this plugin.
- **Built-in `/insights` overlaps only partly.** It writes a usage-wide coaching report (friction, suggestions). It is not project-scoped, not a chronology, and not evidence-linked to individual prompts. The coach report should complement it, not copy it.
- **Git is the ground truth for what shipped.** Commits, reverts, branches, and `Co-Authored-By` trailers anchor the story. The transcripts explain the why.
- **This machine uses both agents.** It has 36 Claude Code project dirs (worktrees appear as separate dirs, e.g. `rooted-skills--claude-worktrees-agent-*`) and 94 Codex rollouts. v1 must cover Claude Code and Codex, and merge worktrees into their parent project.

## 3. Architecture

```
 capture          index                    extract (deterministic)        synthesize (host agent)         render
┌────────────┐  ┌───────────────────┐   ┌──────────────────────────┐   ┌───────────────────────────┐   ┌─────────────────┐
│ agent logs │→ │ agentsview        │ → │ resolve project          │ → │ session-digester (map,    │ → │ chronicle.html  │
│ (CC, Codex,│  │ sessions.db       │   │ timeline.ndjson + git    │   │   parallel, cached)       │   │ brief.md        │
│  …)        │  │ (archive survives │   │ signals + commit links   │   │ story-editor (reduce)     │   │ audit.md / .csv │
│ SessionEnd │  │  retention)       │   │ token-budgeted digests   │   │ practice-coach (rubric)   │   │ coach.html      │
│ hook→sync  │  └───────────────────┘   │ audit ledger (no LLM)    │   │ check_evidence.py (gate)  │   │ (→ pptx-brand)  │
└────────────┘                          └──────────────────────────┘   └───────────────────────────┘   └─────────────────┘
```

Principles:

- **Deterministic first, model second.** Scripts compute everything countable: timelines, signals, commit links, and the audit ledger. The model only interprets: intent, episode boundaries, why something pivoted, rubric judgments.
- **No separate API key.** Synthesis runs in the host agent's own subagents, the way `pptx-brand` uses `deck-builder`. Nothing is sent to an extra endpoint (agentsview's own "Generated Insights" feature is not used).
- **Every claim cites evidence.** Each sentence in `story.json` and `coach.json` carries evidence IDs (`<session>:<ordinal>` or a commit SHA). `check_evidence.py` fails the run on a missing or invalid reference, or on a quote that doesn't match its source. A leadership deck cannot afford invented history.
- **Incremental.** Session cards are cached by content hash. A re-run only digests new or changed sessions, then re-runs the cheap reduce step.

### 3.1 Data storage

The home directory is `$AGENT_CHRONICLE_HOME`, default `~/.agent-chronicle/`. This follows the `PPTX_BRAND_HOME` convention. It deliberately avoids `CLAUDE_PLUGIN_DATA`, which is deleted on uninstall and only exists in Claude Code.

```
~/.agent-chronicle/
├── projects.json                       # project id → paths, worktrees, git remote, aliases
├── work/<project>/
│   ├── timeline.ndjson                 # normalized events (from agentsview + git)
│   ├── signals.json                    # deterministic signals per session/project
│   ├── digests/<session>[.<chunk>].md  # token-budgeted inputs for the map step
│   └── cards/<session>.json            # map outputs, keyed by digest hash
└── reports/<project>/<YYYY-MM-DD>/     # chronicle.html, brief.md, audit.md/.csv, coach.html, story.json, coach.json
```

Reports go outside the repo by default, so transcript excerpts don't get committed by accident. `--out` overrides this.

## 4. Extraction (deterministic)

### 4.1 Project resolution

A project is a git repo root, identified by its remote URL if it has one, otherwise by its path. These all map to that project:

- the repo's own path
- its worktrees, found with `git worktree list` and by the `--claude-worktrees-` naming pattern
- sessions whose `cwd` falls under the root
- renamed paths listed in `projects.json`

`resolve_project.py` prints what it merged, so the user can correct it.

### 4.2 Normalized timeline event

```json
{"id": "s:61d898c7:412", "ts": "...", "session": "61d898c7", "agent": "claude-code",
 "kind": "user_prompt|assistant_text|tool_call|tool_result|plan|compaction|interrupt|denial|subagent|commit",
 "tool": "Edit", "target": "src/app.ts", "text": "<redacted, truncated>", "is_error": false,
 "parent_session": null, "branch": "feature/x"}
```

Prompts are classified as human-typed, slash-command, hook-injected, or meta, so the coach only judges what the human actually wrote.

### 4.3 Signals

These are computed per session and rolled up per project. Fields that agentsview already computes are reused, not recomputed.

| Signal | Detection | Feeds |
| --- | --- | --- |
| Intent statement | First human prompts of the project and of each session; agentsview `unstructured_start`, `missing_success_criteria_count` | Story origin, Coach §1 |
| Plan-first | `ExitPlanMode` / plan file / spec doc written before the first Edit/Write; plan revisions | Story, Coach §2 |
| Context setup | CLAUDE.md / AGENTS.md exists at session time (from git history); file references in prompts; agentsview `no_code_context_count` | Coach §3 |
| Verification | Test or build commands run, with pass/fail; prompts that ask for tests or verification; agentsview `missing_verification_count` | Story, Coach §4 |
| Correction / steering | User interrupts, tool denials, short negative follow-ups ("still broken", "no"), duplicate prompts | Story pivots, Coach §5 |
| Thrash | agentsview `edit_churn_count`, `runaway_tool_loop_count`, `tool_retry_count`; the same file edited N times between failing tests | Backtracks, Coach §5 |
| Session hygiene | Duration, turns, compaction count, distinct goals per session, `/clear` use | Coach §6 |
| Revert / abandon | `git revert` / `reset` / `checkout --`; files created then deleted; branches never merged; agent-written code removed within N days | Backtracks |
| Commit linkage | Session ↔ commit, by time window + branch + file overlap + `Co-Authored-By` trailer; commits and PRs per session | Story "shipped", Coach §7 |
| Delegation | Subagent spawns, parallel agents, model and effort per session | Coach §8 |
| Safety | `bypassPermissions` mode, secret-scanner hits in prompts, destructive commands | Audit, Coach flag |

### 4.4 Digests

Each digest is a Markdown file of at most ~12k tokens. Long sessions are chunked at compaction boundaries and time gaps. A digest contains:

- human prompts in full (after redaction)
- assistant prose, truncated
- one line per tool call (`Edit src/app.ts (+12/−3)`, `Bash pytest → 3 failed`)
- errors
- compaction summaries
- the linked commits

Every line carries its evidence ID.

## 5. Synthesis

### 5.1 Story model

Project → **Chapters** (phases, bounded by goal shifts or long gaps) → **Episodes** (one goal pursued across one or more sessions) → **Events** (evidence).

Backtracks use a fixed taxonomy, so the story and the coach report count them the same way:

| Type | Meaning |
| --- | --- |
| Reverted | Built, then removed or rolled back |
| Re-planned | Approach changed after a failure or a user correction |
| Abandoned | Goal dropped, or branch never merged |
| Thrashed | Repeated fix/fail loops on the same problem |
| Scope change | A new requirement redirected the work |

Each backtrack records what it moved from and to, the cause (quoted), and its cost in sessions and hours.

`story.json` contract. Stored in `references/story-schema.md` and validated by `check_evidence.py`:

```
origin       {problem_statement, intent, constraints[], success_criteria[], initial_plan, evidence[]}
intent_drift {original, delivered, shifts[{when, what, why, evidence[]}]}
chapters[]   {title, span, goal, summary, episodes[]}
episodes[]   {id, title, sessions[], commits[], outcome: shipped|partial|abandoned|reverted, evidence[]}
pivots[]     {when, type, from, to, why, cost, evidence[]}
shipped[]    {what, commits[], evidence[]}
open_threads[], stats{sessions, active_days, commits, agents, subagents, compactions, ...}
```

### 5.2 Subagents

| Agent | Model | Tools | Job |
| --- | --- | --- | --- |
| `session-digester` | sonnet (haiku allowed for short sessions) | Read, Write | One digest → one session card: goal, outcome, decisions, backtracks, notable prompts, with evidence IDs. Runs in parallel batches. |
| `story-editor` | inherit | Read, Write, Bash | Cards + signals + git → `story.json`; then runs `check_evidence.py` and fixes until it passes. |
| `practice-coach` | inherit | Read, Write, Bash | Signals + sampled human prompts + rubric → `coach.json`, including prompt rewrites; checks evidence the same way. |

The subagents have no network or edit-in-repo tools. Transcript content (which may include fetched web pages) is treated as data, never as instructions.

### 5.3 Cost estimate

A first full run on the largest project (126 sessions, about 10k tokens per digest) is roughly 1.3M input tokens on the map step. Later runs only process new sessions. `--since` and `--sessions` limit the scope.

## 6. Coaching rubric (`dev-coach`)

Each dimension is scored 1–4 with anchors defined in `references/rubric.md`. Every score cites at least two prompts or events. Sources:

- Anthropic's Claude Code best-practices docs
- general agentic-engineering practice
- **the user's own CLAUDE.md rules**, if present (e.g. "Think before coding", "Goal-driven execution"). The coach checks whether the user's sessions actually followed the rules they wrote down.

| # | Dimension | Good looks like |
| --- | --- | --- |
| 1 | Problem framing | States the goal, why, constraints, and success criteria up front |
| 2 | Planning and decomposition | Plans or specs before building; phases big work; revises the plan when it learns something |
| 3 | Context engineering | Keeps CLAUDE.md current; points at files and examples; one task per context; uses `/clear` |
| 4 | Verification discipline | Asks for tests or verification; TDD where it fits; runs the app |
| 5 | Steering quality | Interrupts early; corrections are specific, not "still broken"; avoids re-prompt loops |
| 6 | Session and scope hygiene | Right-sized sessions; few forced compactions; no goal-hopping |
| 7 | Version control and review | Frequent commits, branches and PRs, code and security review |
| 8 | Delegation and tooling | Uses subagents, skills, parallelism, and fitting model or effort |
| — | Safety flags (not scored) | Permission bypass, secrets in prompts, destructive commands |

The report contains:

- the scorecard, with the trend against earlier runs (stored in `reports/`)
- the 2 best prompts and why they worked
- 3 real prompts rewritten into better ones
- the top 3 habits to try next
- a pointer to `/insights` for usage-wide patterns

## 7. Outputs

- **`chronicle.html`.** A single self-contained file with inline CSS and JS and no CDN, so it can be emailed or attached.
  - A horizontal timeline with lanes for Intent & plans, Build, Backtracks, and Shipped.
  - Episode cards, and pivot markers with the reason.
  - An "Intent → Delivered" panel showing drift.
  - Click any card to see its quoted evidence.
  - A **Present** mode: one chapter per frame, navigated with the arrow keys, for walking leadership through it.
  - Light and dark themes.
- **`brief.md`.** A one-page leadership summary: problem, approach, what shipped, key pivots and lessons, and stats. Raw prompts are paraphrased by default; `--quotes` includes them. It can be handed to `doc-template-skills`' `deck-builder` for an on-brand deck.
- **`audit.md` and `audit.csv`.** Deterministic, no model needed. One row per session: time, agent, branch, intent (first prompt), files, commits, tests, interrupts, denials, compactions, subagents, permission mode, backtrack flags, evidence link.
- **`coach.html`.** The rubric report from §6.

## 8. Plugin layout

The layout follows `docs/plugin-layout.md`. Scripts use PEP 723 inline dependencies and target the stdlib only, run with `uv run`.

```
plugins/agent-chronicle/
├── plugin.json  .claude-plugin/  .codex-plugin/  .cursor-plugin/     # four manifests, same name/version/description
├── skills/
│   ├── chronicle/                     # story, brief, audit. Triggers: "how was this built", "story/history of
│   │   ├── SKILL.md                   #   this project", "audit the agent sessions", "present this to leadership"
│   │   ├── references/  story-schema.md  backtrack-taxonomy.md  audiences.md
│   │   ├── templates/chronicle.html
│   │   └── scripts/
│   │       ├── _common.py             # paths, AGENT_CHRONICLE_HOME, redaction (secret patterns)
│   │       ├── doctor.py              # agentsview present/synced? cleanupPeriodDays? git? prints fixes
│   │       ├── source_agentsview.py   # sync + JSON export → normalized events (the only agentsview-coupled file)
│   │       ├── resolve_project.py
│   │       ├── extract.py             # timeline, signals, digests
│   │       ├── git_link.py
│   │       ├── audit.py
│   │       ├── check_evidence.py
│   │       └── render.py              # chronicle.html, brief.md, coach.html
│   └── dev-coach/
│       ├── SKILL.md                   # Triggers: "how can I prompt better", "review my agent workflow", "coach me"
│       └── references/rubric.md
├── agents/  session-digester.md  story-editor.md  practice-coach.md
├── com.github.copilot/agents/*.agent.md
├── hooks/hooks.json                   # Claude + Codex: SessionEnd → agentsview sync (no-op, exit 0 if absent)
├── README.md  CHANGELOG.md  LICENSE
```

Client support:

| Client | Support |
| --- | --- |
| Claude Code | Full |
| Codex | Skills + hooks; no bundled subagents, so the skill runs the map and reduce steps inline |
| Copilot | Skills + `.agent.md` agents |
| Cursor | Skills + agents; hook only if Cursor's format supports SessionEnd, checked in Phase 4 |

## 9. Privacy and trust

- Everything runs locally. The only data that leaves the machine is digest text going to the model the user is already running.
- Redaction runs in `extract.py` before digests are written: API keys, tokens, `.env` values, private keys, and connection strings. The same pass runs again on every rendered output.
- Leadership outputs paraphrase prompts by default and never include tool output.
- The audit ledger records the permission mode and safety flags, but no secret values.

## 10. Delivery phases

Each phase has a verify step. Phases 1 and 2 are the minimum useful product.

| Phase | Build | Verify |
| --- | --- | --- |
| **0. Spike** (do first) | Install agentsview and sync. Check that its JSON export has: human vs meta prompts, tool inputs with file paths, subagent links, compaction boundaries and summaries, plan content, quality counters, the exact sync command for the hook. Choose golden projects: `rooted-skills` (126 sessions), `ai-security-framework-viz` (86), and one Codex-heavy project. | A field-coverage table. **Go/no-go on agentsview as the index.** If a field is missing, write a native Claude Code + Codex adapter behind `source_*.py` only for that gap. |
| **1. Extract + audit** | `doctor`, `resolve_project`, `source_agentsview`, `extract`, `git_link`, `audit`. No model involved. | Unit tests on synthetic fixture exports and a fixture git repo. On `rooted-skills`, every session appears once, worktrees are merged, and 20 commit links are spot-checked by hand. |
| **2. Chronicle** | Digests, `session-digester`, `story-editor`, `check_evidence`, `render` (HTML + brief), card cache. | `check_evidence` passes 100%. You read the `rooted-skills` chronicle and confirm the origin, chapters, and pivots match your memory. A re-run after one new session only digests that session. |
| **3. Coach** | `rubric.md`, `practice-coach`, `coach.html`, trend history. | Run on 2 projects. Every score cites evidence. You judge whether the 3 suggested habits are useful and not generic. |
| **4. Package** | Four manifests, Copilot agents, hooks, README, marketplace regen, CI e2e from fixtures (no agentsview or model in CI; `story.json` fixture → render). | `scripts/build_marketplaces.py --check`, `claude plugin validate .`, local install in Claude Code and Codex, CI green. |
| 5. Later (optional) | Deck handoff to `pptx-brand`; a portfolio view across projects ("what I built this quarter"); trend charts. | Separate plan. |

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| agentsview CLI or schema changes (v0.x, frequent releases) | Use its JSON CLI or API, never its internal SQLite tables. Isolate it to `source_agentsview.py` and pin a minimum version in `doctor.py`. |
| Plausible but wrong narrative | The evidence gate; deterministic facts (dates, commits, counts) are never model-written; you review the golden projects in Phase 2. |
| History already lost | `doctor.py` flags short retention. For lost transcripts, `history.jsonl` and `sessions-index.json` still give prompts and titles, so the chronicle can mark those spans as "prompts only". |
| Cost on large projects | Cache, incremental runs, `--since`, and a cheaper model for the map step. |
| Generic coaching | Require quoted evidence and concrete rewrites, and score against the user's own CLAUDE.md rules. |

## 12. Open decisions

1. **Index:** agentsview as a required dependency (recommended: 60+ formats, archive, and quality counters for free), or our own Claude Code + Codex parsers (self-contained, but we own the format drift)? The Phase 0 spike settles this with data.
2. **Name:** `agent-chronicle` (alternatives: `build-story`, `session-storyboard`).
3. **Primary presentation format:** a self-contained HTML storyboard plus `brief.md` (recommended), with a deck via `pptx-brand` later. Or is a deck needed in v1?
4. **Report location:** outside the repo by default (recommended), or `docs/chronicle/` inside it?
