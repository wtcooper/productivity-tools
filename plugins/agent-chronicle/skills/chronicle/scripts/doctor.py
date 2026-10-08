#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check that agent-chronicle can see your history, and print the fix for anything that is off.

    uv run scripts/doctor.py

Exit 1 only when a run cannot work (agentsview missing or too old).
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import archive  # noqa: E402
import source_agentsview as av  # noqa: E402
from _common import HOME  # noqa: E402


def main():
    rows, blocking = [], False

    v = av.version()
    if v is None:
        rows.append(("FAIL", "agentsview", f"not installed. {av.INSTALL_HINT}"))
        blocking = True
    elif v < av.MIN_VERSION:
        rows.append(("FAIL", "agentsview", f"v{'.'.join(map(str, v))} is older than "
                     f"v{'.'.join(map(str, av.MIN_VERSION))}. Upgrade: `brew upgrade --cask agentsview`."))
        blocking = True
    else:
        p = subprocess.run(["agentsview", "session", "list", "--json", "--limit", "1", "--include-children",
                            "--include-one-shot", "--include-automated"], capture_output=True, text=True)
        try:
            total = json.loads(p.stdout[p.stdout.find("{"):]).get("total", 0)
        except ValueError:
            total = 0
        status = "OK" if total else "WARN"
        rows.append((status, "agentsview", f"v{'.'.join(map(str, v))}, {total} sessions indexed"
                     + ("" if total else ". Run `agentsview sync`.")))

    # agentsview never prunes on its own and keeps sessions whose source file is gone; check nothing narrows what it stores.
    config = Path(os.environ.get("AGENTSVIEW_DATA_DIR", "~/.agentsview")).expanduser() / "config.toml"
    text = config.read_text() if config.exists() else ""
    m = re.search(r'^\s*archive_content\s*=\s*"([^"]+)"', text, re.M)
    if m and m.group(1) != "full":
        rows.append(("WARN", "agentsview storage", f'archive_content = "{m.group(1)}" in {config} drops tool inputs and '
                     'results that the chronicle uses. Set it to "full" (the default) and run `agentsview daemon restart`.'))
    else:
        rows.append(("OK", "agentsview storage", 'archive_content = "full"; sessions are kept after their source file '
                     "is deleted, with no automatic pruning (only `agentsview prune` deletes)"))

    st = archive.status()
    if st["files"]:
        rows.append(("OK", "raw-source archive", f"{st['files']} files, {st['mb']} MB, last updated {st['last'][:16]} UTC; "
                     f"{st['preserved']} kept after their source was deleted ({archive.ARCHIVE})"))
    else:
        rows.append(("WARN", "raw-source archive", f"empty. Run `python3 scripts/archive.py` (extract.py also runs it) to keep "
                     f"local copies of every raw transcript in {archive.ARCHIVE}."))

    settings = Path("~/.claude/settings.json").expanduser()
    days = None
    if settings.exists():
        try:
            days = json.loads(settings.read_text()).get("cleanupPeriodDays")
        except ValueError:
            pass
    if days is None or days < 90:
        rows.append(("WARN", "Claude Code retention",
                     f"cleanupPeriodDays is {days if days is not None else 'unset (30)'}: Claude Code deletes transcripts "
                     "older than that. agentsview and the archive keep copies only of what they saw first, so they "
                     "must run inside that window (this plugin's SessionEnd hook does). To keep originals in place too, "
                     f"add \"cleanupPeriodDays\": 3650 to {settings}."))
    else:
        rows.append(("OK", "Claude Code retention", f"cleanupPeriodDays = {days}"))

    for tool, why in (("git", "commit history"), ("uv", "running the scripts")):
        rows.append(("OK" if shutil.which(tool) else "WARN", tool, "found" if shutil.which(tool) else f"not found; needed for {why}"))

    rows.append(("OK", "data dir", f"{HOME} (set AGENT_CHRONICLE_HOME to move it)"))

    width = max(len(r[1]) for r in rows)
    for status, name, detail in rows:
        print(f"{status:4}  {name:<{width}}  {detail}")
    sys.exit(1 if blocking else 0)


if __name__ == "__main__":
    main()
