"""Token-budgeted session digests (map-step input) and the prompts file (coach input).

A digest keeps the human prompts in full, plans and compaction summaries, edits, tests,
failures, git operations, subagent launches, and commits; routine reads and commands are
collapsed to one line per run. Every line carries the evidence id the model must cite.
"""

import hashlib
import shutil
from datetime import datetime

from _common import clip, clip_middle, parse_ts

BUDGET_CHARS = 48_000          # ~12k tokens per digest file
HEADER_END = "\n---\n\n"
PROMPTS_BUDGET_CHARS = 120_000  # ~30k tokens for prompts.md


def hhmm(ts):
    return parse_ts(ts).strftime("%H:%M")


def rel(path, roots):
    for r in sorted(map(str, roots), key=len, reverse=True):
        if path.startswith(r.rstrip("/") + "/"):
            return path[len(r.rstrip("/")) + 1:]
    return path


def session_lines(events, commits, roots):
    """Yield (text, is_boundary) lines for one session, collapsing routine tool runs."""
    out, run = [], []

    def flush():
        if not run:
            return
        first = run[0]
        names = []
        for e in run:
            label = rel(e.get("target") or e.get("text") or e["tool"], roots)
            if label not in names:
                names.append(label)
        shown = ", ".join(clip(n, 60) for n in names[:4]) + (f" (+{len(names) - 4} more)" if len(names) > 4 else "")
        out.append((f"[{first['id']}] {hhmm(first['ts'])} agent ran {len(run)} routine tool call(s): {shown}", False))
        run.clear()

    # The agent's last message before the human speaks again summarizes the turn: keep it long.
    turn_end, last = set(), None
    for i, e in enumerate(events):
        if e["kind"] == "assistant_text":
            last = i
        elif e["kind"] in ("user_prompt", "interrupt", "slash_command") and last is not None:
            turn_end.add(last)
            last = None
    if last is not None:
        turn_end.add(last)
    for i in turn_end:
        events[i] = {**events[i], "turn_end": True}

    stream = sorted(events + [{"kind": "commit_line", **c} for c in commits], key=lambda e: e["ts"])
    for e in stream:
        k = e["kind"]
        routine = (k == "tool" and e["status"] == "ok") or (
            k == "command" and e["status"] == "ok" and not e.get("git") and not e.get("destructive"))
        if routine:
            run.append(e)
            continue
        t = hhmm(e["ts"])
        if k == "assistant_text":
            if e.get("turn_end"):
                out.append((f"[{e['id']}] {t} AGENT (end of turn): {clip(e['text'], 1500)}", False))
            else:
                out.append((f"[{e['id']}] {t} AGENT: {clip(e['text'], 200)}", False))
            continue
        flush()
        if k == "commit_line":
            out.append((f"[c:{e['sha7']}] {t} COMMIT {e['subject']} ({len(e['files'])} files, "
                        f"+{e['insertions']}/-{e['deletions']})", False))
        elif k == "user_prompt":
            out.append((f"[{e['id']}] {t} USER: {clip_middle(e['text'], 4000)}", False))
        elif k == "command":
            label = "GIT" if e.get("git") else "COMMAND"
            if e.get("destructive"):
                label = "DESTRUCTIVE COMMAND"
            line = f"[{e['id']}] {t} {label} {clip(e['text'], 300)}"
            if e["status"] == "denied":
                line = f"[{e['id']}] {t} USER DENIED command {clip(e['text'], 200)}"
            elif e["status"] == "error":
                line += f" → FAILED: {clip(e.get('result', ''), 200)}"
            out.append((line, False))
        elif k == "interrupt":
            out.append((f"[{e['id']}] {t} USER INTERRUPTED the agent", False))
        elif k == "slash_command":
            out.append((f"[{e['id']}] {t} USER ran {clip(e['text'], 300)}", False))
        elif k == "plan":
            out.append((f"[{e['id']}] {t} PLAN PROPOSED:\n{clip(e['text'], 3000)}", False))
        elif k == "compaction":
            out.append((f"[{e['id']}] {t} CONTEXT COMPACTED. Summary of the work so far:\n{clip(e['text'], 4000)}", True))
        elif k == "edit":
            size = f" (+{e['added']}/-{e['removed']})" if e.get("added") or e.get("removed") else ""
            verb = {"add": "CREATE", "write": "WRITE", "delete": "DELETE"}.get(e.get("op"), "EDIT")
            out.append((f"[{e['id']}] {t} {verb} {rel(e['target'], roots)}{size}"
                        + (" → DENIED" if e["status"] == "denied" else ""), False))
        elif k == "test":
            verdict = "PASS" if e["status"] == "ok" else f"FAIL: {clip(e.get('result', ''), 200)}"
            out.append((f"[{e['id']}] {t} TEST {clip(e['text'], 160)} → {verdict}", False))
        elif k == "subagent":
            out.append((f"[{e['id']}] {t} SUBAGENT ({e.get('agent_type') or 'agent'}) {e['text']}", False))
        else:  # a tool call that failed or was denied
            out.append((f"[{e['id']}] {t} {e['tool']} {rel(e.get('target') or e.get('text') or '', roots)} "
                        f"→ {e['status'].upper()}", False))
    flush()
    return out


