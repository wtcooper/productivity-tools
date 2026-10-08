#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Render checked story.json / coach.json into shareable reports.

    uv run scripts/render.py chronicle [--project PATH] [--out DIR] [--quotes]
    uv run scripts/render.py coach     [--project PATH] [--out DIR]

chronicle -> chronicle.html (storyboard with Present mode) + brief.md (leadership one-pager)
coach     -> coach.html (scorecard with trend against the previous run) + coach-history.json
Artifacts go to <project>/.agent-chronicle/; session-derived inputs stay in $AGENT_CHRONICLE_HOME.
Dates, counts, and commits come from extract.py output, never from the model. Without
--quotes, the chronicle shows no prompt or agent text, only commit subjects and metadata.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (SKILL_DIR, clip, fail, load_work, parse_ts, read_json, read_ndjson,  # noqa: E402
                     report_dir, write_json)

KIND_LABEL = {"user_prompt": "Prompt", "assistant_text": "Agent", "plan": "Plan", "compaction": "Compaction summary",
              "edit": "Edit", "test": "Test run", "command": "Command", "subagent": "Subagent", "commit": "Commit",
              "interrupt": "Interrupt", "slash_command": "Slash command", "tool": "Tool call"}
DIMENSION_NAMES = {"framing": "Problem framing", "planning": "Planning & decomposition",
                   "context": "Context engineering", "verification": "Verification discipline",
                   "steering": "Steering quality", "scope": "Session & scope hygiene",
                   "vcs": "Version control & review", "delegation": "Delegation & tooling"}


def collect_ids(obj, out):
    if isinstance(obj, dict):
        ev = obj.get("evidence")
        out.update([ev] if isinstance(ev, str) else ev or [])
        for v in obj.values():
            collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_ids(v, out)
    return out


def strip_quotes(obj):
    if isinstance(obj, dict):
        return {k: strip_quotes(v) for k, v in obj.items() if k != "quote"}
    if isinstance(obj, list):
        return [strip_quotes(v) for v in obj]
    return obj


def evidence_map(ids, events, sessions, quotes):
    by_id = {}
    for e in events:
        by_id.setdefault(e["id"], e)
    out = {}
    for i in sorted(ids):
        e = by_id.get(i)
        if not e:
            continue
        s = sessions.get(e.get("session"))
        show_text = quotes or e["kind"] == "commit"
        out[i] = {
            "id": i,
            "ts": e["ts"],
            "kind": e["kind"],
            "session": e.get("session"),
            "session_title": s["title"] if s else None,
            "label": f"{KIND_LABEL.get(e['kind'], e['kind'].title())} · {parse_ts(e['ts']):%b %d %H:%M}",
            "text": clip(e.get("text") or "", 400) or None if show_text else None,
            "url": s.get("web_url") if s else None,
        }
    return out


def span(dates):
    dates = sorted(d for d in dates if d)
    return (dates[0][:10], dates[-1][:10]) if dates else (None, None)


def embed(template, data):
    html = (SKILL_DIR / "templates" / template).read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    return html.replace("__DATA__", payload, 1)


# ---------------------------------------------------------------- chronicle

