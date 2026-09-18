#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0.2", "Pillow>=10", "lxml>=5"]
# ///
"""Theme XML -> brand.json: the 12 theme colors, major/minor fonts, slide size, custom colors.

Usage:
    extract_theme.py <template-dir> [--overrides brand-overrides.json]

<template-dir> holds source.pptx; brand.json is written beside it. Color roles are
heuristic defaults. If brand.json already exists, its confirmed `color_roles` are kept.
"""

import argparse
from pathlib import Path

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from _common import NS, QA_RELIABLE_FONTS, emu_to_in, load_json, parse_xml, write_json

COLOR_SLOTS = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4",
               "accent5", "accent6", "hlink", "folHlink"]

DEFAULT_ROLES = {
    "primary": "accent1", "secondary": "accent2", "highlight": "accent4",
    "text_on_dark": "lt1", "text_on_light": "dk1",
    "chart_series_order": ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6"],
}


def _hex(slot_el):
    """6-digit hex, no '#': pptxgenjs corrupts files given '#' or 8-digit values."""
    srgb = slot_el.find("a:srgbClr", NS)
    if srgb is not None:
        return srgb.get("val").upper()[:6]
    sys_clr = slot_el.find("a:sysClr", NS)
    return (sys_clr.get("lastClr") or "000000").upper()[:6]


def read_theme(theme_blob):
    root = parse_xml(theme_blob)
    scheme = root.find(".//a:clrScheme", NS)
    fonts = root.find(".//a:fontScheme", NS)
    return {
        "name": root.get("name"),
        "colors": {slot: _hex(scheme.find(f"a:{slot}", NS)) for slot in COLOR_SLOTS},
        "fonts": {
            "major_latin": fonts.find("a:majorFont/a:latin", NS).get("typeface"),
            "minor_latin": fonts.find("a:minorFont/a:latin", NS).get("typeface"),
        },
        "custom_colors": [
            {"name": c.get("name"), "hex": c.find("a:srgbClr", NS).get("val").upper()[:6]}
            for c in root.findall(".//a:custClrLst/a:custClr", NS) if c.find("a:srgbClr", NS) is not None
        ],
    }


def build_brand(tdir, overrides_path=None):
    tdir = Path(tdir)
    prs = Presentation(str(tdir / "source.pptx"))
    themes = []
    for i, master in enumerate(prs.slide_masters, 1):
        theme = read_theme(master.part.part_related_by(RT.THEME).blob)
        theme["master"] = Path(master.part.partname).name
        clr_map = master.element.find("p:clrMap", NS)
        theme["clr_map"] = dict(clr_map.attrib) if clr_map is not None else {}
        themes.append(theme)

    first = themes[0]
    major, minor = first["fonts"]["major_latin"], first["fonts"]["minor_latin"]
    brand = {
        "template": tdir.name,
        "slide_size_emu": {"cx": prs.slide_width, "cy": prs.slide_height},
        "slide_size_in": {"w": emu_to_in(prs.slide_width), "h": emu_to_in(prs.slide_height)},
        "colors": first["colors"],
        "color_roles": dict(DEFAULT_ROLES),
        "color_roles_confirmed": False,
        "fonts": first["fonts"],
        "font_safety": {
            "major_qa_reliable": major.lower() in QA_RELIABLE_FONTS,
            "minor_qa_reliable": minor.lower() in QA_RELIABLE_FONTS,
            "fallback_body": "Calibri",
        },
        "custom_colors": first["custom_colors"],
        # Multi-master templates: every master's theme, in master order. Top-level keys mirror the first.
        "themes": themes,
        "overrides": {},
    }

    out = tdir / "brand.json"
    if out.exists():
        old = load_json(out)
        if old.get("color_roles_confirmed"):
            brand["color_roles"], brand["color_roles_confirmed"] = old["color_roles"], True
        brand["overrides"] = old.get("overrides", {})
        if old.get("motif"):
            brand["motif"] = old["motif"]
    if overrides_path:
        brand["overrides"] = load_json(overrides_path)
    write_json(out, brand)
    return brand


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template_dir")
    ap.add_argument("--overrides")
    args = ap.parse_args()
    brand = build_brand(args.template_dir, args.overrides)
    print(f"wrote {Path(args.template_dir) / 'brand.json'}: {len(brand['themes'])} theme(s), "
          f"fonts {brand['fonts']['major_latin']} / {brand['fonts']['minor_latin']}")


if __name__ == "__main__":
    main()
