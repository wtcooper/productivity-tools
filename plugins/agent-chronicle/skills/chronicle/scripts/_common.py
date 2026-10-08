"""Shared paths, text cleanup, redaction, and evidence ids for agent-chronicle scripts."""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("AGENT_CHRONICLE_HOME", "~/.agent-chronicle")).expanduser()
ARCHIVE = HOME / "archive"
SKILL_DIR = Path(__file__).resolve().parent.parent


def fail(msg):
    sys.exit(f"error: {msg}")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_ndjson(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- time

def parse_ts(value):
    """ISO timestamp (any fraction length, 'Z' or offset) -> aware UTC datetime."""
    s = value.strip().replace("Z", "+00:00")
    m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:
        frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
        s = f"{m.group(1)}.{frac}{m.group(3) or '+00:00'}"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def day(value):
    return parse_ts(value).date().isoformat()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- projects

def git_out(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def repo_root(path):
    """Main repo root for a path (a worktree resolves to the repo it belongs to)."""
    path = Path(path).expanduser().resolve()
    common = git_out(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if common:
        return Path(common).parent if Path(common).name == ".git" else Path(common)
    return path


def project_slug(root):
    root = Path(root)
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", root.name) or "project"
    manifest = read_json(HOME / "work" / slug / "manifest.json")
    if manifest and manifest["project"]["root"] != str(root):
        slug += "-" + hashlib.sha1(str(root).encode()).hexdigest()[:6]
    return slug


def work_dir(root):
    """Session-derived intermediate files. Always under HOME, never inside a project."""
    return HOME / "work" / project_slug(root)


def report_dir(project, out=None):
    """Shareable artifacts go to <checkout>/.agent-chronicle/; committing them is the user's call."""
    if out:
        return Path(out).expanduser().resolve()
    path = Path(project).expanduser().resolve()
    top = git_out(path, "rev-parse", "--show-toplevel").strip()
    return (Path(top) if top else path) / ".agent-chronicle"


def load_work(project):
    """Resolve --project to (root, work dir, manifest); fail with a next step if extract has not run."""
    root = repo_root(project)
    wd = work_dir(root)
    manifest = read_json(wd / "manifest.json")
    if not manifest:
        fail(f"no extract for {root}. Run: uv run scripts/extract.py --project {root}")
    return root, wd, manifest


# ---------------------------------------------------------------- evidence ids

def short_id(session_id):
    """'codex:01a11125-b3c5-...' -> '01a11125'; 'agent-a7ad9b90...' -> 'a7ad9b90'."""
    s = session_id.split(":")[-1].removeprefix("agent-")
    return s.replace("-", "")[:8]


# ---------------------------------------------------------------- prompt cleanup

# Blocks the harness injects into user turns; they are not what the human typed.
INJECTED = re.compile(
    r"<(system-reminder|browser_instruction|ide_selection|ide_opened_file|ide_diagnostics|"
    r"local-command-stdout|local-command-stderr|local-command-caveat|command-message|"
    r"user-prompt-submit-hook|environment_context|user_instructions|permissions instructions|"
    r"external_[a-z_]+)(?:\s[^>]*)?>.*?</\1>",
    re.S,
)
AUTOMATED_PREFIXES = ("<task-notification", "<agent-message", "<cross-session-message", "<teammate-message")


def classify_user(text):
    """Return (kind, cleaned_text) for a user-role message.

    kind: user_prompt (typed by the human), slash_command, interrupt, or meta
    (injected/automated content that is not the human's words).
    """
    t = (text or "").lstrip()
    if t.startswith(AUTOMATED_PREFIXES):
        return "meta", ""
    if t.startswith("[Request interrupted by user") or "<turn_aborted>" in t[:200]:
        return "interrupt", ""
    m = re.search(r"<command-name>(.*?)</command-name>", t, re.S)
    if m:
        args = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
        return "slash_command", f"{m.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    if re.match(r"/[a-z][\w:.-]*(\s|$)", t) and "\n" not in t.strip() and len(t) < 300:
        return "slash_command", t.strip()
    cleaned = INJECTED.sub("", t).strip()
    if not cleaned or cleaned.startswith("Caveat: The messages below were generated"):
        return "meta", ""
    return "user_prompt", cleaned


# ---------------------------------------------------------------- redaction

REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\b(?:sk|pk|rk)-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED JWT]"),
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY)[A-Z0-9_]*)(\s*[=:]\s*)"
                r"(?!\[REDACTED)['\"]?[^\s'\"]{8,}['\"]?"), r"\1\2[REDACTED]"),
]


def redact(text):
    if not text:
        return text
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def clip(text, n):
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def clip_middle(text, n):
    """Keep the head and the tail: long prompts often paste context first and ask at the end."""
    text = text or ""
    if len(text) <= n:
        return text
    head = (2 * n) // 3
    return text[:head].rstrip() + " … " + text[-(n - head - 3):].lstrip()
