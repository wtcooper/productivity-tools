/**
 * Brand-token option factories for pptxgenjs fallback slides.
 *
 *   const pptxgen = require("pptxgenjs");
 *   const brand = require("<skill>/scripts/brand_pptxgenjs.js").load("acme-corporate"); // name or template dir
 *   const pres = new pptxgen();
 *   brand.applyLayout(pres);                       // before any addSlide(): canvas = template canvas
 *   const slide = pres.addSlide();
 *   slide.addText("Process", brand.text("title", { x: 0.6, y: 0.4, w: 12, h: 1 }));
 *   slide.addShape(pres.ShapeType.roundRect, brand.shape("primary", { x: 1, y: 2, w: 3, h: 1.2 }));
 *   slide.addChart(pres.ChartType.bar, data, brand.chart({ x: 1, y: 1.5, w: 11, h: 5 }));
 *
 * Every factory returns a fresh object: pptxgenjs mutates the options it is given.
 * Colors are 6-digit hex without '#'. Do not set slide.background: merge_slides.py drops
 * it so the slide takes the template master's background.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

function templateDir(nameOrDir) {
  if (nameOrDir && fs.existsSync(path.join(nameOrDir, "brand.json"))) return nameOrDir;
  const root = path.join(process.env.PPTX_BRAND_HOME || path.join(os.homedir(), ".pptx-brand"), "templates");
  const index = JSON.parse(fs.readFileSync(path.join(root, "index.json"), "utf8"));
  const names = Object.keys(index.templates);
  const name = nameOrDir || (names.length === 1 ? names[0] : index.default);
  if (!index.templates[name]) throw new Error(`template ${name} is not registered; registered: ${names.join(", ")}`);
  return path.join(root, name);
}

function load(nameOrDir) {
  const dir = templateDir(nameOrDir);
  const brand = JSON.parse(fs.readFileSync(path.join(dir, "brand.json"), "utf8"));
  const assets = JSON.parse(fs.readFileSync(path.join(dir, "assets.json"), "utf8")).assets;

  /** Role ("primary"), theme slot ("accent3") or custom color name -> hex. Anything else is off-brand. */
  function color(token) {
    const slot = brand.color_roles[token];
    if (typeof slot === "string") return brand.colors[slot];
    if (brand.colors[token]) return brand.colors[token];
    const custom = brand.custom_colors.find((c) => c.name === token);
    if (custom) return custom.hex;
    throw new Error(`"${token}" is not a brand color role, theme slot or custom color`);
  }

  const heading = brand.fonts.major_latin;
  const body = brand.fonts.minor_latin;
  const TEXT = {
    title: { fontFace: heading, fontSize: 36, bold: true },
    heading: { fontFace: heading, fontSize: 22, bold: true },
    body: { fontFace: body, fontSize: 16 },
    caption: { fontFace: body, fontSize: 11 },
    stat: { fontFace: heading, fontSize: 60, bold: true },
  };

  return {
    dir,
    brand,
    color,
    size: brand.slide_size_in,

    applyLayout(pres) {
      pres.defineLayout({ name: "BRAND", width: brand.slide_size_in.w, height: brand.slide_size_in.h });
      pres.layout = "BRAND";
      pres.theme = { headFontFace: heading, bodyFontFace: body };
    },

    /** kind: title | heading | body | caption | stat. Pass onDark: true for text over a dark fill. */
    text(kind, opts = {}) {
      const { onDark, ...rest } = opts;
      if (!TEXT[kind]) throw new Error(`unknown text kind ${kind}`);
      return { ...TEXT[kind], color: color(onDark ? "text_on_dark" : "text_on_light"), margin: 0, ...rest };
    },

    /** Filled shape in a brand color, no outline. */
    shape(token, opts = {}) {
      return { fill: { color: color(token) }, line: { color: color(token), width: 0 }, ...opts };
    },

    /** Native chart defaults: brand series order, quiet axes, brand fonts. */
    chart(opts = {}) {
      const ink = color("text_on_light");
      return {
        chartColors: brand.color_roles.chart_series_order.map((slot) => brand.colors[slot]),
        catAxisLabelColor: ink, valAxisLabelColor: ink,
        // pptxgenjs otherwise writes its own grey (888888) for axis lines, which Brand QA rejects.
        catAxisLineColor: brand.colors.lt2, valAxisLineColor: brand.colors.lt2, serAxisLineColor: brand.colors.lt2,
        catAxisLabelFontFace: body, valAxisLabelFontFace: body,
        legendFontFace: body, legendColor: ink, legendPos: "b",
        dataLabelFontFace: body, dataLabelColor: ink,
        titleFontFace: heading, titleColor: ink,
        valGridLine: { color: brand.colors.lt2, size: 0.5 }, catGridLine: { style: "none" },
        ...opts,
      };
    },

    /** Best catalog match for a tag or "#index". Returns { index, label, path } or null; path is embeddable PNG/JPG. */
    icon(query) {
      const q = String(query).toLowerCase().replace(/^#/, "");
      let best = null, bestScore = 0;
      for (const a of assets) {
        const label = a.label.toLowerCase();
        const score = /^\d+$/.test(q) ? (a.index === Number(q) ? 9 : 0)
          : 3 * a.tags.map((t) => t.toLowerCase()).includes(q) + 2 * label.split(" ").includes(q) + label.includes(q);
        if (score > bestScore) { best = a; bestScore = score; }
      }
      if (!best || best.format === "shape") return null;
      const raster = ["png", "jpg", "jpeg", "gif"].includes(best.format);
      return { index: best.index, label: best.label, path: path.join(dir, raster ? best.file : best.preview) };
    },
  };
}

module.exports = { load };
