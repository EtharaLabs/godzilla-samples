// Charts: |chart| (bars, lines, areas, dots, bubbles, bands, marks, axes;
// cartesian or radial) and |pie| (slices). A chart lays out and paints its
// own series children; they are not rendered as ordinary nodes.

mod cart;
pub mod model;
mod pie;
mod radial;
pub mod scale;

use crate::compile::Ctx;
use crate::diag::Diag;
use crate::font::Family;
use crate::render::Out;
use crate::util::{f4, xml_escape};
use std::cell::RefCell;
use std::collections::HashMap;

// Chart text sizes: ticks/labels/tips 12 normal, legend 12 semibold, title 15 semibold.
pub const FS: f64 = 12.0;

// Text width, accumulated glyph by glyph (each advance scaled on its own).
fn cw(weight: u32, size: f64, s: &str) -> f64 {
    let f = crate::font::font(Family::Sans, weight);
    let mut w = 0.0f64;
    for ch in s.chars() {
        let adv = match f.glyph_for(ch) {
            Some(g) => f.adv[g as usize] as f64,
            None => {
                let wide = crate::font::text_width(Family::Sans, weight, 1000.0, &ch.to_string());
                wide / 1000.0 * f.upem
            }
        };
        w += adv / f.upem * size;
    }
    w
}

pub fn tw(s: &str) -> f64 {
    cw(400, FS, s)
}

pub fn tw_legend(s: &str) -> f64 {
    cw(600, FS, s)
}

pub fn tw_title(s: &str) -> f64 {
    cw(600, 15.0, s)
}

// One emitted element of a chart.
#[derive(Clone, Debug)]
pub enum El {
    // <g class="lini-node {cls}" style transform> [title] inner... kids... </g>
    G { cls: String, style: String, tx: f64, ty: f64, title: Option<String>, inner: Vec<String>, kids: Vec<El> },
    // <text class="lini-text {cls}" x y dy style>text</text>
    T { cls: String, x: f64, y: f64, style: String, text: String },
}

#[derive(Default, Clone, Debug)]
pub struct Flags {
    pub title: bool,
    pub text: bool,
    pub label: bool,
    pub legend: bool,
    pub tip: bool,
    pub hits: usize,
    pub line: bool,
    pub oval: bool,
    pub poly: bool,
    pub diamond: bool,
}

#[derive(Default, Clone, Debug)]
pub struct Drawing {
    pub els: Vec<El>,
    pub flags: Flags,
    // content bounds relative to the chart centre
    pub bbox: Option<[f64; 4]>,
}

thread_local! {
    static CACHE: RefCell<HashMap<usize, Result<Drawing, Diag>>> = RefCell::new(HashMap::new());
}

// Is node `i` a chart or pie container this module paints?
pub fn is_chart(ctx: &Ctx, i: usize) -> bool {
    let l = ctx.comp[i].layout.as_str();
    l == "chart" || l == "pie"
}

fn default_size(ctx: &Ctx, i: usize) -> (f64, f64) {
    let pie = ctx.comp[i].layout == "pie";
    let radial = ctx.nodes[i].props.get("direction").and_then(model::ident).as_deref() == Some("radial");
    let (dw, dh) = if pie || radial { (280.0, 280.0) } else { (360.0, 220.0) };
    let c = &ctx.comp[i];
    (c.width.unwrap_or(dw), c.height.unwrap_or(dh))
}

// Placement checks before layout: chart series and parts only live in a chart,
// slices only in a pie; a bare line or polygon needs its points.
pub fn validate(ctx: &Ctx) -> Result<(), Diag> {
    for i in 1..ctx.nodes.len() {
        let n = &ctx.nodes[i];
        if n.prim == crate::types::Prim::Text {
            continue;
        }
        let parent_layout = n.parent.map(|p| ctx.comp[p].layout.as_str()).unwrap_or("");
        let name = n.chain.first().cloned().unwrap_or_default();
        if n.is("slice") {
            if parent_layout != "pie" {
                return Err(Diag::error("chart-type", &format!("'|{}|' belongs in a 'layout: pie'", name), n.span));
            }
            continue;
        }
        if parent_layout == "chart" || parent_layout == "pie" {
            continue;
        }
        for t in ["bars", "area", "dots", "bubble"] {
            if n.is(t) {
                return Err(Diag::error(
                    "chart-type",
                    &format!("'|{}|' is a chart series — it belongs in a 'layout: chart'", name),
                    n.span,
                ));
            }
        }
        for t in ["band", "mark", "axis"] {
            if n.is(t) {
                return Err(Diag::error("chart-type", &format!("'|{}|' belongs in a 'layout: chart'", name), n.span));
            }
        }
    }
    for i in 1..ctx.nodes.len() {
        let n = &ctx.nodes[i];
        let parent_layout = n.parent.map(|p| ctx.comp[p].layout.as_str()).unwrap_or("");
        if parent_layout == "chart" || parent_layout == "pie" {
            continue;
        }
        if n.props.contains_key("chrome") || n.is("plane") {
            continue;
        }
        if matches!(n.prim, crate::types::Prim::Line | crate::types::Prim::Poly) && !n.props.contains_key("points") {
            let name = n.chain.first().cloned().unwrap_or_default();
            return Err(Diag::error("missing-required-property", &format!("'|{}|' requires 'points'", name), n.span));
        }
    }
    Ok(())
}

