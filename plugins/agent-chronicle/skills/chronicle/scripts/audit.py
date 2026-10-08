#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic audit ledger: one row per session, plus commits no captured session explains.

    uv run scripts/audit.py [--project PATH] [--out DIR]

Writes audit.md and audit.csv to <project>/.agent-chronicle/. Needs extract.py first. No model is involved.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import clip, load_work, read_ndjson, read_json, report_dir  # noqa: E402

COLUMNS = ["date", "session", "agent", "title", "branch", "duration_min", "human_prompts", "intent",
           "files_edited", "commits", "tests_run", "tests_failed", "interrupts", "corrections", "denials",
           "compactions", "subagents", "health", "flags", "link"]


def flags(r):
    out = [] if r["agent_steps"] else ["no agent activity recorded"]
    if r["automated"]:
        out.append("automated (templated prompt)")
    if r["rollbacks"]:
        out.append(f"rollback x{r['rollbacks']}")
    if r["churn_files"]:
        out.append("churn: " + ", ".join(Path(f).name for f in r["churn_files"][:2]))
    if r["destructive_commands"]:
        out.append(f"destructive cmd x{r['destructive_commands']}")
    if r["secret_leaks"]:
        out.append(f"secret leak x{r['secret_leaks']}")
    if r["tests_failed"] and not r["commits_linked"]:
        out.append("ended without commit after failing tests")
    return "; ".join(out)


def rows(manifest, sig, events):
    first_prompt = {}
    for e in events:
        if e["kind"] == "user_prompt" and e["session"] not in first_prompt:
            first_prompt[e["session"]] = e["text"]
    for s in manifest["sessions"]:
        r = sig["sessions"][s["short"]]
        yield {
            "date": s["started"][:16].replace("T", " "),
            "session": s["short"],
            "agent": s["agent"],
            "title": s["title"],
            "branch": s["branch"],
            "duration_min": r["duration_min"],
            "human_prompts": r["human_prompts"],
            "intent": " ".join(clip(first_prompt.get(s["short"], ""), 240).split()),
            "files_edited": r["files_edited"],
            "commits": " ".join(s["commits"]),
            "tests_run": r["tests_run"],
            "tests_failed": r["tests_failed"],
            "interrupts": r["interrupts"],
            "corrections": r["corrections"],
            "denials": r["denials"],
            "compactions": r["compactions"],
            "subagents": r["subagents"],
            "health": r["health"] or "",
            "flags": flags(r),
            "link": s.get("web_url") or "",
        }


def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".")
    ap.add_argument("--out", help="artifact dir (default <project>/.agent-chronicle)")
    args = ap.parse_args()
    root, wd, manifest = load_work(args.project)
    sig = read_json(wd / "signals.json")
    events = read_ndjson(wd / "timeline.ndjson")
    table = list(rows(manifest, sig, events))
    out = report_dir(args.project, args.out)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "audit.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(table)

    p = sig["project"]
    lines = [
        f"# Agent session audit — {manifest['project']['name']}",
        "",
        f"`{manifest['project']['root']}` · generated {manifest['generated_at'][:16].replace('T', ' ')} UTC from agentsview + git",
        "",
        f"- **Span:** {p['first']} → {p['last']} · {p['active_days']} active days",
        f"- **Sessions:** {p['sessions']} ({', '.join(f'{a} {n}' for a, n in p['agents'].items())}), "
        f"plus {p['subagent_sessions']} subagent sessions folded into their parents",
        f"- **Human prompts:** {p['human_prompts']} · interrupts {p['interrupts']} · tool denials {p['denials']} · "
        f"compactions {p['compactions']}",
        f"- **Commits:** {p['commits']} · {p['commits_linked']} linked to a session · {p['reverts']} reverts · "
        f"{p['unmerged_commits']} not on {manifest['project']['default_branch'] or 'the default branch'}",
        f"- **Safety:** {p['destructive_commands']} destructive commands · {p['secret_leaks']} secret leaks flagged by agentsview",
    ]
    if p["pre_history_commits"]:
        lines.append(f"- **Gap:** {p['pre_history_commits']} commits from {p['pre_history_first']} predate the first "
                     "captured session (transcripts deleted before agentsview indexed them, or work done without an agent)")
    lines += ["", "## Sessions", "",
              "| Date (UTC) | Session | Agent | Title | Prompts | Files | Commits | Tests run/failed | "
              "Interrupts / corrections / denials | Compactions | Health | Flags |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        session = f"[{r['session']}]({r['link']})" if r["link"] else r["session"]
        lines.append("| " + " | ".join(md_cell(v) for v in (
            r["date"], session, r["agent"], clip(r["title"], 60), r["human_prompts"], r["files_edited"],
            len(r["commits"].split()), f"{r['tests_run']}/{r['tests_failed']}",
            f"{r['interrupts']} / {r['corrections']} / {r['denials']}", r["compactions"], r["health"], r["flags"],
        )) + " |")

    lines += ["", "## Session detail", ""]
    commits = {c["sha7"]: c for c in manifest["commits"]}
    for r in table:
        lines += [f"### {r['date']} · {r['session']} · {r['title']}", "",
                  f"{r['agent']} · branch `{r['branch'] or '-'}` · {r['duration_min']} min · "
                  f"{r['subagents']} subagent launches · health {r['health'] or '-'}", ""]
        if r["intent"]:
            lines += [f"> {r['intent']}", ""]
        for sha in r["commits"].split():
            c = commits[sha]
            lines.append(f"- `{sha}` {md_cell(c['subject'])} (+{c['insertions']}/-{c['deletions']})")
        if r["flags"]:
            lines.append(f"- Flags: {r['flags']}")
        lines.append("")

    orphans = [c for c in manifest["commits"] if not c["session"] and not c["merge"]]
    if orphans:
        lines += ["## Commits with no linked session", "",
                  "Made by hand, by an agent whose transcript was not captured, or outside the linking window.", ""]
        lines += [f"- {c['ts'][:10]} `{c['sha7']}` {md_cell(c['subject'])} — {c['author']}" for c in orphans]
        lines.append("")

    (out / "audit.md").write_text("\n".join(lines))
    print(f"wrote {out / 'audit.md'}\nwrote {out / 'audit.csv'}  ({len(table)} sessions)")


if __name__ == "__main__":
    main()
