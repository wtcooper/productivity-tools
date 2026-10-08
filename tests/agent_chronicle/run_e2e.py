#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""End-to-end test of agent-chronicle without agentsview or a model.

    python3 tests/agent_chronicle/run_e2e.py

A fake `agentsview` on PATH serves fixture sessions; a temp git repo supplies commits. Model output
(cards, story.json, coach.json) is written by this test, then the evidence gate must accept the valid
documents and reject each injected defect.
"""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "plugins/agent-chronicle/skills/chronicle/scripts"
SECRET = "sk-ant-api03-" + "Z" * 40
REVIEW = "Review this change for security vulnerabilities.\nChanged files:\n  - app.py"

FAKE_AGENTSVIEW = r'''#!/usr/bin/env python3
import json, os, sys
fx = json.load(open(os.environ["FAKE_AV_FIXTURE"]))
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("agentsview v0.44.0 (commit test)")
elif a[:1] == ["sync"]:
    print("Sync complete")
elif a[:2] == ["session", "list"]:
    print(json.dumps({"sessions": fx["sessions"], "total": len(fx["sessions"])}))
elif a[:2] == ["session", "messages"]:
    start = int(a[a.index("--from") + 1])
    msgs = [m for m in fx["messages"].get(a[2], []) if m["ordinal"] >= start]
    print(json.dumps({"messages": msgs, "count": len(msgs)}))
else:
    sys.exit(f"fake agentsview: unsupported {a}")
'''


def run(*args, ok=True, env=None):
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, env=env)
    if ok and p.returncode:
        sys.exit(f"FAILED: {' '.join(map(str, args))}\n{p.stdout}\n{p.stderr}")
    return p


def git(repo, *args, date=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}
    if date:
        env |= {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def tool(name, category, inp, result="", **extra):
    return {"tool_name": name, "category": category, "input_json": json.dumps(inp) if isinstance(inp, dict) else inp,
            "result_content": result, **extra}


def msg(ordinal, ts, role, content="", tools=None, **extra):
    return {"ordinal": ordinal, "timestamp": ts, "role": role, "content": content, "tool_calls": tools or [],
            "is_system": False, "is_compact_boundary": False, **extra}


def build_fixture(tmp):
    repo = tmp / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("print('v1')\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Pre-history commit", date="2026-09-01T10:00:00+00:00")
    (repo / "app.py").write_text("print('v2')\n")
    (repo / "test_app.py").write_text("def test_ok():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Add greeting and tests\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        date="2026-09-10T10:20:00+00:00")
    (repo / "app.py").write_text("print('v3')\n")
    git(repo, "commit", "-q", "-am", "Try cache layer", date="2026-09-11T09:30:00+00:00")
    git(repo, "revert", "--no-edit", "HEAD", date="2026-09-11T09:50:00+00:00")
    root = str(repo.resolve())

    s1, s2, child = "aaaaaaaa-1111-2222-3333-444444444444", "codex:bbbbbbbb-1111-2222-3333-444444444444", "agent-cccccccc1111"
    sources = tmp / "agent-logs"
    sources.mkdir()
    for name in ("s1.jsonl", "s2.jsonl"):
        (sources / name).write_text('{"type": "user"}\n' * 50)
    sessions = [
        {"id": s1, "agent": "claude", "cwd": root, "git_branch": "main", "display_name": "Build the greeting app",
         "file_path": str(sources / "s1.jsonl"),
         "started_at": "2026-09-10T10:00:00Z", "ended_at": "2026-09-10T10:30:00Z", "web_url": "http://127.0.0.1:8080/sessions/a",
         "first_message": "x", "compaction_count": 1, "health_grade": "B", "outcome": "success",
         "quality_signals": {"version": 3, "unstructured_start": False, "missing_success_criteria_count": 0}},
        {"id": child, "agent": "claude", "cwd": root, "parent_session_id": s1, "relationship_type": "subagent",
         "started_at": "2026-09-10T10:05:00Z", "ended_at": "2026-09-10T10:06:00Z", "first_message": "sub"},
        {"id": s2, "agent": "codex", "cwd": root, "git_branch": "main", "display_name": "Add a cache",
         "file_path": str(sources / "s2.jsonl"),
         "started_at": "2026-09-11T09:00:00Z", "ended_at": "2026-09-11T10:00:00Z", "first_message": "y",
         "health_grade": "C"},
        {"id": "eeeeeeee-0000", "agent": "claude", "cwd": root, "display_name": "Automated review",
         "started_at": "2026-09-12T08:00:00Z", "ended_at": "2026-09-12T08:00:01Z", "first_message": "Review"},
        *[{"id": f"ffffffff-000{i}", "agent": "claude", "cwd": root, "display_name": "Security review",
           "started_at": f"2026-09-12T0{i}:00:00Z", "ended_at": f"2026-09-12T0{i}:02:00Z", "first_message": "Review"}
          for i in (1, 2, 3)],
        {"id": "dddddddd-0000", "agent": "claude", "cwd": "/somewhere/else", "started_at": "2026-09-10T00:00:00Z",
         "ended_at": "2026-09-10T00:01:00Z", "first_message": "other project"},
    ]
    messages = {
        s1: [
            msg(0, "2026-09-10T10:00:00Z", "user",
                "<browser_instruction>injected harness text</browser_instruction>Build a greeting app. "
                f"Done when pytest passes. My key is {SECRET} do not leak it."),
            msg(1, "2026-09-10T10:01:00Z", "assistant", "I will plan first.\n[ExitPlanMode]",
                [tool("ExitPlanMode", "Other", {"plan": "1. Write app.py\n2. Add tests"})]),
            msg(2, "2026-09-10T10:02:00Z", "assistant", "[Edit: app.py]",
                [tool("Edit", "Edit", {"file_path": f"{root}/app.py", "old_string": "v1", "new_string": "v2"}, "ok")]),
            msg(3, "2026-09-10T10:03:00Z", "assistant", "[Task: explore]",
                [tool("Agent", "Task", {"description": "Explore repo", "subagent_type": "Explore"}, "launched",
                      subagent_session_id=child)]),
            msg(4, "2026-09-10T10:04:00Z", "assistant", "[Bash: run tests]\n$ uv run pytest -q",
                [tool("Bash", "Bash", {"command": "uv run pytest -q"}, "Exit code 1\n1 failed")]),
            msg(5, "2026-09-10T10:05:00Z", "user", "[Request interrupted by user for tool use]",
                is_system=True, source_subtype="interrupted"),
            msg(6, "2026-09-10T10:06:00Z", "user", "still broken, the test imports the wrong module"),
            msg(7, "2026-09-10T10:07:00Z", "assistant", "This session is being continued. Summary: tests fixed.",
                is_system=True, is_compact_boundary=True, source_subtype="compact_boundary"),
            msg(8, "2026-09-10T10:10:00Z", "assistant", "[Bash: run tests]\n$ uv run pytest -q",
                [tool("Bash", "Bash", {"command": "uv run pytest -q"}, "1 passed")]),
            msg(9, "2026-09-10T10:19:00Z", "assistant", "[Bash: commit]\n$ git commit -am 'Add greeting and tests'",
                [tool("Bash", "Bash", {"command": "git commit -am 'Add greeting and tests'"}, "[main abc] ok")]),
            msg(10, "2026-09-10T10:20:00Z", "assistant", "Done: the greeting app prints v2 and its test passes."),
            msg(11, "2026-09-10T10:21:00Z", "user", "<task-notification>agent finished</task-notification>"),
            msg(12, "2026-09-10T10:22:00Z", "user", "<command-name>/review</command-name><command-args>app.py</command-args>"),
            msg(13, "2026-09-10T10:23:00Z", "user", "/model opus"),
            msg(14, "2026-09-10T10:24:00Z", "assistant", "[Bash: clean]",
                [tool("Bash", "Bash", {"command": "rm -rf /tmp/scratch && rm -rf build"}, "")]),
            msg(15, "2026-09-10T10:25:00Z", "assistant", "[Bash: wipe]", [tool("Bash", "Bash", {"command": "rm -rf src"}, "")]),
            # compaction replays preserved messages with their original timestamps
            msg(16, "2026-09-10T10:06:00Z", "user", "still broken, the test imports the wrong module"),
            msg(17, "2026-09-10T10:10:00Z", "assistant", "[Bash: run tests]\n$ uv run pytest -q",
                [tool("Bash", "Bash", {"command": "uv run pytest -q"}, "1 passed")]),
        ],
        "eeeeeeee-0000": [msg(0, "2026-09-12T08:00:00Z", "user", REVIEW)],
        **{f"ffffffff-000{i}": [msg(0, f"2026-09-12T0{i}:00:00Z", "user", REVIEW),
                                msg(1, f"2026-09-12T0{i}:01:00Z", "assistant", "No vulnerabilities found.")] for i in (1, 2, 3)},
        s2: [
            msg(0, "2026-09-11T09:00:00Z", "user", "<environment_context>cwd</environment_context>"),
            msg(1, "2026-09-11T09:01:00Z", "user", "add a cache layer to app.py"),
            msg(2, "2026-09-11T09:05:00Z", "assistant", "[Bash]",
                [tool("exec", "Bash", 'text(await tools.apply_patch("*** Begin Patch\\n*** Update File: '
                      + root + '/app.py\\n@@\\n-v2\\n+v3\\n*** End Patch"))', "ok")]),
            msg(3, "2026-09-11T09:29:00Z", "assistant", "[Bash]",
                [tool("exec", "Bash", 'const r = await tools.exec_command({cmd:"git commit -am \\"Try cache layer\\""})', "ok")]),
            msg(4, "2026-09-11T09:45:00Z", "user", "no, revert that, the cache breaks output"),
            msg(5, "2026-09-11T09:49:00Z", "assistant", "[Bash]",
                [tool("exec", "Bash", 'const r = await tools.exec_command({cmd:"git revert --no-edit HEAD"})', "ok")]),
            msg(6, "2026-09-11T09:51:00Z", "assistant", "Reverted the cache layer."),
        ],
    }
    fixture = tmp / "fixture.json"
    fixture.write_text(json.dumps({"sessions": sessions, "messages": messages}))
    bindir = tmp / "bin"
    bindir.mkdir()
    fake = bindir / "agentsview"
    fake.write_text(FAKE_AGENTSVIEW.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return repo, fixture, bindir, sources


def check(cond, what):
    if not cond:
        sys.exit(f"FAILED: {what}")
    print(f"ok  {what}")


def main():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo, fixture, bindir, sources = build_fixture(tmp)
        home = tmp / "home"
        os.environ.update({"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_AV_FIXTURE": str(fixture),
                           "AGENT_CHRONICLE_HOME": str(home)})
        proj = ["--project", str(repo)]

        check(run(SCRIPTS / "doctor.py").returncode == 0, "doctor passes with agentsview present")
        out = run(SCRIPTS / "extract.py", *proj).stdout
        check("sessions:  6 (claude 5, codex 1); 1 subagent sessions folded" in out, "extract finds 6 sessions, folds the subagent")
        check("commits:   4 (3 linked to a session)" in out, "three of four commits link to sessions (pre-history stays unlinked)")

        archive_dir = home / "archive"
        check("archive: 2 new" in out and len(list(archive_dir.rglob("*.jsonl.gz"))) == 2,
              "extract archives raw sources locally (gzip)")
        (sources / "s1.jsonl").write_text('{"type": "user"}\n' * 60)
        out = run(SCRIPTS / "archive.py").stdout
        check("0 new, 1 refreshed" in out, "a grown source is refreshed in the archive")
        (sources / "s2.jsonl").unlink()
        out = run(SCRIPTS / "archive.py").stdout
        check("0 new, 0 refreshed" in out and "1 kept after their source was deleted" in out
              and len(list(archive_dir.rglob("*.jsonl.gz"))) == 2, "archive keeps a copy after the agent deletes the source")
        check(not (repo / ".agent-chronicle").exists() and str(home) not in str(repo),
              "nothing session-derived is written into the project")

        wd = home / "work" / "app"
        manifest = json.loads((wd / "manifest.json").read_text())
        timeline = [json.loads(line) for line in (wd / "timeline.ndjson").read_text().splitlines()]
        raw = (wd / "timeline.ndjson").read_text() + "".join(p.read_text() for p in (wd / "digests").glob("*.md"))
        check(SECRET not in raw and "[REDACTED]" in raw, "secret redacted from timeline and digests")
        check("injected harness text" not in raw, "harness-injected blocks stripped from prompts")
        kinds = {e["id"]: e["kind"] for e in timeline}
        check(kinds.get("aaaaaaaa:5") == "interrupt" and kinds.get("aaaaaaaa:12") == "slash_command", "interrupt and slash command classified")
        check("aaaaaaaa:11" not in kinds and "bbbbbbbb:0" not in kinds, "automated and environment messages dropped")
        check(kinds.get("aaaaaaaa:7") == "compaction" and kinds.get("aaaaaaaa:1") == "plan", "compaction and plan captured")
        codex_edit = [e for e in timeline if e["session"] == "bbbbbbbb" and e["kind"] == "edit"]
        check(codex_edit and codex_edit[0]["target"].endswith("/app.py"), "Codex apply_patch inside exec parsed as an edit")
        by_subject = {c["subject"]: c for c in manifest["commits"]}
        check(by_subject["Add greeting and tests"]["session"] == "aaaaaaaa", "commit linked by git commit call + trailer")
        check(by_subject["Try cache layer"]["session"] == "bbbbbbbb", "Codex commit linked")
        check(by_subject['Revert "Try cache layer"']["revert"], "revert commit detected")

        sig = json.loads((wd / "signals.json").read_text())
        s1 = sig["sessions"]["aaaaaaaa"]
        check(s1["plan_before_code"] and s1["tests_run"] == 2 and s1["tests_failed"] == 1, "plan-first and test signals")
        check(s1["interrupts"] == 1 and s1["corrections"] == 1, "interrupt (agentsview 'interrupted' subtype) and correction counted")
        check("aaaaaaaa:16" not in kinds and "aaaaaaaa:17" not in kinds, "messages replayed by compaction are counted once")
        check(s1["slash_commands"] == ["/review", "/model"], "tagged and plain-text slash commands captured")
        check(s1["destructive_commands"] == 1, "rm -rf of scratch/build is housekeeping; rm -rf src is destructive")
        check({"ffffffff", "ffff0002", "ffff0003"} <= set(sig["sessions"]), "colliding 8-char ids are disambiguated")
        check(sig["sessions"]["ffffffff"]["automated"] and sig["project"]["sessions_automated"] == 4,
              "templated single-prompt sessions detected as automated")
        check(sig["project"]["sessions_active"] == 2, "rates use only the 2 human-driven sessions")
        check("## Automated sessions (4)" in (wd / "prompts.md").read_text(), "prompts.md groups automated sessions")
        check(sig["sessions"]["bbbbbbbb"]["rollbacks"] == 1 and sig["project"]["pre_history_commits"] == 1, "rollback and pre-history signals")

        run(SCRIPTS / "audit.py", *proj)
        art = repo / ".agent-chronicle"
        audit = (art / "audit.md").read_text()
        check("Build the greeting app" in audit and "Pre-history commit" in audit, "audit lists sessions and unlinked commits")
        check("no agent activity recorded" in audit, "audit flags the stub session")

        # --- map step stand-in: valid cards, then the gate
        pending = json.loads((wd / "pending.json").read_text())["digests"]
        check(len(pending) == 5, "one digest per session with agent activity; the stub session gets none")
        for d in pending:
            sid = d["session"]
            first = next(e for e in timeline if e["session"] == sid and e["kind"] == "user_prompt")
            card = {"digest": d["name"], "digest_sha": d["sha"], "session": sid,
                    "goal": {"text": "Goal", "evidence": [first["id"]]}, "summary": "What happened.",
                    "outcome": "shipped" if sid == "aaaaaaaa" else "reverted",
                    "built": [{"text": "Thing", "evidence": [first["id"]]}], "decisions": [], "backtracks": [],
                    "open_threads": []}
            (wd / "cards").mkdir(exist_ok=True)
            (wd / "cards" / f"{d['name']}.json").write_text(json.dumps(card))
        check(run(SCRIPTS / "check_evidence.py", "cards", *proj).returncode == 0, "valid cards pass the gate")
        run(SCRIPTS / "extract.py", *proj, "--no-sync")
        check(json.loads((wd / "pending.json").read_text())["digests"] == [], "re-run reuses cached cards")
        fx = json.loads(fixture.read_text())
        fx["sessions"][0]["display_name"] = "Greeting app, retitled as the session grew"
        fixture.write_text(json.dumps(fx))
        run(SCRIPTS / "extract.py", *proj, "--no-sync")
        check(json.loads((wd / "pending.json").read_text())["digests"] == [],
              "a header-only change (new title) keeps the cached cards")
        run(SCRIPTS / "bundle.py", *proj)
        check("goal: Goal [aaaaaaaa:0]" in (wd / "bundle.md").read_text(), "bundle includes cards with evidence")

        story = {
            "headline": "A greeting app shipped; a cache experiment was reverted </script><script>alert(1)</script>",
            "origin": {"problem_statement": "Need a greeting app", "intent": "Build it with tests",
                       "success_criteria": ["pytest passes"], "evidence": ["aaaaaaaa:0"],
                       "quote": "Done when pytest passes."},
            "intent_drift": {"original": "Greeting app", "delivered": "Greeting app",
                             "shifts": [{"what": "Tried a cache", "evidence": ["bbbbbbbb:1"]}]},
            "chapters": [{"id": "ch1", "title": "Build", "goal": "Ship", "summary": "Built and tested.",
                          "episodes": ["ep1", "ep2"], "evidence": ["aaaaaaaa:0"]}],
            "episodes": [{"id": "ep1", "title": "Greeting", "summary": "s", "outcome": "shipped", "sessions": ["aaaaaaaa"],
                          "commits": [by_subject["Add greeting and tests"]["sha7"]], "evidence": ["aaaaaaaa:10"]},
                         {"id": "ep2", "title": "Cache", "summary": "s", "outcome": "reverted", "sessions": ["bbbbbbbb"],
                          "commits": [], "evidence": ["bbbbbbbb:4"]}],
            "pivots": [{"id": "pv1", "type": "reverted", "from": "cache", "to": "no cache", "why": "broke output",
                        "evidence": ["bbbbbbbb:4", "c:" + by_subject['Revert "Try cache layer"']["sha7"]]}],
            "shipped": [{"what": "Greeting app", "commits": [by_subject["Add greeting and tests"]["sha7"]],
                         "evidence": ["aaaaaaaa:10"]}],
            "lessons": [{"text": "Test before caching", "evidence": ["bbbbbbbb:4"]}],
            "open_threads": [],
        }
        story_path = wd / "story.json"
        story_path.write_text(json.dumps(story))
        check(run(SCRIPTS / "check_evidence.py", "story", *proj).returncode == 0, "valid story passes the gate")
        for mutate, expect in (
            (lambda s: s["episodes"][0].update(evidence=["aaaaaaaa:999"]), "unknown evidence id"),
            (lambda s: s["origin"].update(quote="Done when everything is perfect"), "not found verbatim"),
            (lambda s: s["lessons"][0].update(text=f"key {SECRET}"), "looks like a secret"),
            (lambda s: s["chapters"][0].update(episodes=["ep1"]), "exactly one chapter"),
            (lambda s: s["pivots"][0].update(type="oops"), "type must be one of"),
        ):
            bad = json.loads(json.dumps(story))
            mutate(bad)
            story_path.write_text(json.dumps(bad))
            p = run(SCRIPTS / "check_evidence.py", "story", *proj, ok=False)
            check(p.returncode == 1 and expect in p.stdout, f"gate rejects story: {expect}")
        story_path.write_text(json.dumps(story))

        run(SCRIPTS / "render.py", "chronicle", *proj)
        html = (art / "chronicle.html").read_text()
        data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
                          .replace("<\\/", "</"))
        check("__DATA__" not in html and "<\\/script><script>alert(1)" in html, "data embedded with </script> escaped")
        check(data["evidence"]["aaaaaaaa:0"]["text"] is None and "quote" not in data["story"]["origin"],
              "no prompt text or quotes without --quotes")
        check(data["evidence"]["c:" + by_subject['Revert "Try cache layer"']["sha7"]]["text"] == 'Revert "Try cache layer"',
              "commit subjects always shown")
        check(data["story"]["chapters"][0]["start"] == "2026-09-10" and data["story"]["chapters"][0]["end"] == "2026-09-11",
              "chapter dates computed from evidence")
        brief = (art / "brief.md").read_text()
        check("## Key pivots" in brief and "reverted" in brief, "brief written")
        out_q = tmp / "quoted"
        run(SCRIPTS / "render.py", "chronicle", *proj, "--quotes", "--out", out_q)
        html_q = (out_q / "chronicle.html").read_text()
        check("Build a greeting app" in html_q and SECRET not in html_q, "--quotes adds redacted excerpts")

        coach = {
            "dimensions": [{"id": d, "score": 3, "summary": "ok",
                            "strengths": [{"text": "a", "evidence": ["aaaaaaaa:0"]}],
                            "gaps": [{"text": "b", "evidence": ["bbbbbbbb:1"]}]}
                           for d in ["framing", "planning", "context", "verification", "steering", "scope", "vcs", "delegation"]],
            "habits": [{"title": f"h{i}", "detail": "d", "dimension": "framing"} for i in range(3)],
            "rewrites": [{"evidence": "bbbbbbbb:1", "original_excerpt": "add a cache layer to app.py",
                          "rewrite": "Add a cache layer to app.py; done when output is unchanged and tests pass.", "why": "criteria"}],
            "best_prompts": [{"evidence": "aaaaaaaa:0", "excerpt": "Done when pytest passes.", "why": "clear"}],
            "own_rules": [], "safety_flags": [],
        }
        coach_path = wd / "coach.json"
        coach_path.write_text(json.dumps(coach))
        check(run(SCRIPTS / "check_evidence.py", "coach", *proj).returncode == 0, "valid coach passes the gate")
        bad = json.loads(json.dumps(coach))
        bad["dimensions"].pop()
        bad["rewrites"][0]["original_excerpt"] = "make a cache please"
        coach_path.write_text(json.dumps(bad))
        p = run(SCRIPTS / "check_evidence.py", "coach", *proj, ok=False)
        check(p.returncode == 1 and "dimensions must be exactly" in p.stdout and "not found verbatim" in p.stdout,
              "gate rejects coach: missing dimension, invented excerpt")
        coach_path.write_text(json.dumps(coach))
        def coach_data():
            run(SCRIPTS / "render.py", "coach", *proj)
            html = (art / "coach.html").read_text()
            return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
                              .group(1).replace("<\\/", "</"))
        first = coach_data()
        check(first["overall"]["previous"] is None, "first coach run has no trend")
        coach_data()
        check(len(json.loads((art / "coach-history.json").read_text())) == 1, "re-rendering the same run adds no history")
        coach["dimensions"][0]["score"] = 4
        coach_path.write_text(json.dumps(coach))
        cdata = coach_data()
        check(cdata["overall"]["previous"] == 3.0 and cdata["dimensions"][0]["previous"] == 3, "coach trend uses the previous run")
        artifacts = {p.name for p in art.iterdir()}
        check(artifacts == {"chronicle.html", "brief.md", "audit.md", "audit.csv", "coach.html", "coach-history.json"},
              f"project folder holds only artifacts: {sorted(artifacts)}")
        check(len(cdata["metrics"]) >= 10, "coach metrics computed from signals")
    print("\nall agent-chronicle e2e checks passed")


if __name__ == "__main__":
    main()