// Size the chart (sets ctx.nodes[i].w / h). Children are not laid out by the core.
pub fn measure(ctx: &mut Ctx, i: usize) {
    let (w, h) = default_size(ctx, i);
    {
        // the box is the outer size; a stroked frame draws inside it
        let sw = if ctx.comp[i].has_stroke { ctx.comp[i].stroke_width } else { 0.0 };
        let n = &mut ctx.nodes[i];
        n.w = w - sw;
        n.h = h - sw;
    }
    let res = draw(ctx, i, w, h);
    CACHE.with(|c| {
        c.borrow_mut().insert(i, res);
    });
}

fn draw(ctx: &Ctx, i: usize, w: f64, h: f64) -> Result<Drawing, Diag> {
    let ch = model::build(ctx, i)?;
    let mut d = if ch.pie {
        pie::draw(ctx, &ch, w, h)?
    } else if ch.dir == model::Dir::Radial {
        radial::draw(ctx, &ch, w, h)?
    } else {
        cart::draw(ctx, &ch, w, h)?
    };
    d.bbox = Some(bbox_of(&d.els));
    Ok(d)
}

// Content bounds of a chart (relative to its centre), for the viewBox.
pub fn content_bbox(i: usize) -> Option<[f64; 4]> {
    CACHE.with(|c| match c.borrow().get(&i) {
        Some(Ok(d)) => d.bbox,
        _ => None,
    })
}

fn attr(s: &str, name: &str) -> Option<f64> {
    let key = format!(" {}=\"", name);
    let p = s.find(&key)? + key.len();
    let e = s[p..].find('"')? + p;
    s[p..e].parse().ok()
}

// Half the drawn stroke of an element: its inline width, else the
// primitive's default (2) when it is stroked at all.
fn half_stroke(style: &str) -> f64 {
    if let Some(p) = style.find("stroke-width: ") {
        let rest = &style[p + 14..];
        let end = rest.find(';').unwrap_or(rest.len());
        return rest[..end].trim().parse::<f64>().unwrap_or(0.0) / 2.0;
    }
    if style.contains("stroke: ") && !style.contains("stroke: none") {
        1.0
    } else {
        0.0
    }
}

fn bbox_of(els: &[El]) -> [f64; 4] {
    let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    let mut add = |x0: f64, y0: f64, x1: f64, y1: f64| {
        b[0] = b[0].min(x0);
        b[1] = b[1].min(y0);
        b[2] = b[2].max(x1);
        b[3] = b[3].max(y1);
    };
    for e in els {
        match e {
            El::G { cls, style, tx, ty, inner, .. } => {
                if cls.contains("chart-tip") {
                    continue;
                }
                for l in inner {
                    let h = half_stroke(style);
                    if l.starts_with("<rect") {
                        if let (Some(x), Some(y), Some(w), Some(hh)) = (attr(l, "x"), attr(l, "y"), attr(l, "width"), attr(l, "height")) {
                            add(tx + x - h, ty + y - h, tx + x + w + h, ty + y + hh + h);
                        }
                    } else if l.starts_with("<ellipse") {
                        if let (Some(rx), Some(ry)) = (attr(l, "rx"), attr(l, "ry")) {
                            add(tx - rx - h, ty - ry - h, tx + rx + h, ty + ry + h);
                        }
                    } else if l.starts_with("<polygon") || l.starts_with("<polyline") {
                        // outlines count by their points alone, without the stroke
                        if let Some(pts) = l.split('"').nth(1) {
                            for p in pts.split(' ') {
                                let mut it = p.split(',');
                                if let (Some(Ok(x)), Some(Ok(y))) = (it.next().map(|v| v.parse::<f64>()), it.next().map(|v| v.parse::<f64>())) {
                                    add(tx + x, ty + y, tx + x, ty + y);
                                }
                            }
                        }
                    } else if l.starts_with("<line") {
                        if let (Some(x1), Some(y1), Some(x2), Some(y2)) = (attr(l, "x1"), attr(l, "y1"), attr(l, "x2"), attr(l, "y2")) {
                            add(tx + x1.min(x2), ty + y1.min(y2), tx + x1.max(x2), ty + y1.max(y2));
                        }
                    }
                }
            }
            El::T { cls, x, y, text, .. } => {
                let w = if cls.contains("chart-title") {
                    tw_title(text)
                } else if cls.contains("chart-legend") {
                    tw_legend(text)
                } else {
                    tw(text)
                };
                let h = if cls.contains("chart-title") { 15.0 } else { FS };
                add(x - w / 2.0, y - h / 2.0, x + w / 2.0, y + h / 2.0);
            }
        }
    }
    b
}

