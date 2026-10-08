#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Pull one project's agent sessions from agentsview, join them with git, and write the work dir.

    uv run scripts/extract.py [--project PATH] [--since YYYY-MM-DD] [--no-sync]
    uv run scripts/extract.py --list            # projects found across all sessions

Writes $AGENT_CHRONICLE_HOME/work/<project>/:
    manifest.json     project, sessions, commits (with session links), context files
    timeline.ndjson   normalized, redacted events; ids are evidence ids (<session8>:<ordinal>)
    signals.json      deterministic per-session and project signals
    digests/*.md      token-budgeted inputs for the session-digester map step
    prompts.md        the human prompts, for the coach
    pending.json      digests that have no up-to-date card yet
No model is involved.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import archive  # noqa: E402
import digest  # noqa: E402
import gitlog  # noqa: E402
import signals  # noqa: E402
import source_agentsview as av  # noqa: E402
from _common import (classify_user, clip, fail, now_iso, parse_ts, project_slug,  # noqa: E402
                     read_json, redact, repo_root, short_id, work_dir, write_json)

TOOL_LINE = re.compile(r"^\[[A-Za-z_][\w\-.:]*(?::[^\]]*)?\]$")
TEST_RE = re.compile(r"(?:^|[;&|(]\s*|\buv run\s+(?:--\S+\s+)*|\bpython3? -m\s+|\bnpx\s+|\bpoetry run\s+)"
                     r"(pytest|vitest|jest|mocha|playwright test|go test|cargo test|(?:npm|pnpm|yarn|bun)(?: run)? test|"
                     r"make (?:test|check)|tox|nox|rspec|phpunit|dotnet test|mvn test|gradle test|\S*run_e2e\S*)\b")
FAIL_RE = re.compile(r"\b(\d+ (?:failed|errors?)|FAILED|FAIL\b|Traceback|AssertionError|failures?: *[1-9])")
GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
GIT_ROLLBACK = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(revert|reset\s+--hard|checkout\s+--\s|restore\b|stash\s+drop|clean\s+-[a-z]*f)")
GH_PR = re.compile(r"\bgh\s+pr\s+(create|merge)\b")
DESTRUCTIVE = re.compile(r"\bgit\s+push\b[^\n]*(--force|\s-f\b)|reset\s+--hard|\bDROP\s+(TABLE|DATABASE)\b", re.I)
RM_RF = re.compile(r"(?:^|[;&|\n(]\s*)(?:sudo\s+)?rm\s+-[a-z]*(?:rf|fr)[a-z]*\s+([^;&|\n]+)")  # command position only
SCRATCH = re.compile(r"tmp|temp|scratch|cache|node_modules|\.venv|venv|dist\b|build\b|__pycache__|\.pytest|coverage", re.I)
PATCH_FILE = re.compile(r"\*\*\* (Add|Update|Delete) File: ([^\s\\\"]+)")
CODEX_CMD = re.compile(r"cmd\s*:\s*\"((?:[^\"\\]|\\.)*)\"")


# ---------------------------------------------------------------- normalization

def assistant_prose(content):
    """Assistant text before its first tool marker (agentsview appends tool calls as `[Tool: ...]` lines)."""
    lines = []
    for line in (content or "").splitlines():
        if TOOL_LINE.match(line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def unescape_js(s):
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def tool_status(result):
    head = (result or "")[:400]
    low = head.lower()
    if "doesn't want to proceed" in low or "user rejected" in low or "permission denied by user" in low:
        return "denied"
    if re.match(r"exit code [1-9]", low) or "<tool_use_error>" in low or low.startswith("error"):
        return "error"
    return "ok"


def tool_events(t):
    """One agentsview tool call -> zero or more normalized events (a Codex exec can hold many)."""
    name, cat = t.get("tool_name") or "", t.get("category") or ""
    raw = t.get("input_json") or ""
    try:
        inp = json.loads(raw) if raw else {}
    except ValueError:
        inp = {}
    if not isinstance(inp, dict):
        inp = {}
    result = t.get("result_content") or ""
    status = tool_status(result)
    base = {"tool": name, "status": status}

    if name == "ExitPlanMode":
        return [{**base, "kind": "plan", "text": redact(clip(inp.get("plan", ""), 8000))}]
    if cat == "Task":
        if name in ("send_message", "followup_task"):
            return []
        desc = inp.get("description") or inp.get("task_name") or ""
        return [{**base, "kind": "subagent", "text": clip(desc, 200),
                 "agent_type": inp.get("subagent_type", ""), "child": t.get("subagent_session_id")}]

    patch = inp.get("input") if isinstance(inp.get("input"), str) else raw
    files = PATCH_FILE.findall(patch or "")
    if files:  # apply_patch, including inside a Codex exec script
        out = []
        for op, path in files:
            out.append({**base, "kind": "edit", "target": path, "op": op.lower(), "added": 0, "removed": 0})
        return out

    target = inp.get("file_path") or inp.get("notebook_path") or ""
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit") or (cat in ("Edit", "Write") and target):
        if name == "Write":
            added, removed = (inp.get("content") or "").count("\n") + 1, 0
        elif name == "MultiEdit":
            edits = inp.get("edits") or []
            added = sum((e.get("new_string") or "").count("\n") + 1 for e in edits)
            removed = sum((e.get("old_string") or "").count("\n") + 1 for e in edits)
        else:
            added = (inp.get("new_string") or "").count("\n") + 1
            removed = (inp.get("old_string") or "").count("\n") + 1
        return [{**base, "kind": "edit", "target": target, "op": "write" if name == "Write" else "update",
                 "added": added, "removed": removed}]

    cmd = inp.get("command") or inp.get("cmd") or ""
    if isinstance(cmd, list):
        cmd = " ".join(map(str, cmd))
    if not cmd and cat == "Bash" and raw:
        found = CODEX_CMD.findall(raw)
        cmd = " ; ".join(unescape_js(c) for c in found) if found else raw
    if cmd:
        ev = {**base, "kind": "command", "text": redact(clip(cmd, 600))}
        if TEST_RE.search(cmd):
            failed = status == "error" or bool(FAIL_RE.search(result[-3000:]))
            ev |= {"kind": "test", "status": "error" if failed else "ok"}
        if GIT_COMMIT.search(cmd):
            ev["git"] = "commit"
        elif GIT_ROLLBACK.search(cmd):
            ev["git"] = "rollback"
        elif GH_PR.search(cmd):
            ev["git"] = "pr"
        if DESTRUCTIVE.search(cmd) or (RM_RF.search(cmd) and not SCRATCH.search(cmd)):
            ev["destructive"] = True
        if status != "ok" or ev["kind"] == "test":
            ev["result"] = redact(clip(result.strip(), 300))
        return [ev]

    target = target or inp.get("path") or inp.get("pattern") or inp.get("url") or inp.get("query") or ""
    return [{**base, "kind": "tool", "category": cat, "target": clip(str(target), 200)}]


def normalize(msgs, short):
    events = []
    for m in msgs:
        base = {"id": f"{short}:{m['ordinal']}", "ts": parse_ts(m["timestamp"]).isoformat(), "session": short}
        if m.get("is_compact_boundary") or m.get("source_subtype") == "compact_boundary":
            events.append({**base, "kind": "compaction", "text": redact(clip(m.get("content", ""), 6000))})
            continue
        if m["role"] == "user":
            if m.get("source_subtype") == "interrupted":
                events.append({**base, "kind": "interrupt", "text": ""})
                continue
            if m.get("is_system"):
                continue
            kind, text = classify_user(m.get("content", ""))
            if kind != "meta":
                events.append({**base, "kind": kind, "text": redact(clip(text, 20000))})
            continue
        prose = assistant_prose(m.get("content", ""))
        if prose:
            events.append({**base, "kind": "assistant_text", "text": redact(clip(prose, 2000)),
                           "model": m.get("model") or ""})
        for t in m.get("tool_calls") or []:
            events += [{**base, **e} for e in tool_events(t)]
    # Compaction re-writes the preserved recent messages after the boundary with their original timestamps,
    # and agentsview stores both copies. Keep the first.
    seen, unique = set(), []
    for e in events:
        key = (e["ts"], e["kind"], e.get("tool"), e.get("text") or e.get("target"), e.get("added"), e.get("removed"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


# ---------------------------------------------------------------- project + linking

def assign_shorts(sessions):
    """8-char session ids, unique within the project. Time-ordered ids (Codex uses UUIDv7) share a prefix
    when sessions start close together, so a collision falls back to the id's random tail."""
    shorts, taken = {}, set()
    for s in sessions:
        short = short_id(s["id"])
        if short in taken:
            short = s["id"].replace("-", "")[-8:]
        if short in taken:
            fail(f"cannot give session {s['id']} a unique short id")
        taken.add(short)
        shorts[s["id"]] = short
    return shorts


def under(path, roots):
    p = str(path or "")
    return any(p == str(r) or p.startswith(str(r).rstrip("/") + "/") for r in roots)


def rel_to(path, roots):
    for r in sorted(roots, key=lambda r: -len(str(r))):
        if under(path, [r]):
            return str(path)[len(str(r)):].lstrip("/")
    return str(path)


def link_commits(commits, sessions, events_by_session, roots):
    """Attach each commit to the session that most plausibly produced it."""
    windows = []
    for s in sessions:
        evs = events_by_session[s["short"]]
        windows.append((
            parse_ts(s["started"]) - timedelta(minutes=10),
            parse_ts(s["ended"]) + timedelta(minutes=30),
            s,
            [parse_ts(e["ts"]) for e in evs if e.get("git") == "commit"],
            {rel_to(e["target"], roots) for e in evs if e["kind"] == "edit"},
        ))
    for c in commits:
        if c["merge"]:
            continue
        ts, best = parse_ts(c["ts"]), None
        for start, end, s, commit_times, edited in windows:
            if not start <= ts <= end:
                continue
            score = 3 if any(abs((ts - t).total_seconds()) <= 300 for t in commit_times) else 0
            score += 2 if edited & set(c["files"]) else 0
            score += 1 if c["agent_trailer"] else 0
            if score >= 2 and (best is None or score > best[0]):
                best = (score, s)
        if best:
            c["session"] = best[1]["short"]
            best[1]["commits"].append(c["sha7"])


def context_files(root):
    names = ["CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md", ".cursorrules"]
    found = [str(root / n) for n in names if (root / n).exists()]
    global_md = Path("~/.claude/CLAUDE.md").expanduser()
    codex_md = Path("~/.codex/AGENTS.md").expanduser()
    return {
        "repo": found,
        "user": [str(p) for p in (global_md, codex_md) if p.exists()],
        "first_added": gitlog.first_added(root, ["CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md"]) if gitlog.is_repo(root) else None,
    }


def list_projects():
    groups = defaultdict(list)
    roots_cache = {}
    for s in av.list_sessions():
        if s.get("parent_session_id"):
            continue
        cwd = s.get("cwd") or ""
        if cwd not in roots_cache:
            roots_cache[cwd] = str(repo_root(cwd)) if cwd and Path(cwd).exists() else cwd or "(unknown)"
        groups[roots_cache[cwd]].append(s)
    rows = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    print(f"{'sessions':>8}  {'first':10}  {'last':10}  agents            project")
    for root, ss in rows:
        agents = ",".join(f"{a}:{n}" for a, n in Counter(s["agent"] for s in ss).most_common())
        print(f"{len(ss):>8}  {ss[0]['started_at'][:10]}  {max(s['started_at'] for s in ss)[:10]}  {agents:16}  {root}")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="any path inside the project (default: cwd)")
    ap.add_argument("--since", help="only sessions and commits on or after YYYY-MM-DD")
    ap.add_argument("--no-sync", action="store_true", help="skip `agentsview sync` and the raw-source archive")
    ap.add_argument("--list", action="store_true", help="list projects found across all sessions and exit")
    args = ap.parse_args()

    if not args.no_sync:
        av.sync()
        archive.run()
    if args.list:
        return list_projects()

    root = repo_root(args.project)
    is_git = gitlog.is_repo(root)
    roots = [root] + [w for w in (gitlog.worktrees(root) if is_git else []) if w != root]
    wd = work_dir(root)
    slug = project_slug(root)

    raw_sessions = [s for s in av.list_sessions() if under(s.get("cwd"), roots)]
    if args.since:
        raw_sessions = [s for s in raw_sessions if (s.get("ended_at") or s["started_at"])[:10] >= args.since]
    if not raw_sessions:
        fail(f"agentsview has no sessions under {root}. Check `agentsview session list --json` or run with --list.")

    children = Counter(s["parent_session_id"] for s in raw_sessions if s.get("parent_session_id"))
    top = [s for s in raw_sessions if not s.get("parent_session_id")]
    sessions, events_by_session, all_events = [], {}, []
    shorts = assign_shorts(top)
    for s in top:
        short = shorts[s["id"]]
        evs = normalize(av.messages(s["id"]), short)
        events_by_session[short] = evs
        all_events += evs
        sessions.append({
            "short": short,
            "id": s["id"],
            "agent": s.get("agent"),
            "title": s.get("display_name") or clip(classify_user(s.get("first_message", ""))[1], 80) or short,
            "started": parse_ts(s["started_at"]).isoformat(),
            "ended": parse_ts(s.get("ended_at") or s["started_at"]).isoformat(),
            "branch": s.get("git_branch") or "",
            "cwd": s.get("cwd") or "",
            "web_url": s.get("web_url"),
            "children": children.get(s["id"], 0),
            "commits": [],
            "agentsview": {k: s.get(k) for k in (
                "health_grade", "health_score", "outcome", "compaction_count", "mid_task_compaction_count",
                "peak_context_tokens", "total_output_tokens", "edit_churn_count", "tool_retry_count",
                "tool_failure_signal_count", "secret_leak_count", "quality_signals")},
        })

    commits = gitlog.commits(root) if is_git else []
    if args.since:
        commits = [c for c in commits if c["ts"][:10] >= args.since]
    link_commits(commits, sessions, events_by_session, roots)

    for c in commits:
        all_events.append({"id": f"c:{c['sha7']}", "ts": c["ts"], "session": c["session"], "kind": "commit",
                           "text": c["subject"], "files": len(c["files"]),
                           "insertions": c["insertions"], "deletions": c["deletions"]})
    all_events.sort(key=lambda e: e["ts"])

    wd.mkdir(parents=True, exist_ok=True)
    with open(wd / "timeline.ndjson", "w") as f:
        for e in all_events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    ctx = context_files(root)
    manifest = {
        "project": {"slug": slug, "name": root.name, "root": str(root), "worktrees": [str(w) for w in roots[1:]],
                    "remote": gitlog.remote(root) if is_git else None,
                    "default_branch": gitlog.default_branch(root) if is_git else None},
        "generated_at": now_iso(),
        "since": args.since,
        "sessions": sessions,
        "commits": commits,
        "context_files": ctx,
    }
    sig = signals.compute(manifest, events_by_session)
    write_json(wd / "signals.json", sig)

    cards_dir = wd / "cards"
    digests = digest.write_digests(wd, manifest, events_by_session, roots, sig)
    digest.write_prompts(wd, manifest, events_by_session, sig)
    pending = []
    for d in digests:
        card = read_json(cards_dir / f"{d['name']}.json")
        if not card or card.get("digest_sha") != d["sha"]:
            pending.append(d)
    for d in digests:
        session = next(s for s in sessions if s["short"] == d["session"])
        session.setdefault("digests", []).append(d["name"])
    write_json(wd / "manifest.json", manifest)
    write_json(wd / "pending.json", {"generated_at": manifest["generated_at"], "digests": pending})

    agents = Counter(s["agent"] for s in sessions)
    linked = sum(1 for c in commits if c["session"])
    print(f"project:   {root.name}  ({root})")
    if roots[1:]:
        print(f"worktrees: merged {len(roots) - 1}: " + ", ".join(Path(w).name for w in roots[1:]))
    print(f"sessions:  {len(sessions)} ({', '.join(f'{a} {n}' for a, n in agents.most_common())}); "
          f"{sum(children.values())} subagent sessions folded into their parents")
    print(f"span:      {sessions[0]['started'][:10]} → {max(s['ended'] for s in sessions)[:10]}")
    print(f"commits:   {len(commits)} ({linked} linked to a session)" if is_git else "commits:   not a git repo")
    tokens = sum(d["tokens"] for d in pending)
    print(f"digests:   {len(digests)} total, {len(pending)} pending (~{tokens:,} input tokens for the map step)")
    print(f"work dir:  {wd}")


if __name__ == "__main__":
    main()
