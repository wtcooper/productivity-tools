#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0.2", "Pillow>=10", "lxml>=5"]
# ///
"""brand.json + layouts.json + assets.json -> catalog.md, the one file the deck builder loads.

Usage:
    build_catalog.py <template-dir>

Kept under ~6k tokens: placeholder geometry stays in layouts.json, and a large icon
library collapses from one row per icon to a tag index.
"""

import argparse
from collections import defaultdict
from pathlib import Path

from _common import load_json

TOKEN_BUDGET = 6000


def tokens(text):
    return len(text) // 4


def brand_section(brand):
    colors, roles = brand["colors"], brand["color_roles"]
    size = brand["slide_size_in"]
    confirmed = "" if brand.get("color_roles_confirmed") else " (heuristic, not yet confirmed with the user)"
    lines = [f"# Brand catalog: {brand['template']}", "",
             "Palette, fonts and slide size are fixed by the template. Never substitute your own.", "",
             "## 1. Brand tokens", "",
             f"- Slide size: {size['w']} x {size['h']} in",
             f"- Heading font: {brand['fonts']['major_latin']} | Body font: {brand['fonts']['minor_latin']}"]
    safety = brand["font_safety"]
    if not (safety["major_qa_reliable"] and safety["minor_qa_reliable"]):
        lines.append("- Brand fonts do not render true-to-width in LibreOffice previews: leave ~10% slack in text "
                     "boxes and do not trust preview text fit.")
    if brand.get("motif"):
        lines.append(f"- Visual motif: {brand['motif']}")
    lines += ["", f"Color roles{confirmed}:", "", "| Role | Theme slot | Hex |", "|---|---|---|"]
    for role, slot in roles.items():
        if isinstance(slot, str):
            lines.append(f"| {role} | {slot} | {colors[slot]} |")
    lines.append(f"| chart series order | {', '.join(roles['chart_series_order'])} | "
                 f"{', '.join(colors[s] for s in roles['chart_series_order'])} |")
    lines += ["", "All theme slots: " + ", ".join(f"{k}={v}" for k, v in colors.items())]
    if brand["custom_colors"]:
        lines.append("Custom colors: " + ", ".join(f"{c['name']}={c['hex']}" for c in brand["custom_colors"]))
    return lines


def layout_section(layouts):
    lines = ["", "## 2. Layouts", "",
             "Request a layout by class (or exact name) in the outline. Geometry is in layouts.json.", "",
             "| # | Class | Name | Placeholders (type:idx) | Body capacity | Use for | Thumbnail |", "|---|---|---|---|---|---|---|"]
    for l in layouts:
        phs = ", ".join(f"{p['type']}:{p['idx']}" for p in l["placeholders"] if p["type"] not in ("dt", "ftr", "sldNum"))
        caps = [f"{p['capacity_lines']}x{p['chars_per_line']}" for p in l["placeholders"] if "capacity_lines" in p]
        note = f" {l['notes']}" if l["notes"] else ""
        lines.append(f"| {l['index']} | {l['class']} | {l['name']} | {phs or '-'} | "
                     f"{' / '.join(caps) + ' lines x chars' if caps else '-'} | {l['use_for']}{note} | {l.get('thumb', '-')} |")
    return lines


def asset_rows(assets, kinds):
    return [a for a in assets if a["kind"] in kinds]


def icon_section(assets, compact):
    icons = asset_rows(assets, {"icon", "logo"})
    lines = ["", "## 3. Icons and logos", ""]
    if not icons:
        return lines + ["None catalogued."]
    sheets = sorted({a["thumb"] for a in icons if a.get("thumb")})
    lines.append("Contact sheets: " + (", ".join(sheets) or "not rendered") + ". R = recolorable to a brand token.")
    lines.append("")
    if compact:
        by_tag = defaultdict(list)
        for a in icons:
            for tag in a["tags"] or [a["label"]]:
                by_tag[tag].append(str(a["index"]))
        lines.append("Tag index (tag: asset indexes). Labels and files are in assets.json.")
        lines.append("")
        lines += [f"- {tag}: {', '.join(ids)}" for tag, ids in sorted(by_tag.items())]
    else:
        lines += ["| # | Label | Tags | Kind | R |", "|---|---|---|---|---|"]
        lines += [f"| {a['index']} | {a['label']} | {', '.join(a['tags'])} | {a['kind']} | {'R' if a['recolorable'] else ''} |"
                  for a in icons]
    return lines


def graphics_section(assets):
    graphics = asset_rows(assets, {"diagram", "pattern", "photo"})
    lines = ["", "## 4. Graphics and photos", ""]
    if not graphics:
        return lines + ["None catalogued."]
    lines += ["| # | Label | Tags | Kind | Pixels | Used by |", "|---|---|---|---|---|---|"]
    lines += [f"| {a['index']} | {a['label']} | {', '.join(a['tags'])} | {a['kind']} | "
              f"{'x'.join(map(str, a['px'])) if a['px'] else '-'} | {', '.join(a['used_by'][:3]) or '-'} |" for a in graphics]
    return lines


def rules_section(brand, coverage):
    missing = coverage["missing_classes"]
    lines = ["", "## 5. Coverage gaps and fallback", ""]
    if missing:
        lines.append(f"The template has no layout for: {', '.join(missing)}. fill_layout.py substitutes the nearest class "
                     "and reports it. For a bespoke visual, build the slide with brand_pptxgenjs.js and merge it with "
                     "merge_slides.py so it lands on a template layout.")
    else:
        lines.append("Every layout class is covered by the template.")
    if coverage.get("warning"):
        lines.append(f"\nWarning: {coverage['warning']}")
    lines += ["", "## 6. Do / don't", ""]
    overrides = brand.get("overrides") or {}
    rules = [f"- DO: {r}" for r in overrides.get("do", [])] + [f"- DON'T: {r}" for r in overrides.get("dont", [])]
    rules += [f"- {k}: {v}" for k, v in overrides.items() if k not in ("do", "dont", "extra_colors", "extra_fonts")]
    return lines + (rules or ["No template-specific rules recorded."])


def build_catalog(tdir):
    tdir = Path(tdir)
    brand = load_json(tdir / "brand.json")
    layout_data = load_json(tdir / "layouts.json")
    assets = load_json(tdir / "assets.json")["assets"]

    def render(compact):
        parts = (brand_section(brand) + layout_section(layout_data["layouts"]) + icon_section(assets, compact)
                 + graphics_section(assets) + rules_section(brand, layout_data["coverage"]))
        return "\n".join(parts) + "\n"

    text = render(compact=False)
    if tokens(text) > TOKEN_BUDGET:
        text = render(compact=True)
    (tdir / "catalog.md").write_text(text)
    return tokens(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template_dir")
    args = ap.parse_args()
    used = build_catalog(args.template_dir)
    print(f"wrote catalog.md (~{used} tokens)")
    if used > TOKEN_BUDGET:
        print(f"warning: catalog exceeds the ~{TOKEN_BUDGET}-token budget; merge or prune icon tags in assets.json")


if __name__ == "__main__":
    main()
