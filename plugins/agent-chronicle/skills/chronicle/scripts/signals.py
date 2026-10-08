"""Deterministic signals per session and per project. Counts only; interpretation is the model's job."""

import re
from collections import Counter
from statistics import median

from _common import parse_ts

CORRECTION = re.compile(
    r"^\s*(no\b|nope|wrong|that'?s not|that is not|not what|still\b|doesn'?t work|didn'?t work|"
    r"isn'?t working|not working|broken|revert|undo|stop\b|why did you|you (?:didn'?t|forgot|broke)|try again)",
    re.I)
VERIFY = re.compile(r"\b(tests?|verify|verif\w+|validate|make sure|confirm|check that|assert|e2e|lint)\b", re.I)
CRITERIA = re.compile(r"\b(success criteria|acceptance|done when|definition of done|should|must|so that|"
                      r"expected|goal is|the goal|requirements?)\b", re.I)
FILE_REF = re.compile(r"(@[\w./-]+|\b[\w.-]+/[\w./-]+\.\w{1,5}\b|\b[\w-]+\.(?:py|ts|tsx|js|jsx|md|json|go|rs|"
                      r"java|rb|sql|ya?ml|toml|sh|css|html)\b)")
PLAN_DOC = re.compile(r"(^|/)(plans?|specs?|rfcs?|adrs?)/|(^|/|[-_])(plan|spec|prd|design|rfc|adr)[-_.\w]*\.md$", re.I)


def session_signals(session, events):
    prompts = [e for e in events if e["kind"] == "user_prompt"]
    edits = [e for e in events if e["kind"] == "edit"]
    code_edits = [e for e in edits if not PLAN_DOC.search(e["target"])]
    plans = [e for e in events if e["kind"] == "plan" or (e["kind"] == "edit" and PLAN_DOC.search(e["target"]))]
    tests = [e for e in events if e["kind"] == "test"]
    churn = Counter(e["target"] for e in code_edits)
    subagents = [e for e in events if e["kind"] == "subagent"]
    per_msg = Counter(e["id"] for e in subagents)
    av = session["agentsview"]
    q = {k: v for k, v in (av.get("quality_signals") or {}).items() if k != "version"}
    duration = (parse_ts(session["ended"]) - parse_ts(session["started"])).total_seconds() / 60
    return {
        "session": session["short"],
        "title": session["title"],
        "agent": session["agent"],
        "started": session["started"],
        "duration_min": round(duration),
        "human_prompts": len(prompts),
        "agent_steps": sum(1 for e in events if e["kind"] not in ("user_prompt", "slash_command", "interrupt")),
        "first_prompt_chars": len(prompts[0]["text"]) if prompts else 0,
        "median_prompt_chars": round(median(len(p["text"]) for p in prompts)) if prompts else 0,
        "first_prompt_has_criteria": bool(prompts and CRITERIA.search(prompts[0]["text"])),
        "prompts_with_file_refs": sum(1 for p in prompts if FILE_REF.search(p["text"])),
        "slash_commands": [e["text"].split()[0] for e in events if e["kind"] == "slash_command" and e["text"]],
        "plans": len(plans),
        "plan_before_code": bool(plans) and (not code_edits or plans[0]["ts"] <= code_edits[0]["ts"]),
        "verification_asked": any(VERIFY.search(p["text"]) for p in prompts),
        "tests_run": len(tests),
        "tests_failed": sum(1 for t in tests if t["status"] != "ok"),
        "interrupts": sum(1 for e in events if e["kind"] == "interrupt"),
        "denials": sum(1 for e in events if e.get("status") == "denied"),
        "corrections": sum(1 for p in prompts[1:] if CORRECTION.match(p["text"])),
        "files_edited": len(churn),
        "edits": len(code_edits),
        "churn_files": [f for f, n in churn.most_common(5) if n >= 5],
        "rollbacks": sum(1 for e in events if e.get("git") == "rollback"),
        "commit_commands": sum(1 for e in events if e.get("git") == "commit"),
        "pr_commands": sum(1 for e in events if e.get("git") == "pr"),
        "commits_linked": len(session["commits"]),
        "subagents": len(subagents),
        "max_parallel_subagents": max(per_msg.values(), default=0),
        "subagent_sessions": session["children"],
        "destructive_commands": sum(1 for e in events if e.get("destructive")),
        "compactions": av.get("compaction_count") or 0,
        "peak_context_tokens": av.get("peak_context_tokens"),
        "models": sorted({e["model"] for e in events if e.get("model")}),
        "health": av.get("health_grade"),
        "outcome": av.get("outcome"),
        "secret_leaks": av.get("secret_leak_count") or 0,
        "edit_churn": av.get("edit_churn_count") or 0,
        "tool_retries": av.get("tool_retry_count") or 0,
        "tool_failures": av.get("tool_failure_signal_count") or 0,
        "quality": q,
    }