def chronicle(wd, manifest, out, quotes):
    story = read_json(wd / "story.json") or fail("story.json missing. Run the story-editor step first.")
    sig = read_json(wd / "signals.json")
    events = read_ndjson(wd / "timeline.ndjson")
    sessions = {s["short"]: s for s in manifest["sessions"]}
    commits = {c["sha7"]: c for c in manifest["commits"]}
    ts_of = {}
    for e in events:
        ts_of.setdefault(e["id"], e["ts"])

    def ev_dates(item):
        return [ts_of[i] for i in collect_ids(item, set()) if i in ts_of]

    story = json.loads(json.dumps(story))
    for ep in story.get("episodes", []):
        # Evidence timestamps, not session spans: one long session can carry many episodes.
        ds = ev_dates(ep) + [commits[c]["ts"] for c in ep.get("commits", []) if c in commits]
        if not ds:
            ds = [sessions[s][k] for s in ep.get("sessions", []) if s in sessions for k in ("started", "ended")]
        ep["start"], ep["end"] = span(ds)
    eps = {ep["id"]: ep for ep in story.get("episodes", [])}
    for ch in story.get("chapters", []):
        ds = [d for e in ch.get("episodes", []) if e in eps for d in (eps[e]["start"], eps[e]["end"])]
        ch["start"], ch["end"] = span(ds or ev_dates(ch))
    # Each pivot belongs to one chapter: the latest-starting chapter that had begun when the pivot happened.
    ch_start = {ch["id"]: min(ev_dates(ch) + [d for e in ch.get("episodes", []) if e in eps
                                              for d in ev_dates(eps[e])], default=None)
                for ch in story.get("chapters", []) if ch.get("id")}
    for p in story.get("pivots", []):
        when = min(ev_dates(p), default=None)
        p["date"] = when[:10] if when else None
        begun = [(start, cid) for cid, start in ch_start.items() if start and when and start <= when]
        p["chapter"] = max(begun)[1] if begun else next(iter(ch_start), None)
    for s in (story.get("intent_drift") or {}).get("shifts", []):
        s["date"] = span(ev_dates(s))[0]
    for sh in story.get("shipped", []):
        ds = [commits[c]["ts"] for c in sh.get("commits", []) if c in commits]
        sh["date"] = span(ds or ev_dates(sh))[1]
    if not quotes:
        story = strip_quotes(story)

    p = sig["project"]
    per_day = Counter()
    prompts_day = Counter(e["ts"][:10] for e in events if e["kind"] == "user_prompt")
    for s in manifest["sessions"]:
        per_day[s["started"][:10]] += 1
    commits_day = Counter(c["ts"][:10] for c in manifest["commits"] if not c["merge"])
    days = sorted(set(per_day) | set(prompts_day) | {d for d, n in commits_day.items() if d >= p["first"]})
    data = {
        "project": {k: manifest["project"][k] for k in ("name", "remote")},  # no local paths in a shareable file
        "generated_at": manifest["generated_at"],
        "quotes": quotes,
        "stats": {k: p[k] for k in ("sessions", "subagent_sessions", "active_days", "first", "last", "human_prompts",
                                    "commits", "commits_linked", "agents", "compactions", "pre_history_commits",
                                    "pre_history_first")},
        "days": [{"date": d, "sessions": per_day[d], "commits": commits_day[d], "prompts": prompts_day[d]} for d in days],
        "story": story,
        "commits": [{"sha": c["sha7"], "date": c["ts"][:10], "subject": c["subject"], "session": c["session"],
                     "revert": c["revert"]} for c in manifest["commits"] if not c["merge"] and c["ts"][:10] >= p["first"]],
        "evidence": evidence_map(collect_ids(story, set()), events, sessions, quotes),
    }
    (out / "chronicle.html").write_text(embed("chronicle.html", data))
    (out / "brief.md").write_text(brief(manifest, data))
    return ["chronicle.html", "brief.md"]


def brief(manifest, data):
    st, s = data["stats"], data["story"]
    o = s.get("origin") or {}
    agents = ", ".join(f"{a} {n}" for a, n in st["agents"].items())
    L = [f"# {manifest['project']['name']}: how it was built", "", s.get("headline", ""), "",
         f"**{st['first']} → {st['last']}** · {st['sessions']} agent sessions over {st['active_days']} active days · "
         f"{st['commits']} commits · agents: {agents}", "", "## The problem", "", o.get("problem_statement", ""), ""]
    if o.get("intent"):
        L += [f"**Intent:** {o['intent']}", ""]
    if o.get("success_criteria"):
        L += ["**Success looked like:**", *[f"- {c}" for c in o["success_criteria"]], ""]
    eps = {e["id"]: e for e in s.get("episodes", [])}
    L += ["## How it unfolded", ""]
    for n, ch in enumerate(s.get("chapters", []), 1):
        L += [f"### {n}. {ch['title']} ({ch.get('start') or '?'} – {ch.get('end') or '?'})", "", ch.get("summary", ""), ""]
        L += [f"- {eps[e]['title']} — *{eps[e]['outcome']}*" for e in ch.get("episodes", []) if e in eps]
        L.append("")
    if s.get("pivots"):
        L += ["## Key pivots", ""]
        for p in s["pivots"]:
            cost = p.get("cost") or {}
            cost_txt = ", ".join(x for x in (f"{cost['sessions']} sessions" if cost.get("sessions") else "",
                                             f"{cost['hours']} h" if cost.get("hours") else "") if x)
            L.append(f"- **{p.get('date') or ''} · {p['type']}:** {p['from']} → {p['to']}. {p['why']}"
                     + (f" *(cost: {cost_txt})*" if cost_txt else ""))
        L.append("")
    if s.get("shipped"):
        L += ["## What shipped", ""]
        L += [f"- {x['what']} ({x.get('date') or '?'}, {len(x.get('commits', []))} commits)" for x in s["shipped"]]
        L.append("")
    drift = s.get("intent_drift") or {}
    if drift.get("original"):
        L += ["## Intent vs. delivered", "", f"- **Set out to:** {drift['original']}",
              f"- **Delivered:** {drift.get('delivered', '')}", ""]
    for key, title in (("lessons", "Lessons"), ("open_threads", "Open threads")):
        if s.get(key):
            L += [f"## {title}", "", *[f"- {x['text']}" for x in s[key]], ""]
    L += ["---", "", "*Dates, counts, and commits are computed from agentsview and git. The narrative is "
          "model-written; every claim links to its evidence in chronicle.html.*", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- coach

def record_history(out, doc, generated_at):
    """coach-history.json keeps one score snapshot per distinct coach run; returns the run before this one."""
    path = out / "coach-history.json"
    history = read_json(path, [])
    sha = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]
    earlier = [h for h in history if h["sha"] != sha]
    if len(earlier) == len(history):
        history.append({"sha": sha, "generated_at": generated_at,
                        "scores": {d["id"]: d.get("score") for d in doc.get("dimensions", [])}})
        write_json(path, history)
    return earlier[-1] if earlier else None


