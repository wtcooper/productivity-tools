# Mapping content to layouts

## Outline syntax (`fill_layout.py`)

One `## ` heading per slide. Attributes go in braces at the end of the heading.

```md
## Q3 Highlights {layout=three_column icons="growth,security,cost" icon_color=primary}
### Growth
- Revenue up **14%** year on year
  - Sub-bullet (two spaces per level)
### Security
- Zero critical findings
### Cost
Plain lines become unbulleted paragraphs.

Notes: Everything after "Notes:" becomes speaker notes.
```

| Syntax | Meaning |
|---|---|
| `{layout=CLASS}` | A layout class, an exact layout name in quotes (`layout="Two Content"`), or `#index` from `catalog.md` |
| `{icons="tag,tag"}` | Catalog icons by tag, label word, or `#index`. See `icon-usage.md` |
| `{icon_color=ROLE}` | Tint recolorable icons to a color role or theme slot |
| `### Heading` | Starts a new block. Blocks fill content placeholders left to right |
| `---` | Starts a new block without a heading |
| `- item`, `1. item` | One paragraph per item; bullets and numbering style inherit from the layout |
| `**text**` | Bold run |
| `![alt](path.png)` or `![alt](asset:TAG)` | Picture: fills a picture placeholder (cropped to fill) or fits inside a content placeholder |
| Markdown table | Native table in the next content placeholder |
| ```` ```chart ```` fenced JSON | Native chart: `{"type", "title", "categories", "series": [{"name", "values"}]}`. Types: `column`, `stacked_column`, `bar`, `stacked_bar`, `line`, `area`, `pie`, `doughnut` |
| `Notes:` | Speaker notes to the end of the slide |

On `title`, `section`, and `closing` layouts the first text block goes to the subtitle.
On `comparison` layouts each block's `### Heading` goes to the column's small heading
placeholder. Placeholders left unused are deleted from the slide.

With no `layout=`, the first slide is `title` and the rest are chosen by block count
(one, two, three columns; image plus text; lone chart or table).

## Layout classes

`title`, `section`, `one_column`, `two_column`, `three_column`, `image_left`,
`image_right`, `full_bleed_image`, `chart`, `table`, `comparison`, `quote`, `closing`,
`title_only`, `blank`. `catalog.md` section 2 lists which the template has and what each
is for; section 5 lists the gaps.

## Choosing well

- Start from the content's shape: parallel points → columns; a contrast → comparison;
  one number or chart that carries the slide → chart or one_column with the chart alone;
  a change of topic → section.
- Vary layouts. Three identical title-and-bullets slides in a row is a signal to regroup
  the content, not a formatting problem.
- Respect capacity. `catalog.md` gives `lines x chars` per body placeholder. A single
  over-long list is continued on a "(cont.)" slide automatically; multi-column slides are
  not split, so `fill_layout.py` warns and you trim or restructure. Never solve overflow
  by shrinking text below what the template sets.
- Titles: one line where possible. Title capacity is in `layouts.json` (`capacity_chars`).
- Keep clear of `reserved_regions_in` (logos, bars) when placing anything by coordinates
  on the fallback path.

## Substitutions

When the template lacks a class, `fill_layout.py` uses the nearest one and prints a
warning (`three_column` → `two_column` → `one_column`; `chart`/`table` → `one_column`;
`closing` → `title`; `quote` → `section`). A third block on a two-column layout is
appended to the second column. Decide per slide whether the substitute is acceptable,
the content should be regrouped, or the slide belongs on the fallback path.

## Fallback slides

Build with pptxgenjs using `scripts/brand_pptxgenjs.js`, then merge:

```bash
node make_fallback.js                                   # writes fallback.pptx
uv run scripts/merge_slides.py deck.pptx fallback.pptx -o final.pptx --after 4
```

`--after N` inserts the fallback slides after slide N of the base deck. `--layout`
selects the destination layout (default `title_only`, else `blank`). Leave the title
band and reserved regions of that layout clear; the merged slide shows the master's
decoration underneath your shapes.