def chunk(lines, budget):
    chunks, cur, size = [], [], 0
    for text, boundary in lines:
        if cur and (size + len(text) > budget or (boundary and size > budget // 2)):
            chunks.append(cur)
            cur, size = [], 0
        cur.append(text)
        size += len(text) + 1
    if cur:
        chunks.append(cur)
    return chunks


def body_sha(text):
    """Cache key for a digest part: its event lines only. The header carries session-wide context (title,
    totals, part count) that changes as a session grows; hashing it would re-digest every earlier part."""
    return hashlib.sha256(text.split(HEADER_END, 1)[-1].encode()).hexdigest()[:16]


def header(s, sig, part, parts):
    start, end = parse_ts(s["started"]), parse_ts(s["ended"])
    span = f"{start:%Y-%m-%d %H:%M} → {end:%H:%M}" if start.date() == end.date() else f"{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M}"
    return (f"# Session {s['short']} — {s['title']}\n"
            f"agent {s['agent']} · branch {s['branch'] or '-'} · {span} UTC · {sig['human_prompts']} human prompts · "
            f"health {sig['health'] or '-'} · compactions {sig['compactions']} · subagent sessions {s['children']}\n"
            f"part {part}/{parts}. Evidence ids are in [brackets]; cite them exactly." + HEADER_END)


def write_digests(wd, manifest, events_by_session, roots, sig):
    """Write digests/<session>.<part>.md for every session with human input or edits. Returns their index."""
    ddir = wd / "digests"
    shutil.rmtree(ddir, ignore_errors=True)
    ddir.mkdir(parents=True)
    commits_by_session = {}
    for c in manifest["commits"]:
        if c["session"]:
            commits_by_session.setdefault(c["session"], []).append(c)
    index = []
    for s in manifest["sessions"]:
        evs = events_by_session[s["short"]]
        if not sig["sessions"][s["short"]]["agent_steps"]:
            continue  # nothing the agent did was recorded; the audit still lists it
        parts = chunk(session_lines(evs, commits_by_session.get(s["short"], []), roots), BUDGET_CHARS)
        for i, lines in enumerate(parts, 1):
            name = f"{s['short']}.{i}"
            text = header(s, sig["sessions"][s["short"]], i, len(parts)) + "\n".join(lines) + "\n"
            (ddir / f"{name}.md").write_text(text)
            index.append({"name": name, "session": s["short"], "part": i, "parts": len(parts),
                          "sha": body_sha(text), "tokens": len(text) // 4})
    return index


def write_prompts(wd, manifest, events_by_session, sig):
    """prompts.md: every human prompt, chronologically, with each session's signal line."""
    automated = [s for s in manifest["sessions"] if sig["sessions"][s["short"]]["automated"]]

    def render(cap):
        blocks = []
        for s in manifest["sessions"]:
            if sig["sessions"][s["short"]]["automated"]:
                continue
            prompts = [e for e in events_by_session[s["short"]] if e["kind"] in ("user_prompt", "interrupt", "slash_command")]
            if not prompts:
                continue
            r = sig["sessions"][s["short"]]
            blocks.append(
                f"## {s['started'][:10]} · {s['short']} · {s['title']}\n"
                f"{s['agent']} · {r['human_prompts']} prompts · plan before code: {r['plan_before_code']} · "
                f"tests {r['tests_run']} run / {r['tests_failed']} failed · interrupts {r['interrupts']} · "
                f"corrections {r['corrections']} · compactions {r['compactions']} · commits {r['commits_linked']} · "
                f"health {r['health'] or '-'}\n")
            for i, e in enumerate(prompts):
                if e["kind"] == "interrupt":
                    blocks.append(f"[{e['id']}] (user interrupted the agent)")
                elif e["kind"] == "slash_command":
                    blocks.append(f"[{e['id']}] (slash command) {clip(e['text'], 200)}")
                else:
                    blocks.append(f"[{e['id']}] {clip_middle(e['text'], 3000 if i == 0 else cap)}")
            blocks.append("")
        if automated:
            first = next(e for e in events_by_session[automated[0]["short"]] if e["kind"] == "user_prompt")
            blocks.append(f"## Automated sessions ({len(automated)})\n"
                          "Opened by a hook or tool with the same templated prompt, not typed by the developer:\n"
                          f"> {clip(' '.join(first['text'].split()), 200)}\n")
            blocks += [f"- {s['started'][:10]} · {s['short']} · {s['title']}" for s in automated]
        return "\n".join(blocks)

    for cap in (1500, 600, 250, 120):
        body = render(cap)
        if len(body) <= PROMPTS_BUDGET_CHARS:
            break
    note = "" if len(body) <= PROMPTS_BUDGET_CHARS else "\n(Truncated: the project has more prompt text than the budget.)\n"
    title = (f"# Human prompts — {manifest['project']['name']}\n"
             f"Generated {datetime.now():%Y-%m-%d}. First prompt of each session is kept longer; others are clipped.\n\n")
    (wd / "prompts.md").write_text(title + body[:PROMPTS_BUDGET_CHARS] + note)
