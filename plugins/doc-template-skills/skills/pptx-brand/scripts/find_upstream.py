#!/usr/bin/env python3
"""Locate the official Anthropic `pptx` skill (standard library only).

Usage:
    find_upstream.py        # prints the skill directory, or exits 1 with install help

That skill is proprietary, so it is used where it is installed and never bundled here.
Set PPTX_SKILL_DIR to point at it explicitly.
"""

import os
import sys
from pathlib import Path

INSTALL_HELP = """official pptx skill not found. Install it, or set PPTX_SKILL_DIR to its directory:
  Claude Code:  /plugin marketplace add anthropics/skills
                /plugin install document-skills@anthropic-agent-skills
  claude.ai:    already present at /mnt/skills/public/pptx
Without it, brand_qa.py skips the `file` (validate.py) check; everything else works."""


def find_upstream():
    home = Path.home()
    candidates = [Path(os.environ["PPTX_SKILL_DIR"])] if os.environ.get("PPTX_SKILL_DIR") else []
    candidates += [Path("/mnt/skills/public/pptx"), Path.cwd() / ".claude/skills/pptx", home / ".claude/skills/pptx"]
    for base in (home / ".claude/plugins", home / ".copilot/installed-plugins", home / ".codex", home / ".cursor"):
        if base.is_dir():
            candidates += sorted(base.glob("**/skills/pptx"))
    for path in candidates:
        if (path / "SKILL.md").is_file() and (path / "scripts/office/validate.py").is_file():
            return path
    return None


if __name__ == "__main__":
    found = find_upstream()
    if found is None:
        sys.exit(INSTALL_HELP)
    print(found)