def metrics(p):
    def pct(v):
        return f"{v}%" if v is not None else "—"
    rows = [
        ("Sessions whose first prompt states success criteria", pct(p["pct_first_prompt_with_criteria"]), None),
        ("Code-editing sessions that planned before editing", pct(p["pct_plan_before_code"]),
         "Plan mode, a proposed plan, or a plan/spec doc written before the first code edit"),
        ("Sessions where you asked for tests or verification", pct(p["pct_verification_asked"]), None),
        ("Sessions where tests actually ran", pct(p["pct_sessions_running_tests"]), None),
        ("Sessions with corrections or interrupts", pct(p["pct_sessions_with_corrections"]), None),
        ("Sessions that hit context compaction", pct(p["pct_sessions_compacted"]), f"{p['compactions']} compactions total"),
        ("Sessions using subagents", pct(p["pct_sessions_using_subagents"]), None),
        ("Sessions that produced a commit", pct(p["pct_sessions_with_commits"]), None),
        ("Median human prompts per session", str(p["median_prompts_per_session"]), None),
        ("Median first-prompt length", f"{int(p['median_first_prompt_chars']):,} chars", None),
        ("Commits linked to an agent session", f"{p['commits_linked']} of {p['commits']}", None),
        ("Repo instructions file (CLAUDE.md / AGENTS.md) first committed",
         p["context_file_first_added"] or "never", f"first session {p['first']}"),
    ]
    return [{"label": a, "value": b, "note": c} for a, b, c in rows]


def coach(wd, manifest, out):
    doc = read_json(wd / "coach.json") or fail("coach.json missing. Run the practice-coach step first.")
    sig = read_json(wd / "signals.json")
    events = read_ndjson(wd / "timeline.ndjson")
    sessions = {s["short"]: s for s in manifest["sessions"]}
    prev = record_history(out, doc, manifest["generated_at"])
    prev_scores = (prev or {}).get("scores", {})

    def overall(scores):
        scores = [v for v in scores if isinstance(v, int)]
        return round(sum(scores) / len(scores), 1) if scores else None

    dims = [{**d, "name": DIMENSION_NAMES.get(d["id"], d["id"]), "previous": prev_scores.get(d["id"])}
            for d in doc.get("dimensions", [])]
    data = {
        "project": {k: manifest["project"][k] for k in ("name", "root", "remote")},
        "generated_at": manifest["generated_at"],
        "overall": {"score": overall(d.get("score") for d in dims),
                    "previous": overall(prev_scores.values()) if prev else None,
                    "previous_date": prev["generated_at"][:10] if prev else None},
        "dimensions": dims,
        **{k: doc.get(k, []) for k in ("habits", "rewrites", "best_prompts", "own_rules", "safety_flags")},
        "metrics": metrics(sig["project"]),
        "evidence": evidence_map(collect_ids(doc, set()), events, sessions, quotes=True),
    }
    (out / "coach.html").write_text(embed("coach.html", data))
    return ["coach.html", "coach-history.json"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", choices=["chronicle", "coach"])
    ap.add_argument("--project", default=".")
    ap.add_argument("--out", help="artifact dir (default <project>/.agent-chronicle)")
    ap.add_argument("--quotes", action="store_true", help="include prompt and agent text excerpts in the chronicle")
    args = ap.parse_args()
    root, wd, manifest = load_work(args.project)
    out = report_dir(args.project, args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = chronicle(wd, manifest, out, args.quotes) if args.report == "chronicle" else coach(wd, manifest, out)
    for f in files:
        print(f"wrote {out / f}")


if __name__ == "__main__":
    main()
