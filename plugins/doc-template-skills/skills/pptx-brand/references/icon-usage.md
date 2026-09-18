# Using catalog icons and graphics

## The rule

If the catalog has an asset that fits, use it. Generic icon sets (react-icons and the
like) are a last resort for concepts the catalog truly lacks, and `brand_qa.py` flags any
image that did not come from the catalog or the outline. Record what you used: the
builder writes `Brand catalog assets: #12 shield with checkmark` into the speaker notes
so a designer can audit the deck.

## Finding an asset

`catalog.md` section 3 lists icons as `# | label | tags`, or as a tag index when the
library is large; the contact sheets `thumbs/icons-N.jpg` and `thumbs/graphics-N.jpg`
show every asset with its `#index`. Look at the sheet before choosing: labels are short,
and the right icon for "resilience" may be labeled "shield".

Queries match, in order of strength: exact tag, a word of the label, a substring of the
label. `#12` or `12` selects by index. An unmatched query is reported as an unresolved
icon; pick another tag or index rather than leaving the slot empty.

## Template layouts (`fill_layout.py`)

```md
## Pillars {layout=three_column icons="growth,security,#31" icon_color=primary}
```

- Icons go first into unused picture placeholders; otherwise one icon sits at the top
  left of each column (0.6 in) and that column's text moves down to make room.
- The n-th icon belongs to the n-th column. More icons than columns is reported.
- `icon_color` tints only assets marked recolorable (single-color art on transparency).
  Multi-color icons and logos keep their native colors. Never recolor a logo.
- `![alt](asset:TAG)` places a catalog graphic or photo as a picture block.

## Formats

| Format | How it is placed |
|---|---|
| PNG, JPG, GIF | Embedded as is |
| SVG, EMF, WMF | Embedded as the PNG preview rendered at onboarding (python-pptx cannot embed vector files). Fine at icon size; do not enlarge past about 1.5 in |
| `shape` | A vector shape or group harvested from an icon-library deck. Cloned as native, editable PowerPoint shapes, scaled into place. Not tinted |

To reuse art that lives on a layout or master (a watermark, a corner graphic), choose a
layout that already contains it; `assets.json` → `used_by` says which. Do not re-insert it.

## Fallback slides (pptxgenjs)

```js
const icon = brand.icon("security");            // { index, label, path } or null
if (icon) slide.addImage({ path: icon.path, x: 1, y: 2, w: 0.6, h: 0.6 });
slide.addNotes(`Brand catalog assets: #${icon.index} ${icon.label}`);
```

Only when `brand.icon()` returns null may a generic icon be rendered, recolored to a brand
token via `brand.color("primary")`. Then pass the rendered file to
`brand_qa.py --allow-image` and say in your report that the catalog had no match.

## Contrast and size

Icons need the same contrast as text. On a dark layout use a light or `text_on_dark`
tint; on light, `primary` or `text_on_light`. Keep one size per slide and one tint per
deck section.
