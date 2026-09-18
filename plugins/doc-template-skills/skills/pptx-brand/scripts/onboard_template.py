#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0.2", "Pillow>=10", "lxml>=5"]
# ///
"""Register a brand template once: brand.json, layouts.json, assets.json, thumbnails, catalog.md.

Usage:
    onboard_template.py TEMPLATE.pptx|.potx [--name NAME] [--icons DIR]... [--graphics DIR]...
                        [--icon-deck FILE.pptx]... [--overrides brand-overrides.json]
                        [--default] [--no-render]
    onboard_template.py --list

Output goes to $PPTX_BRAND_HOME/templates/<name>/ (default ~/.pptx-brand). Re-running on a
new template version refreshes everything and keeps confirmed color roles, edited layout
rows and written asset labels.
"""

import argparse
import datetime
import re
import zipfile
from pathlib import Path

from _common import brand_home, can_render, fail, load_json, sha1, write_json
from build_catalog import build_catalog
from extract_theme import build_brand
from harvest_assets import build_assets
from profile_layouts import build_layouts

TEMPLATE_CT = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
DECK_CT = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"


def normalize(src, dest):
    """Copy to source.pptx. A .potx differs only by its main content type, which python-pptx refuses to open."""
    if not zipfile.is_zipfile(src):
        fail(f"{src} is not a .pptx/.potx (legacy .ppt/.pot must be converted first)")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(TEMPLATE_CT.encode(), DECK_CT.encode())
            zout.writestr(item, data)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", nargs="?")
    ap.add_argument("--name")
    ap.add_argument("--icons", action="append", default=[])
    ap.add_argument("--graphics", action="append", default=[])
    ap.add_argument("--icon-deck", action="append", default=[])
    ap.add_argument("--overrides")
    ap.add_argument("--default", action="store_true", help="make this the default template")
    ap.add_argument("--no-render", action="store_true", help="skip thumbnails (no LibreOffice needed)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    root = brand_home() / "templates"
    index_path = root / "index.json"
    index = load_json(index_path) if index_path.exists() else {"default": None, "templates": {}}
    if args.list:
        for name, meta in index["templates"].items():
            print(f"{name}{' (default)' if name == index['default'] else ''}\t{root / name}\t{meta['onboarded']}")
        return
    if not args.template:
        ap.error("TEMPLATE is required")

    src = Path(args.template)
    name = slug(args.name or src.stem)
    tdir = root / name
    tdir.mkdir(parents=True, exist_ok=True)
    normalize(src, tdir / "source.pptx")

    brand = build_brand(tdir, args.overrides)
    layouts, coverage = build_layouts(tdir, render=not args.no_render)
    assets = build_assets(tdir, args.icons, args.graphics, args.icon_deck)
    used = build_catalog(tdir)

    index["templates"][name] = {"source_file": src.name, "source_sha1": sha1(src.read_bytes()),
                                "onboarded": datetime.date.today().isoformat()}
    if args.default or index["default"] is None:
        index["default"] = name
    write_json(index_path, index)

    print(f"registered template {name!r} at {tdir}")
    print(f"  theme: {brand['fonts']['major_latin']} / {brand['fonts']['minor_latin']}, {len(brand['themes'])} master(s)")
    print(f"  layouts: {len(layouts)}; missing classes: {', '.join(coverage['missing_classes']) or 'none'}")
    print(f"  assets: {len(assets)} ({sum(not a['labeled'] for a in assets)} labels to review)")
    print(f"  catalog.md: ~{used} tokens")
    if not args.no_render and not can_render():
        print("warning: LibreOffice (soffice) or pdftoppm missing: thumbnails and vector previews were skipped")
    if "warning" in coverage:
        print("warning: " + coverage["warning"])
    print("next: view thumbs/*.jpg, correct layout classes and asset labels, confirm color roles, "
          "then re-run build_catalog.py")


if __name__ == "__main__":
    main()
