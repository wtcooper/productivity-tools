"""Shared helpers for the pptx-brand scripts: paths, safe XML, rendering, contact sheets."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from find_upstream import find_upstream

EMU_PER_IN = 914400

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# Fonts that LibreOffice renders at true width, so a preview's text fit can be trusted.
QA_RELIABLE_FONTS = {"arial", "calibri", "cambria", "times new roman", "courier new",
                     "bookman old style", "century schoolbook"}

# Templates are untrusted input: no entity expansion, no network.
SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def fail(msg):
    sys.exit(f"error: {msg}")


def parse_xml(blob):
    return etree.fromstring(blob, SAFE_PARSER)


def emu_to_in(emu):
    return round(emu / EMU_PER_IN, 3)


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def brand_home():
    """Registered templates live outside the plugin so plugin updates never wipe them."""
    return Path(os.environ.get("PPTX_BRAND_HOME", Path.home() / ".pptx-brand"))


def template_dir(name=None):
    """Resolve a registered template directory; with no name, use the only one or the default."""
    root = brand_home() / "templates"
    index_path = root / "index.json"
    index = load_json(index_path) if index_path.exists() else {"default": None, "templates": {}}
    names = sorted(index["templates"])
    if name is None:
        if len(names) == 1:
            name = names[0]
        elif index.get("default"):
            name = index["default"]
        else:
            fail(f"pass --template; registered templates: {names or 'none (run onboard_template.py first)'}")
    if name not in index["templates"]:
        fail(f"template {name!r} is not registered; registered: {names}")
    return root / name


def soffice_cmd():
    """Prefer the official skill's wrapper (bare soffice hangs in some sandboxes); else the binary."""
    upstream = find_upstream()
    if upstream and (upstream / "scripts/office/soffice.py").is_file():
        return [sys.executable, str(upstream / "scripts/office/soffice.py")]
    binary = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    return [binary] if Path(binary).exists() else None


def can_render():
    return soffice_cmd() is not None and shutil.which("pdftoppm") is not None


def soffice_convert(src, fmt, out_dir):
    subprocess.run(soffice_cmd() + ["--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(src)],
                   check=True, capture_output=True, timeout=600)
    return Path(out_dir) / (Path(src).stem + "." + fmt)


def render_slides(pptx_path, out_dir, prefix="slide", dpi=110):
    """Render every slide to PNG via LibreOffice + pdftoppm. Returns the image paths in slide order."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pdf = soffice_convert(pptx_path, "pdf", tmp)
        for old in out_dir.glob(f"{prefix}-*.png"):
            old.unlink()
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out_dir / prefix)],
                       check=True, capture_output=True)
    return sorted(out_dir.glob(f"{prefix}-*.png"))


def to_png(src, dest, size=256):
    """Write a preview PNG no larger than `size`. Vector formats (SVG/EMF/WMF) go through LibreOffice."""
    src, dest = Path(src), Path(dest)
    try:
        img = Image.open(src)
        img.load()
    except Exception:
        if soffice_cmd() is None:
            return False
        with tempfile.TemporaryDirectory() as tmp:
            try:
                img = Image.open(soffice_convert(src, "png", tmp))
                img.load()
            except Exception:
                return False
    img = img.convert("RGBA")
    img.thumbnail((size, size))
    img.save(dest)
    return True


def _font(px):
    for name in ("Arial.ttf", "DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def contact_sheets(items, out_prefix, cols=4, cell_w=300, per_sheet=24, checker=False):
    """Labeled grids. `items` is [(label, image_path)]. Returns the JPG paths written."""
    font = _font(15)
    label_h, pad = 40, 16
    paths = []
    chunks = [items[i:i + per_sheet] for i in range(0, len(items), per_sheet)]
    for n, chunk in enumerate(chunks, 1):
        thumbs = []
        for label, path in chunk:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((cell_w, cell_w))
            thumbs.append((label, img))
        cell_h = max(t.height for _, t in thumbs)
        rows = -(-len(thumbs) // cols)
        sheet = Image.new("RGB", (cols * (cell_w + pad) + pad, rows * (cell_h + label_h + pad) + pad), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (label, img) in enumerate(thumbs):
            x = pad + (i % cols) * (cell_w + pad)
            y = pad + (i // cols) * (cell_h + label_h + pad)
            # Mid-grey backing keeps white-on-transparent and black-on-transparent icons both visible.
            draw.rectangle([x, y, x + cell_w, y + cell_h], fill="#B8B8B8" if checker else "#F2F2F2")
            sheet.paste(img, (x + (cell_w - img.width) // 2, y + (cell_h - img.height) // 2), img)
            draw.rectangle([x, y, x + cell_w, y + cell_h], outline="#999999")
            draw.text((x, y + cell_h + 4), label[:42], fill="black", font=font)
        path = Path(f"{out_prefix}-{n}.jpg")
        sheet.save(path, quality=90)
        paths.append(path)
    return paths


def drop_all_slides(prs):
    """Remove every slide but keep masters, layouts and theme. Dropped parts are not saved."""
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst):
        prs.part.drop_rel(sld_id.rId)
        sld_id_lst.remove(sld_id)
    # Sections list slide ids; stale ids make PowerPoint offer to repair the file.
    for el in prs.part._element.xpath("//*[local-name()='sectionLst']"):
        ext = el.getparent()
        ext.getparent().remove(ext)


def ph_type(shape):
    """Raw OOXML placeholder type; an absent type attribute means a generic content ('obj') placeholder."""
    return shape._element.xpath(".//p:nvPr/p:ph")[0].get("type", "obj")
