#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Bundle checked session cards, signals, and commits into one compact file for the story-editor.

    uv run scripts/bundle.py [--project PATH]

Writes work/<project>/bundle.md. Run after `check_evidence.py cards` passes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import clip, load_work, read_json  # noqa: E402


def ev(item):
    ids = item.get("evidence") or []
    return f" [{', '.join([ids] if isinstance(ids, str) else ids)}]" if ids else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=".")
    args = ap.parse_args()
    root, wd, manifest = load_work(args.project)
    sig = read_json(wd / "signals.json")
    p = sig["project"]

    L = [f"# Bundle — {manifest['project']['name']}", "",
         f"{p['first']} → {p['last']} · {p['sessions']} sessions · {p['active_days']} active days · "
         f"{p['human_prompts']} human prompts · {p['commits']} commits ({p['commits_linked']} linked)", ""]
    if p["pre_history_commits"]:
        L += [f"{p['pre_history_commits']} commits from {p['pre_history_first']} predate the first captured session.", ""]

    L += ["## Sessions and their cards (chronological)", ""]
    for s in manifest["sessions"]:
        r = sig["sessions"][s["short"]]
        auto = " · automated (opened by a hook or tool)" if r["automated"] else ""
        L.append(f"### {s['started'][:16].replace('T', ' ')} · session {s['short']} · {s['title']}{auto}")
        L.append(f"{s['agent']} · {r['human_prompts']} prompts · {r['duration_min']} min · edits {r['edits']} · "
                 f"tests {r['tests_run']}/{r['tests_failed']} failed · interrupts {r['interrupts']} · "
                 f"corrections {r['corrections']} · rollbacks {r['rollbacks']} · compactions {r['compactions']} · "
                 f"commits {' '.join(s['commits']) or '-'}")
        if not s.get("digests"):
            L += ["(no agent activity recorded; no card)", ""]
            continue
        for name in s["digests"]:
            c = read_json(wd / "cards" / f"{name}.json") or {}
            if len(s["digests"]) > 1:
                L.append(f"part {name}:")
            goal = c.get("goal") or {}
            L.append(f"- goal: {goal.get('text', '')}{ev(goal)}")
            L.append(f"- outcome: {c.get('outcome', 'unknown')} — {c.get('summary', '')}")
            for key in ("built", "decisions", "backtracks", "open_threads"):
                for item in c.get(key) or []:
                    text = item.get("text") or f"{item.get('from', '')} → {item.get('to', '')}"
                    extra = f" ({item['type']})" if item.get("type") else ""
                    why = f" — why: {item['why']}" if item.get("why") else ""
                    L.append(f"- {key[:-1] if key != 'built' else 'built'}{extra}: {text}{why}{ev(item)}")
        L.append("")

    L += ["## Commits (chronological; c:<sha> is the evidence id)", ""]
    for c in manifest["commits"]:
        if c["merge"]:
            continue
        flags = " [revert]" if c["revert"] else ""
        flags += "" if c["merged"] else " [not on default branch]"
        L.append(f"- {c['ts'][:10]} c:{c['sha7']} {clip(c['subject'], 120)} (session {c['session'] or '-'}, "
                 f"+{c['insertions']}/-{c['deletions']}){flags}")
    (wd / "bundle.md").write_text("\n".join(L) + "\n")
    print(f"wrote {wd / 'bundle.md'} (~{len(chr(10).join(L)) // 4:,} tokens)")


if __name__ == "__main__":
    main()