// Paint the chart's inner elements (inside the node's <g>, at indent `ind`).
pub fn render(ctx: &Ctx, i: usize, ind: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let d = CACHE.with(|c| c.borrow().get(&i).cloned());
    let d = match d {
        Some(r) => r?,
        None => return Ok(()),
    };
    for l in crate::render::shape_lines(ctx, i) {
        s.push_str(&" ".repeat(ind));
        s.push_str(&l);
        s.push('\n');
    }
    for e in &d.els {
        emit(e, ind, s, out);
    }
    let f = &d.flags;
    fn has_text(els: &[El]) -> bool {
        els.iter().any(|e| match e {
            El::T { .. } => true,
            El::G { kids, .. } => has_text(kids),
        })
    }
    if has_text(&d.els) {
        out.any_text = true;
    }
    crate::style::use_var(&mut out.vars, "stroke");
    if f.line && !out.used_types.iter().any(|t| t == "line") {
        out.used_types.push("line".into());
    }
    if f.oval {
        out.extra_rules.push(("oval".into(), ".lini-oval { stroke-dasharray: none; }".into()));
    }
    if f.diamond {
        out.extra_rules.push(("diamond".into(), ".lini-diamond { stroke-dasharray: none; }".into()));
    }
    if f.poly {
        out.extra_rules.push(("poly".into(), ".lini-poly { stroke-dasharray: none; }".into()));
    }
    if f.title {
        out.extra_rules.push(("chart-title".into(), ".lini-chart-title { font-size: 15px; font-weight: 600; }".into()));
    }
    if f.text {
        out.extra_rules.push(("chart-text".into(), ".lini-chart-text { font-size: 12px; font-weight: normal; }".into()));
    }
    if f.label {
        out.extra_rules.push(("chart-label".into(), ".lini-chart-label { font-size: 12px; font-weight: normal; }".into()));
        out.extra_rules.push(("chart-label-pe".into(), ".lini-chart-label { pointer-events: none; }".into()));
    }
    if f.legend {
        out.extra_rules.push(("chart-legend".into(), ".lini-chart-legend { font-size: 12px; font-weight: 600; }".into()));
    }
    if f.tip {
        out.extra_rules.push(("chart-tip".into(), ".lini-chart-tip { visibility: hidden; pointer-events: none; }".into()));
        for k in 0..f.hits {
            out.extra_rules.push(("chart-hit".into(), format!(".lini-hit-{}:hover ~ .lini-tip-{} {{ visibility: visible; }}", k, k)));
        }
    }
    Ok(())
}

fn use_vars(style: &str, out: &mut Out) {
    let mut rest = style;
    while let Some(p) = rest.find("var(--lini-") {
        let after = &rest[p + 11..];
        let end = after.find(')').unwrap_or(after.len());
        crate::style::use_var(&mut out.vars, &after[..end]);
        rest = &after[end..];
    }
}

