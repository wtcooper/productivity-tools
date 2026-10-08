#!/usr/bin/env python3
"""Generate the four vendor marketplace catalogs from plugins/*/plugin.json.

Source of truth is each plugin's root `plugin.json` (Agent Plugins 1.0 manifest).
Vendor-specific catalog fields come from `extensions` in that manifest, e.g.
`extensions["com.openai.codex"].category`.

Usage:
    python3 scripts/build_marketplaces.py           # write catalogs
    python3 scripts/build_marketplaces.py --check   # fail if catalogs or manifests are stale/inconsistent
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"

MARKETPLACE_NAME = "productivity-tools"
DISPLAY_NAME = "Productivity Tools"
DESCRIPTION = "Skills, agents, and hooks for everyday productivity work: documents, presentations, and templates driven by your own assets, and the story of how your coding agents built a project."
OWNER = {"name": "Wade Cooper", "url": "https://github.com/wtcooper"}
REPO_URL = "https://github.com/wtcooper/productivity-tools"

AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
ALLOWED_ROOT_KEYS = {"$schema", "name", "version", "description", "author", "homepage",
                     "repository", "license", "keywords", "extensions"}
VENDOR_MANIFESTS = [".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json"]

OUTPUTS = {
    "claude": ROOT / ".claude-plugin" / "marketplace.json",
    "copilot": ROOT / ".github" / "plugin" / "marketplace.json",
    "codex": ROOT / ".agents" / "plugins" / "marketplace.json",
    "cursor": ROOT / ".cursor-plugin" / "marketplace.json",
}


def fail(msg):
    sys.exit(f"error: {msg}")


def load_json(path):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")


def validate_root_manifest(path, manifest):
    rel = path.relative_to(ROOT)
    if manifest.get("$schema") != AGENT_PLUGINS_SCHEMA:
        fail(f"{rel}: $schema must be {AGENT_PLUGINS_SCHEMA}")
    name = manifest.get("name", "")
    if not (1 <= len(name) <= 64 and NAME_RE.match(name)):
        fail(f"{rel}: invalid plugin name {name!r}")
    if name != path.parent.name:
        fail(f"{rel}: name {name!r} must match directory {path.parent.name!r}")
    extra = set(manifest) - ALLOWED_ROOT_KEYS
    if extra:
        fail(f"{rel}: keys not allowed by Agent Plugins 1.0: {sorted(extra)}")
    for key in ("version", "description"):
        if not manifest.get(key):
            fail(f"{rel}: {key} is required by this marketplace")


def validate_vendor_manifests(plugin_dir, root):
    for rel_path in VENDOR_MANIFESTS:
        path = plugin_dir / rel_path
        if not path.exists():
            fail(f"{plugin_dir.name}: missing {rel_path}")
        vendor = load_json(path)
        for key in ("name", "version", "description"):
            if vendor.get(key) != root.get(key):
                fail(f"{path.relative_to(ROOT)}: {key} differs from plugin.json")


def validate_skills(plugin_dir):
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        fail(f"{plugin_dir.name}: skills/ directory is required")
    for skill in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill / "SKILL.md"
        if not skill_md.exists():
            fail(f"{skill.relative_to(ROOT)}: missing SKILL.md")
        text = skill_md.read_text()
        match = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
        if not match or match.group(1) != skill.name:
            fail(f"{skill_md.relative_to(ROOT)}: frontmatter name must equal directory name {skill.name!r}")
        if not re.search(r"^description:\s*\S", text, re.MULTILINE):
            fail(f"{skill_md.relative_to(ROOT)}: frontmatter description is required")


def collect_plugins():
    plugins = []
    for manifest_path in sorted(PLUGINS_DIR.glob("*/plugin.json")):
        manifest = load_json(manifest_path)
        validate_root_manifest(manifest_path, manifest)
        validate_vendor_manifests(manifest_path.parent, manifest)
        validate_skills(manifest_path.parent)
        plugins.append(manifest)
    if not plugins:
        fail("no plugins found under plugins/*/plugin.json")
    return plugins


def common_entry(p):
    entry = {"name": p["name"], "description": p["description"], "version": p["version"]}
    for key in ("author", "homepage", "repository", "license", "keywords"):
        if key in p:
            entry[key] = p[key]
    return entry


def build_claude(plugins):
    return {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": MARKETPLACE_NAME,
        "owner": OWNER,
        "metadata": {"description": DESCRIPTION, "version": "1.0.0"},
        "plugins": [
            {**common_entry(p), "source": f"./plugins/{p['name']}",
             "category": p.get("extensions", {}).get("com.anthropic.claude", {}).get("category", "productivity")}
            for p in plugins
        ],
    }


def build_copilot(plugins):
    return {
        "name": MARKETPLACE_NAME,
        "owner": OWNER,
        "metadata": {"description": DESCRIPTION, "version": "1.0.0"},
        "plugins": [{**common_entry(p), "source": f"./plugins/{p['name']}"} for p in plugins],
    }


def build_codex(plugins):
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": DISPLAY_NAME},
        "plugins": [
            {
                "name": p["name"],
                "source": {"source": "local", "path": f"./plugins/{p['name']}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": p.get("extensions", {}).get("com.openai.codex", {}).get("category", "Productivity"),
            }
            for p in plugins
        ],
    }


def build_cursor(plugins):
    return {
        "name": MARKETPLACE_NAME,
        "owner": {"name": OWNER["name"]},
        "metadata": {"description": DESCRIPTION},
        "plugins": [{**common_entry(p), "source": f"plugins/{p['name']}"} for p in plugins],
    }


BUILDERS = {"claude": build_claude, "copilot": build_copilot, "codex": build_codex, "cursor": build_cursor}


def main():
    check = "--check" in sys.argv[1:]
    plugins = collect_plugins()
    stale = []
    for vendor, path in OUTPUTS.items():
        rendered = json.dumps(BUILDERS[vendor](plugins), indent=2) + "\n"
        if check:
            if not path.exists() or path.read_text() != rendered:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        fail("stale catalogs (run scripts/build_marketplaces.py): " + ", ".join(stale))
    if check:
        print(f"OK: {len(plugins)} plugin(s), 4 catalogs in sync")


if __name__ == "__main__":
    main()
