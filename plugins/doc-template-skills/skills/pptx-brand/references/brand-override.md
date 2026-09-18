# Brand override

When a registered template is in use, this file replaces the design-direction guidance
of any generic deck skill, including the official `pptx` skill's "Before Starting" and
"Color Palettes" sections. Everything else in that skill (pptxgenjs gotchas, editing
rules, typography sizes, spacing, its "Avoid" list, QA) still applies.

## What is fixed

- **Palette.** Only the colors in `brand.json`: the 12 theme slots, the template's custom
  colors, and `overrides.extra_colors`. Do not pick a topic-specific palette, and do not
  use a generic skill's palette table. Refer to colors by role (`primary`, `secondary`,
  `highlight`, `text_on_dark`, `text_on_light`), not by eye.
- **Fonts.** Heading = `fonts.major_latin`, body = `fonts.minor_latin`. On template
  layouts, set no font at all: placeholders inherit it. On fallback slides, take fonts
  from `brand_pptxgenjs.js`.
- **Slide size.** `slide_size_in`. A fallback deck with a different canvas cannot be merged.
- **Layouts.** The template's slide layouts. A slide type the template lacks is a
  coverage gap to substitute or build on the fallback path, not a reason to restyle.

## What you still decide

- **Which layout per slide**, and variety across the deck. Do not put every section on
  the same title-and-bullets layout when the template offers columns, comparison,
  picture, and section layouts.
- **Color weight.** One role dominates; `highlight` is for the one thing per slide that
  must be seen. Equal weight for every accent reads as noise even when each is on-brand.
- **Visual motif = the template's.** Identify it from the layout thumbnails during
  onboarding (corner shape, image treatment, how icons are framed) and record it in
  `brand.json` as `motif`. Repeat that; do not introduce a second motif.
- **Dark/light rhythm.** Open and close on dark layouts only if the template has dark
  layouts. If it is light throughout, stay light.
- **A visual on every content slide**: a catalog icon, a native chart, a table, or a
  catalog graphic. Text-only slides are the exception.

## Charts

Series colors follow `color_roles.chart_series_order`. `fill_layout.py` writes them as
theme references, so they track the template. On the fallback path use `brand.chart()`.
Keep charts native; never paste a chart as an image.

## Do / don't from the brand team

`brand.json` → `overrides` holds rules the template file cannot encode (a banned accent,
a minimum logo width, a required footer). `catalog.md` section 6 lists them. They outrank
every default in this file.

## When the brand and good design disagree

Follow the brand, and say so. If a brand font does not render true-to-width in the
LibreOffice preview (`font_safety`), size with about 10% slack and trust the capacity
numbers over the preview. If a template layout is genuinely poor (tiny body area, low
contrast), tell the user rather than silently working around it.
