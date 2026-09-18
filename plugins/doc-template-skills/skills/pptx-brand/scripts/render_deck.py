#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0.2", "Pillow>=10", "lxml>=5"]
# ///
"""Render a deck to one PNG per slide plus a labeled contact sheet, for visual QA.

Usage:
    render_deck.py DECK.pptx OUT_DIR [--dpi 110]

Needs LibreOffice (soffice) and Poppler (pdftoppm). Prints the files it wrote.
"""

import argparse
from pathlib import Path

from _common import can_render, contact_sheets, fail, render_slides


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck")
    ap.add_argument("out_dir")
    ap.add_argument("--dpi", type=int, default=110)
    args = ap.parse_args()
    if not can_render():
        fail("LibreOffice (soffice) and Poppler (pdftoppm) are required to render")
    pngs = render_slides(args.deck, args.out_dir, dpi=args.dpi)
    sheets = contact_sheets([(f"slide {i}", p) for i, p in enumerate(pngs, 1)],
                            Path(args.out_dir) / "sheet", cols=3, cell_w=420, per_sheet=12)
    for path in sheets + pngs:
        print(Path(path).resolve())


if __name__ == "__main__":
    main()
