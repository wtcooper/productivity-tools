# doc-template-skills

Document skills that are driven by *your* templates instead of a model's taste.

The first skill, **`pptx-brand`**, makes PowerPoint decks from a corporate template.
You register the template once. After that every deck is built from the template's real
slide layouts, painted only with its theme colors and fonts, illustrated from its own
icon library, and checked by a script that fails on anything off-brand.

Works in Claude Code, OpenAI Codex, GitHub Copilot, Cursor, and any Agent Plugins 1.0
client. Install instructions are in the [repository README](../../README.md#install);
substitute `doc-template-skills` for the plugin name.

## Why

Generic deck skills pick a "bold, content-informed" palette and a fresh visual motif for
each deck. That is right for a one-off and wrong for a company with a brand system, where
the usual failure is a deck in nearly-the-right blue with text boxes drawn over the
template's artwork. `pptx-brand` fixes the inputs:

- **Brand tokens are data.** Colors, fonts, and slide size are read from the theme XML
  into `brand.json`; nobody types a hex value.
- **Slide masters first.** Slides are instantiated from the template's layouts and their
  placeholders are filled, so the logo, footer, and typography are inherited and the deck
  stays editable by people.
- **A catalog the model can see.** Every layout, icon, and graphic gets a labeled
  thumbnail and a row in `catalog.md`.
- **QA is computed.** `brand_qa.py` fails on off-brand colors and fonts, images that
  bypass the catalog, slides on a stray master, and leftover placeholders.

## Requirements

| Need | For |
|---|---|
| Python 3.10+ and [`uv`](https://docs.astral.sh/uv/) (or `pip install python-pptx Pillow lxml defusedxml`) | Everything |
| LibreOffice (`soffice`) and Poppler (`pdftoppm`) | Thumbnails, vector-icon previews, visual QA. Optional: onboard with `--no-render` |
| Node.js and `npm install pptxgenjs` | Only for bespoke fallback slides |
| Anthropic's official `pptx` skill | Recommended: adds its `validate.py` file check and its authoring guidance |

### About the official `pptx` skill

`pptx-brand` is designed as an add-on to Anthropic's `pptx` document skill. That skill is
proprietary: its license forbids copying, redistribution, and derivative works, so **none
of it is included in this repository**. `pptx-brand` finds it where you installed it and
calls it in place. In Claude Code:

```
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills
```

Or set `PPTX_SKILL_DIR` to its directory. Without it, everything works except the `file`
check in QA, which is reported as skipped.

## Onboard a template (about 10 minutes)

Ask in plain language: *"Register `Acme-Corporate-2026.potx` as our brand template. Icons
are in `~/brand/icons` and there is an icon deck at `~/brand/Acme-Icons.pptx`."*

What happens:

1. `onboard_template.py` copies the template to `~/.pptx-brand/templates/<name>/` and
   writes `brand.json` (12 theme colors, heading/body fonts, slide size, custom colors),
   `layouts.json` (every layout's placeholders, inch geometry, text capacity, reserved
   regions, and a class such as `two_column` or `section`), `assets.json` (template
   media, your icon and graphics folders, and shapes lifted from icon decks), contact
   sheets under `thumbs/`, and `catalog.md`.
2. The agent looks at the contact sheets, corrects any misclassified layout, and writes a
   short label and tags for every icon.
3. It asks you **once** to confirm which theme colors are primary, secondary, and
   highlight.
4. It rebuilds `catalog.md`. Done: the template is registered until its next version.

By hand:

```bash
cd plugins/doc-template-skills/skills/pptx-brand
uv run scripts/onboard_template.py ~/brand/Acme-Corporate-2026.potx \
    --icons ~/brand/icons --icon-deck ~/brand/Acme-Icons.pptx --default
uv run scripts/onboard_template.py --list
```

Rules the file cannot express go in `--overrides brand-overrides.json`:

```json
{"dont": ["use accent 5", "place anything over the bottom-left logo"],
 "do": ["end every deck on the Closing layout"],
 "extra_colors": ["1A1A1A"]}
```

## Build a deck

Ask: *"Make an on-brand leadership deck from these notes."* Or by hand:

```bash
uv run scripts/fill_layout.py outline.md -o deck.pptx     # build from template layouts
uv run scripts/brand_qa.py deck.pptx                      # must pass
uv run scripts/render_deck.py deck.pptx renders/          # images for visual QA
```

```md
## Q3 Highlights {layout=three_column icons="growth,security,cost" icon_color=primary}
### Growth
- Revenue up **14%** year on year
```

The outline format (columns, comparison, pictures, native charts and tables, speaker
notes) is in [`references/layout-mapping.md`](skills/pptx-brand/references/layout-mapping.md).
For a visual the template has no layout for, the skill draws the slide with pptxgenjs
using only brand tokens, then `merge_slides.py` moves it onto the template's title-only
layout so it still carries the master's logo and footer.

## Contents

- `skills/pptx-brand/SKILL.md` — the procedure
- `skills/pptx-brand/references/` — brand override, layout mapping, icon usage
- `skills/pptx-brand/scripts/` — onboarding (`onboard_template.py`, `extract_theme.py`,
  `profile_layouts.py`, `harvest_assets.py`, `build_catalog.py`), building
  (`fill_layout.py`, `brand_pptxgenjs.js`, `merge_slides.py`), QA (`brand_qa.py`,
  `render_deck.py`), and `find_upstream.py`
- `agents/` — `template-onboarder`, `deck-builder`, `visual-qa` subagents (Claude Code, Cursor)
- `com.github.copilot/agents/` — the same subagents in Copilot's `.agent.md` format

Test: `uv run tests/pptx_brand/run_e2e.py --render` from the repository root (omit
`--render` on a machine without LibreOffice).

## Troubleshooting

**The deck looks flat even though it used my template.** The "template" is probably an
example deck: its artwork sits on slides, not on slide layouts, so there is nothing to
inherit. Onboarding warns about this. Open the file in PowerPoint, go to View → Slide
Master, move the artwork onto layouts (and turn text boxes into placeholders), save, and
onboard again.

**A layout was classified wrongly.** Edit `class` for that row in `layouts.json`, set
`"edited": true`, and run `build_catalog.py <template-dir>`. Edited rows survive
re-onboarding.

**`fill_layout.py` says "template has no 'three_column' layout".** That is a coverage gap.
Accept the substitute, regroup the content, add such a layout to the template, or build
that slide on the fallback path.

**Text overflows in the preview but not in PowerPoint (or the reverse).** LibreOffice
substitutes fonts it does not have. `brand.json` → `font_safety` records whether your
brand fonts preview reliably; when they do not, trust the capacity numbers and check the
file in PowerPoint.

**No thumbnails were produced.** LibreOffice or Poppler is missing. On macOS:
`brew install --cask libreoffice && brew install poppler`. Then re-run onboarding.

**SVG/EMF icons look soft when enlarged.** python-pptx cannot embed vector files, so
they are placed as a 256 px preview. Keep them at icon size, or supply the icons as a
PowerPoint icon deck (`--icon-deck`): those are cloned as true vector shapes.

**Brand QA flags a color I consider on-brand.** Add it to `extra_colors` in your
overrides file and re-onboard, or fix the generator so it uses a brand token.

**Brand QA flags an image.** Use a catalog asset if one fits. If the image is legitimate
and not in the catalog, pass `--allow-image path`.

**Where are my templates? Will a plugin update delete them?** `~/.pptx-brand/templates/`
(or `$PPTX_BRAND_HOME`). They live outside the plugin, so no.

**A new version of the template arrived.** Onboard it under the same `--name`. Confirmed
color roles, edited layout rows, and icon labels (matched by file hash) are kept.

## Known limits

- Promoting example slides to layouts is detected and explained, not automated.
- Continuation slides are created for a single over-long list; multi-column overflow is
  reported for you to fix.
- `merge_slides.py` copies shapes, pictures, and native charts. SmartArt, video, and
  embedded OLE objects on fallback slides are not supported.

## Provenance

Built from the plan "Template-Aware Hybrid of the Anthropic `pptx` Skill". Ideas borrowed
from [`tristan-mcinnis/pptx-from-layouts-skill`](https://github.com/tristan-mcinnis/pptx-from-layouts-skill)
(layouts first, three subagents), [`anyideaz/pptx-skills`](https://github.com/anyideaz/pptx-skills)
(analyze once, generate many), and [`tfriedel/claude-office-skills`](https://github.com/tfriedel/claude-office-skills)
(thumbnail-grid validation). No code from those projects or from Anthropic's skill is included.
