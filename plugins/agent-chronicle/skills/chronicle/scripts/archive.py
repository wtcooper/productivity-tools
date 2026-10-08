#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Keep a compressed local copy of every raw session file agentsview indexes, indefinitely.

    python3 scripts/archive.py [--quiet]

agentsview's database keeps parsed sessions forever (it has no automatic pruning, and sessions survive their source
file's deletion), but it does not keep the raw files. Agents delete those: Claude Code after
`cleanupPeriodDays` (30 by default), Gemini CLI after 30 days. This archive keeps them, so a session
can be re-parsed later for anything the index did not capture (`gunzip -k` a copy, then
`agentsview session sync <file>`). Files are only added or refreshed, never removed.

Local only: $AGENT_CHRONICLE_HOME/archive/ (default ~/.agent-chronicle/archive), never inside a project.
The plugin's SessionEnd hook runs this after `agentsview sync`; extract.py runs it too.
"""

import argparse
import fcntl
import gzip
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import source_agentsview as av  # noqa: E402
from _common import ARCHIVE, now_iso, read_json, write_json  # noqa: E402

SKIP_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".vscdb"}  # shared databases, not per-session files


def run(quiet=False):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    lock = open(ARCHIVE / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None  # another run (e.g. a parallel SessionEnd hook) is archiving
    index_path = ARCHIVE / "index.json"
    index = read_json(index_path, {})
    added = refreshed = 0
    for s in av.list_sessions(include_automated=True, include_source=True):
        src = s.get("file_path")
        if not src or Path(src).suffix in SKIP_SUFFIXES or not os.path.isfile(src):
            continue
        st = os.stat(src)
        rec = index.get(src)
        if rec and rec["size"] == st.st_size and rec["mtime"] == st.st_mtime:
            continue
        dest = ARCHIVE / "files" / (src.lstrip("/") + ".gz")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        with open(src, "rb") as fin, gzip.open(tmp, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        tmp.replace(dest)
        added, refreshed = (added + 1, refreshed) if rec is None else (added, refreshed + 1)
        index[src] = {"size": st.st_size, "mtime": st.st_mtime, "archived_at": now_iso(),
                      "agent": s.get("agent"), "session": s.get("id"), "archive": str(dest.relative_to(ARCHIVE))}
    write_json(index_path, index)
    summary = status(index)
    summary.update(added=added, refreshed=refreshed)
    if not quiet:
        print(f"archive: {added} new, {refreshed} refreshed · {summary['files']} files, {summary['mb']} MB · "
              f"{summary['preserved']} kept after their source was deleted · {ARCHIVE}")
    return summary


def status(index=None):
    index = read_json(ARCHIVE / "index.json", {}) if index is None else index
    size = sum((ARCHIVE / r["archive"]).stat().st_size for r in index.values() if (ARCHIVE / r["archive"]).exists())
    return {"files": len(index), "mb": round(size / 1e6, 1),
            "preserved": sum(1 for src in index if not os.path.exists(src)),
            "last": max((r["archived_at"] for r in index.values()), default=None)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    run(args.quiet)


if __name__ == "__main__":
    main()