fn emit(e: &El, ind: usize, s: &mut String, out: &mut Out) {
    let pad = " ".repeat(ind);
    match e {
        El::G { cls, style, tx, ty, title, inner, kids } => {
            use_vars(style, out);
            s.push_str(&pad);
            s.push_str(&format!("<g class=\"lini-node {}\"", cls));
            if !style.is_empty() {
                s.push_str(&format!(" style=\"{}\"", xml_escape(style)));
            }
            s.push_str(&format!(" transform=\"translate({},{})\">\n", f4(*tx), f4(*ty)));
            let ci = " ".repeat(ind + 2);
            if let Some(t) = title {
                s.push_str(&format!("{}<title>{}</title>\n", ci, xml_escape(t)));
            }
            for l in inner {
                s.push_str(&ci);
                s.push_str(l);
                s.push('\n');
            }
            for k in kids {
                emit(k, ind + 2, s, out);
            }
            s.push_str(&pad);
            s.push_str("</g>\n");
        }
        El::T { cls, x, y, style, text } => {
            use_vars(style, out);
            s.push_str(&pad);
            s.push_str(&format!("<text class=\"lini-text {}\" x=\"{}\" y=\"{}\" dy=\"0.358em\"", cls, f4(*x), f4(*y)));
            if !style.is_empty() {
                s.push_str(&format!(" style=\"{}\"", xml_escape(style)));
            }
            s.push_str(&format!(">{}</text>\n", xml_escape(text)));
        }
    }
}

// ------------------------------------------------------------ shared helpers

pub fn rect(x: f64, y: f64, w: f64, h: f64, r: f64) -> String {
    format!("<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"{}\" ry=\"{}\"/>", f4(x), f4(y), f4(w), f4(h), f4(r), f4(r))
}

pub fn line_el(x1: f64, y1: f64, x2: f64, y2: f64, style: &str) -> El {
    El::G {
        cls: "lini-line".into(),
        style: style.into(),
        tx: 0.0,
        ty: 0.0,
        title: None,
        inner: vec![format!("<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>", f4(x1), f4(y1), f4(x2), f4(y2))],
        kids: vec![],
    }
}

pub fn pts_str(pts: &[(f64, f64)]) -> String {
    pts.iter().map(|(x, y)| format!("{},{}", f4(*x), f4(*y))).collect::<Vec<_>>().join(" ")
}

// Clip a polyline to a rectangle [l, t, r, b], segment by segment
// (Liang–Barsky); a run continues while a segment starts exactly where the
// previous clipped segment ended.
pub fn clip_runs(pts: &[(f64, f64)], rc: [f64; 4]) -> Vec<Vec<(f64, f64)>> {
    let mut runs: Vec<Vec<(f64, f64)>> = Vec::new();
    let mut cur: Vec<(f64, f64)> = Vec::new();
    for k in 1..pts.len() {
        let (x0, y0) = pts[k - 1];
        let (x1, y1) = pts[k];
        let dx = x1 - x0;
        let dy = y1 - y0;
        let mut t0 = 0.0f64;
        let mut t1 = 1.0f64;
        let mut ok = true;
        for (p, q) in [(-dx, x0 - rc[0]), (dx, rc[2] - x0), (-dy, y0 - rc[1]), (dy, rc[3] - y0)] {
            if p == 0.0 {
                if q < 0.0 {
                    ok = false;
                    break;
                }
            } else {
                let r = q / p;
                if p < 0.0 {
                    if r > t1 {
                        ok = false;
                        break;
                    } else if r > t0 {
                        t0 = r;
                    }
                } else if r < t0 {
                    ok = false;
                    break;
                } else if r < t1 {
                    t1 = r;
                }
            }
        }
        if !ok {
            if cur.len() >= 2 {
                runs.push(std::mem::take(&mut cur));
            }
            cur.clear();
            continue;
        }
        let q0 = (x0 + t0 * dx, y0 + t0 * dy);
        let q1 = (x0 + t1 * dx, y0 + t1 * dy);
        if cur.last() == Some(&q0) {
            cur.push(q1);
        } else {
            if cur.len() >= 2 {
                runs.push(std::mem::take(&mut cur));
            }
            cur = vec![q0, q1];
        }
    }
    if cur.len() >= 2 {
        runs.push(cur);
    }
    runs
}

// A polyline (or a <line> for two points).
pub fn path_el(pts: &[(f64, f64)], style: &str) -> El {
    if pts.len() == 2 {
        return line_el(pts[0].0, pts[0].1, pts[1].0, pts[1].1, style);
    }
    El::G {
        cls: "lini-line".into(),
        style: style.into(),
        tx: 0.0,
        ty: 0.0,
        title: None,
        inner: vec![format!("<polyline points=\"{}\"/>", pts_str(pts))],
        kids: vec![],
    }
}

