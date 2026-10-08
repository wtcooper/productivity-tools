"""The only module that talks to agentsview. Everything else reads the normalized output of extract.py.

agentsview (https://github.com/kenn-io/agentsview) indexes every agent's sessions into
~/.agentsview/sessions.db and keeps them after the agent deletes its own transcripts. We use
its JSON CLI, never its internal tables, so its schema can change without breaking us.
Read commands start the agentsview background server if it is not running.
"""

import json
import re
import shutil
import subprocess

from _common import fail

MIN_VERSION = (0, 44, 0)
INSTALL_HINT = ("Install agentsview: `brew install --cask agentsview` "
                "(or `curl -fsSL https://agentsview.io/install.sh | bash`), then run `agentsview sync`.")


def installed():
    return shutil.which("agentsview") is not None


def version():
    if not installed():
        return None
    out = subprocess.run(["agentsview", "--version"], capture_output=True, text=True).stdout
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else None


def _run(*args):
    if not installed():
        fail(f"agentsview is not installed. {INSTALL_HINT}")
    p = subprocess.run(["agentsview", *args, "--json"], capture_output=True, text=True, timeout=600)
    if p.returncode:
        fail(f"`agentsview {' '.join(args)}` failed: {p.stderr.strip()[-600:]}")
    out = p.stdout
    start = min((i for i in (out.find("{"), out.find("[")) if i >= 0), default=-1)
    if start < 0:
        fail(f"`agentsview {' '.join(args)}` returned no JSON")
    return json.loads(out[start:])


def sync():
    """Incremental sync of every agent's session files into the agentsview index."""
    if not installed():
        fail(f"agentsview is not installed. {INSTALL_HINT}")
    p = subprocess.run(["agentsview", "sync"], capture_output=True, text=True, timeout=900)
    if p.returncode:
        fail(f"`agentsview sync` failed: {p.stderr.strip()[-600:]}")
    return p.stdout.strip().splitlines()[-1:] or [""]


def list_sessions(include_automated=False, include_source=False):
    """All sessions (top-level and subagent), oldest first."""
    sessions, cursor = [], None
    while True:
        args = ["session", "list", "--include-children", "--include-one-shot",
                "--limit", "500", "--sort", "started:asc"]
        args += ["--include-automated"] if include_automated else []
        args += ["--include-source"] if include_source else []
        if cursor:
            args += ["--cursor", cursor]
        page = _run(*args)
        sessions += page.get("sessions") or []
        cursor = page.get("next_cursor")
        if not cursor or not page.get("sessions"):
            return sessions


def messages(session_id):
    """Every message of one session in ordinal order, each with its tool calls and results."""
    out, start = [], 0
    while True:
        page = _run("session", "messages", session_id, "--from", str(start), "--limit", "1000")
        batch = page.get("messages") or []
        if not batch:
            return out
        out += batch
        start = int(batch[-1]["ordinal"]) + 1
