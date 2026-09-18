# Productivity Tools

Plugins for everyday productivity work, packaged once in the open
[Agent Plugins 1.0](https://agent-plugins.org/) format and installable in
**Claude Code**, **OpenAI Codex**, **GitHub Copilot**, and **Cursor**.

This repository is a plugin marketplace. It ships one catalog per vendor, all
generated from the same `plugins/*/plugin.json` manifests, so every plugin here
installs with each vendor's native marketplace command.

## Plugins

| Plugin | What it does |
| --- | --- |
| [`doc-template-skills`](plugins/doc-template-skills/) | Document skills driven by your own templates. `pptx-brand` registers a PowerPoint brand template once (theme colors, fonts, slide-master layouts, icon catalog), builds decks from the template's real layouts, and fails QA on anything off-brand. Ships `template-onboarder`, `deck-builder`, and `visual-qa` subagents. |

## Install

Every command below uses the first plugin, `doc-template-skills`. Substitute any
plugin name from the table above.

### Claude Code

**Terminal (user scope, all projects):**

```bash
claude plugin marketplace add wtcooper/productivity-tools
claude plugin install doc-template-skills@productivity-tools
```

**Inside a session:** run `/plugin marketplace add wtcooper/productivity-tools`,
then `/plugin install doc-template-skills@productivity-tools`. The `/plugin`
menu also lets you browse, enable, disable, and uninstall.

**Project scope (shared with your team):** add `--scope project` to both commands.
Claude Code writes the marketplace and plugin into `.claude/settings.json`; commit
that file and teammates get prompted to install on their next session.

**Verify:** `claude plugin list` shows `doc-template-skills@productivity-tools`
as enabled. In a session, `/doc-template-skills:pptx-brand` invokes the skill
directly, or just ask for an on-brand deck from your template and Claude picks it up.

**Update:** `claude plugin marketplace update productivity-tools` then
`claude plugin update doc-template-skills@productivity-tools`. Restart the session.

**Uninstall:** `claude plugin uninstall doc-template-skills@productivity-tools`.
Remove the catalog with `claude plugin marketplace remove productivity-tools`.

**Try without installing:** `claude --plugin-dir path/to/plugins/doc-template-skills`
from a checkout of this repo.

### OpenAI Codex

**Terminal (CLI, desktop app, and VS Code extension share the install):**

```bash
codex plugin marketplace add wtcooper/productivity-tools
codex plugin add doc-template-skills@productivity-tools
```

**Inside Codex:** type `/plugins` to open the plugin browser, switch to the
**Productivity Tools** marketplace tab, select the plugin, and press Install.
Once the marketplace is added from the CLI it appears in the desktop app and the
VS Code extension too.

**Verify:** `codex plugin list` shows `doc-template-skills@productivity-tools`.
In a session, `/skills` lists `doc-template-skills:pptx-brand`.

**Update:** `codex plugin marketplace upgrade` refreshes the catalog snapshot;
then run `codex plugin add doc-template-skills@productivity-tools` again to pick
up a new version.

**Uninstall:** `codex plugin remove doc-template-skills@productivity-tools`.
Remove the catalog with `codex plugin marketplace remove productivity-tools`.

**Pin a ref:** `codex plugin marketplace add wtcooper/productivity-tools --ref v0.1.0`
installs from a tag instead of the default branch.

### GitHub Copilot

**Terminal (CLI):**

```bash
copilot plugin marketplace add wtcooper/productivity-tools
copilot plugin install doc-template-skills@productivity-tools
```

**Inside a session:** `/plugin marketplace add wtcooper/productivity-tools`,
then `/plugin install doc-template-skills@productivity-tools`.
`/plugin marketplace browse productivity-tools` lists what is available.

**VS Code and the Copilot app:** plugins installed by the CLI land in
`~/.copilot/installed-plugins/` and show up automatically. To install from VS
Code instead, open the Command Palette and run
**Chat: Install Plugin From Source** with
`https://github.com/wtcooper/productivity-tools`, or search `@agentPlugins` in
the Extensions view once the marketplace is registered.

**Declarative install (dotfiles, CI images):** add to `~/.copilot/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "productivity-tools": {
      "source": { "source": "github", "repo": "wtcooper/productivity-tools" }
    }
  },
  "enabledPlugins": { "doc-template-skills@productivity-tools": true }
}
```

**Enterprise:** put the same `extraKnownMarketplaces` block in your
organization's `.github-private/.github/copilot/settings.json` to preload the
marketplace for every Copilot CLI user.

**Verify:** `copilot plugin list` shows the plugin. In a session, `/skills list`
shows `pptx-brand`, and `/agent` lists `doc-template-skills:template-onboarder`,
`doc-template-skills:deck-builder`, and `doc-template-skills:visual-qa`.

**Update:** `copilot plugin update doc-template-skills`.

**Uninstall:** `copilot plugin uninstall doc-template-skills`, then
`copilot plugin marketplace remove productivity-tools` if you no longer want the catalog.

**Direct install (deprecated by the CLI, still works):**
`copilot plugin install wtcooper/productivity-tools:plugins/doc-template-skills`.

**Try without installing:** `copilot --plugin-dir path/to/plugins/doc-template-skills`.

### Cursor

Cursor installs plugins from the editor or the team dashboard. The `agent` CLI
can register a marketplace but does not install from it.

**Team marketplace (recommended for teams):**

1. Open the Cursor Dashboard → **Plugins** → **Add Marketplace**.
2. Choose **Import from Repo** and enter `https://github.com/wtcooper/productivity-tools`.
3. Set **Marketplace Access** for your team and turn on **Auto Refresh** so pushes to
   `main` update the plugin (requires the Cursor GitHub App).
4. In the editor, open **Customize → Plugins**, find `doc-template-skills`, and
   click **Install**, choosing user or project scope.

**Register the marketplace from the CLI:**

```bash
agent plugin marketplace add https://github.com/wtcooper/productivity-tools
```

Then install from **Customize → Plugins** in the editor, or `/plugin` in the CLI.

**Local plugin, no marketplace:**

```bash
git clone https://github.com/wtcooper/productivity-tools
mkdir -p ~/.cursor/plugins/local
ln -s "$PWD/productivity-tools/plugins/doc-template-skills" ~/.cursor/plugins/local/doc-template-skills
```

Restart Cursor or run **Developer: Reload Window**. `git pull` in the clone
updates the plugin in place.

**One session from the CLI:** `agent --plugin-dir path/to/plugins/doc-template-skills`.

**Verify:** in the editor or CLI, `/skills` lists `pptx-brand` and the
`template-onboarder`, `deck-builder`, and `visual-qa` subagents appear under
**Customize → Agents**.

**Uninstall:** **Customize → Plugins → Uninstall**, or remove the symlink.

### Any other Agent Plugins 1.0 client

Point the client at `plugins/<name>/`. The root `plugin.json`, `skills/`, and
(where present) `mcp.json` follow the spec; vendor-only extras live in
`com.<vendor>.<client>/` folders and vendor manifests that other clients ignore.
In VS Code, the `chat.pluginLocations` setting accepts a local plugin path.

## Local development

```bash
git clone https://github.com/wtcooper/productivity-tools && cd productivity-tools

# Load a plugin for one session without installing it
claude --plugin-dir plugins/doc-template-skills
copilot --plugin-dir plugins/doc-template-skills
agent --plugin-dir plugins/doc-template-skills

# Or register the checkout as a local marketplace
claude plugin marketplace add .
codex plugin marketplace add .
copilot plugin marketplace add "$PWD"
```

Validate before you commit:

```bash
python3 scripts/build_marketplaces.py --check   # manifests and catalogs agree
claude plugin validate .                         # Claude Code marketplace + plugins
```

## Repository layout

```
.claude-plugin/marketplace.json   # Claude Code catalog        (generated)
.github/plugin/marketplace.json   # GitHub Copilot catalog     (generated)
.agents/plugins/marketplace.json  # OpenAI Codex catalog       (generated)
.cursor-plugin/marketplace.json   # Cursor catalog             (generated)
plugins/<name>/                   # one directory per plugin, see docs/plugin-layout.md
scripts/build_marketplaces.py     # regenerates the catalogs and checks consistency
```

See [docs/plugin-layout.md](docs/plugin-layout.md) for the per-plugin layout
and how to add a new plugin.

## License

MIT. See [LICENSE](LICENSE).