pub fn poly_el(cls: &str, pts: &[(f64, f64)], style: &str, title: Option<String>) -> El {
    El::G {
        cls: format!("{}lini-poly", cls),
        style: style.into(),
        tx: 0.0,
        ty: 0.0,
        title,
        inner: vec![format!("<polygon points=\"{}\"/>", pts_str(pts))],
        kids: vec![],
    }
}

pub fn text_el(cls: &str, x: f64, y: f64, style: &str, text: &str) -> El {
    El::T { cls: cls.into(), x, y, style: style.into(), text: text.into() }
}

// A hover tip anchored at (ax, ay), kept inside the chart box.
pub fn tip_el(k: usize, ax: f64, ay: f64, text: &str, bounds: [f64; 4]) -> El {
    let w = tw(text) + 10.0;
    let h = 22.0;
    let mut x = ax + 7.0;
    let mut y = ay - 29.0;
    if x + w > bounds[2] {
        x = bounds[2] - w;
    }
    if x < bounds[0] {
        x = bounds[0];
    }
    if y + h > bounds[3] {
        y = bounds[3] - h;
    }
    if y < bounds[1] {
        y = bounds[1];
    }
    let cx = x + w / 2.0;
    let cy = y + h / 2.0;
    El::G {
        cls: format!("lini-chart-tip lini-tip-{} lini-block", k),
        style: String::new(),
        tx: 0.0,
        ty: 0.0,
        title: None,
        inner: vec![rect(x, y, w, h, 0.0)],
        kids: vec![
            El::G {
                cls: "lini-block".into(),
                style: "fill: var(--lini-tip-bg); stroke-width: 0".into(),
                tx: cx,
                ty: cy,
                title: None,
                inner: vec![rect(-w / 2.0, -h / 2.0, w, h, 3.0)],
                kids: vec![],
            },
            text_el("lini-chart-text", cx, cy, "fill: var(--lini-tip-fg)", text),
        ],
    }
}

// ------------------------------------------------------------ colours

pub const PALETTE: &[&str] = &["rose", "teal", "orange", "sky", "amber", "purple", "green", "blue", "lime", "gray"];
pub const HUES: &[&str] = &["red", "rose", "orange", "amber", "lime", "green", "teal", "sky", "blue", "purple", "gray"];

pub fn hue(k: usize) -> &'static str {
    PALETTE[k % PALETTE.len()]
}

// The hue of a palette colour "var(--lini-sky-soft)" → "sky".
pub fn hue_of(css: &str) -> Option<String> {
    let inner = css.strip_prefix("var(--lini-")?.strip_suffix(')')?;
    let base = inner.split('-').next()?;
    if HUES.contains(&base) {
        let rest = &inner[base.len()..];
        if rest.is_empty() || matches!(rest, "-wash" | "-soft" | "-deep" | "-ink") {
            return Some(base.to_string());
        }
    }
    None
}

// The stroke derived from a fill: the hue's deep tier, else the fill itself.
pub fn deep_of(css: &str) -> String {
    match hue_of(css) {
        Some(h) => format!("var(--lini-{}-deep)", h),
        None => css.to_string(),
    }
}

// CSS text of a colour term (vars are registered when the style is emitted).
pub fn color_term(t: &crate::ast::Term) -> Option<String> {
    let mut tmp = Vec::new();
    match t {
        // 'auto' and 'none' leave the colour to the walk
        crate::ast::Term::Ident(s, _) if s == "auto" || s == "none" => None,
        _ => crate::style::color_css(t, &mut tmp, t.span()).ok(),
    }
}

// Entry k of a colour list (a single value applies to every entry).
pub fn color_at(v: &Option<crate::ast::Value>, k: usize) -> Option<String> {
    let v = v.as_ref()?;
    let g = if v.groups.len() == 1 { v.groups.first()? } else { v.groups.get(k)? };
    color_term(g.first()?)
}

pub fn is_list(v: &Option<crate::ast::Value>) -> bool {
    v.as_ref().map(|v| v.groups.len() > 1).unwrap_or(false)
}

pub fn raw_term(v: &Option<crate::ast::Value>) -> Option<String> {
    let v = v.as_ref()?;
    let t = crate::style::single_term(v)?;
    match t {
        crate::ast::Term::Ident(s, _) if s == "auto" || s == "none" => None,
        crate::ast::Term::Ident(s, _) => Some(s.clone()),
        _ => color_term(t),
    }
}