def automated_sessions(manifest, events_by_session):
    """Sessions opened by a hook or tool: 3+ single-prompt sessions that share the same opening text."""
    firsts = {}
    for s in manifest["sessions"]:
        prompts = [e for e in events_by_session[s["short"]] if e["kind"] == "user_prompt"]
        if len(prompts) == 1:
            firsts[s["short"]] = " ".join(prompts[0]["text"].split())[:80].lower()
    counts = Counter(firsts.values())
    return {short for short, key in firsts.items() if counts[key] >= 3}


def pct(n, d):
    return round(100 * n / d) if d else None


def compute(manifest, events_by_session):
    per = {s["short"]: session_signals(s, events_by_session[s["short"]]) for s in manifest["sessions"]}
    automated = automated_sessions(manifest, events_by_session)
    for short, r in per.items():
        r["automated"] = short in automated
    rows = list(per.values())
    # Rates describe how the human worked: leave out sessions a hook or tool opened, and stubs where
    # no agent activity was recorded.
    active = [r for r in rows if r["human_prompts"] and r["agent_steps"] and not r["automated"]]
    sessions = manifest["sessions"]
    commits = [c for c in manifest["commits"] if not c["merge"]]
    first_session = min(s["started"] for s in sessions)[:10]
    pre = [c for c in commits if c["ts"][:10] < first_session]
    days = {s["started"][:10] for s in sessions} | {c["ts"][:10] for c in commits if c["session"]}
    n = len(active)
    project = {
        "sessions": len(sessions),
        "sessions_active": n,
        "sessions_stub": sum(1 for r in rows if not r["agent_steps"]),
        "sessions_automated": len(automated),
        "subagent_sessions": sum(s["children"] for s in sessions),
        "agents": dict(Counter(s["agent"] for s in sessions)),
        "first": first_session,
        "last": max(s["ended"] for s in sessions)[:10],
        "active_days": len(days),
        "human_prompts": sum(r["human_prompts"] for r in rows if not r["automated"]),
        "median_prompts_per_session": median(r["human_prompts"] for r in active) if active else 0,
        "median_first_prompt_chars": median(r["first_prompt_chars"] for r in active) if active else 0,
        "pct_first_prompt_with_criteria": pct(sum(r["first_prompt_has_criteria"] for r in active), n),
        "pct_plan_before_code": pct(sum(r["plan_before_code"] for r in active if r["edits"]),
                                    sum(1 for r in active if r["edits"])),
        "pct_verification_asked": pct(sum(r["verification_asked"] for r in active), n),
        "pct_sessions_running_tests": pct(sum(1 for r in active if r["tests_run"]), n),
        "pct_sessions_with_corrections": pct(sum(1 for r in active if r["corrections"] or r["interrupts"]), n),
        "pct_sessions_compacted": pct(sum(1 for r in active if r["compactions"]), n),
        "pct_sessions_using_subagents": pct(sum(1 for r in active if r["subagents"]), n),
        "pct_sessions_with_commits": pct(sum(1 for r in active if r["commits_linked"]), n),
        "compactions": sum(r["compactions"] for r in rows),
        "interrupts": sum(r["interrupts"] for r in rows),
        "denials": sum(r["denials"] for r in rows),
        "rollbacks": sum(r["rollbacks"] for r in rows),
        "destructive_commands": sum(r["destructive_commands"] for r in rows),
        "secret_leaks": sum(r["secret_leaks"] for r in rows),
        "health_grades": dict(Counter(r["health"] for r in rows if r["health"])),
        "slash_commands": dict(Counter(c for r in rows for c in r["slash_commands"]).most_common(15)),
        "quality_totals": dict(sum((Counter(r["quality"]) for r in rows), Counter())),
        "commits": len(commits),
        "commits_linked": sum(1 for c in commits if c["session"]),
        "commits_with_agent_trailer": sum(1 for c in commits if c["agent_trailer"]),
        "reverts": sum(1 for c in commits if c["revert"]),
        "unmerged_commits": sum(1 for c in commits if not c["merged"]),
        "merges": sum(1 for c in manifest["commits"] if c["merge"]),
        "pre_history_commits": len(pre),
        "pre_history_first": pre[0]["ts"][:10] if pre else None,
        "context_file_first_added": manifest["context_files"]["first_added"],
    }
    return {"project": project, "sessions": per}
