// Drawing annotations [SPEC 15.5–15.9]: dimensions `(-)` / `(o)`, leaders
// `<-` `*-` `>-`, datums, GD&T frames and surface-finish symbols, halos.
//
// Layout runs inside a drawing frame's measure (after its parts sit on the
// datum, before the frame is centred): every annotation statement written
// directly in the drawing is laid out in datum coordinates and its items
// extend the frame's content box. The frame's centring shift is recorded so
// render can write the items after the frame's children (generated nodes
// translate by the shift; texts carry frame coordinates).
//
// Facts (px, verified against the reference):
// - dimension rows: the band (text + arrows + overshoot) clears the geometry
//   box (and the rows inside it) by CLEAR; text centre sits TEXT_OFF from the
//   dim line, above (horizontal) / left (vertical) of it.
// - arrows inside when span >= text + 30, else outside (line runs 14 past);
//   text inside when span >= text + 4, else after the far end (+4).
// - leaders: the ray from the frame datum through the feature (default 45°
//   up-right), knee = where it leaves the content box + NOTE_OFFSET, pushed
//   out until the note text clears the box by NOTE_OFFSET; landing 12, text
//   gap 5. `side:` turns the ray to that side's normal.

use crate::compile::Ctx;
use crate::diag::{Diag, Span};
use crate::geom::BBox;
use crate::render::Out;
use crate::sketch::{pt, Seg, TagKind, P};
use crate::style::{ident_of, use_var};
use crate::types::Prim;
use crate::util::{f4, xml_escape};
use std::collections::HashMap;

pub const CLEAR: f64 = 18.0;
pub const EXT_GAP: f64 = 3.0;
pub const EXT_OVER: f64 = 3.0;
pub const HALO_MARGIN: f64 = 2.0;
pub const HALO_W: f64 = 3.0;
pub const ARROW_L: f64 = 12.0;
pub const ARROW_HW: f64 = 2.0;
pub const DATUM_TRI: f64 = 11.0;
pub const NOTE_OFFSET: f64 = 20.0;
pub const NOTE_LANDING: f64 = 12.0;
pub const NOTE_GAP: f64 = 5.0;
pub const TOL_STACK: f64 = 0.7;
pub const FONT: f64 = 12.0;

// The statement being laid out: its stroke width (arrowheads and insets
// scale with it) and its text size (the text stands half its size + 2 off
// the line).
thread_local! {
    static INK: std::cell::Cell<(f64, f64)> = std::cell::Cell::new((1.0, FONT));
}
fn set_ink(w: f64, font: f64) {
    INK.with(|c| c.set((w, font)));
}
fn ink_w() -> f64 {
    INK.with(|c| c.get().0)
}
fn font_sz() -> f64 {
    INK.with(|c| c.get().1)
}
fn arrow_l() -> f64 {
    ARROW_L * ink_w()
}
fn arrow_hw() -> f64 {
    ARROW_HW * ink_w()
}
fn line_inset() -> f64 {
    LINE_INSET * ink_w()
}
fn text_off() -> f64 {
    font_sz() / 2.0 + 2.0
}
pub const TEXT_OFF: f64 = 8.0;
pub const LINE_INSET: f64 = 2.0;

#[derive(Default)]
pub struct State {
    pub frames: HashMap<usize, Frame>,
    // every nested frame's centring shift: where its datum sits from its centre
    pub shifts: HashMap<usize, P>,
    // the first layout-time error (raised once measure is done)
    pub error: Option<Diag>,
}

#[derive(Clone, Debug)]
pub struct Frame {
    pub shift: P,
    pub items: Vec<Item>,
    pub bbox: BBox,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Kind {
    Line,
    Polyline,
    Polygon,
    Text,
    // an SVG path (`text` holds its data)
    Path,
    // a carried / generated node rendered by render_node at `pts[0]`
    Node(usize),
}

#[derive(Clone, Debug)]
pub struct Item {
    pub kind: Kind,
    // node classes after "lini-node" (e.g. "lini-ext-line lini-line")
    pub cls: String,
    pub pts: Vec<P>,
    pub text: String,
    pub rot: f64,
    pub size: Option<f64>,
    // eligible for halos where it crosses geometry
    pub halo: bool,
    // computed: (mask id, box, halo segments)
    pub mask: Option<(String, (f64, f64, f64, f64), Vec<(P, P)>)>,
    // extra element lines written inside the group after the main element
    pub extra: Vec<String>,
    // an arrow tip that lands on geometry (suppresses halos there)
    pub tip: Option<P>,
    // further points the halo mask box spans (a connector's marker tips)
    pub mask_pts: Vec<P>,
    // this line's own arrow tips: no halo under its arrowheads
    pub own_tips: Vec<P>,
    // a text's own inline style and the theme vars it reads
    pub css: String,
    pub css_vars: Vec<String>,
    // a styled text's measured box (width, height)
    pub wh: Option<(f64, f64)>,
    // nodes whose own outline the line does not halo (an extension line's
    // anchored node)
    pub own_nodes: Vec<usize>,
    // a text's size (its statement's)
    pub font: f64,
}

impl Item {
    fn new(kind: Kind, cls: &str, pts: Vec<P>) -> Item {
        Item { kind, cls: cls.to_string(), pts, text: String::new(), rot: 0.0, size: None, halo: false, mask: None, extra: vec![], tip: None, mask_pts: vec![], own_tips: vec![], css: String::new(), css_vars: vec![], wh: None, own_nodes: vec![], font: font_sz() }
    }
    fn text(p: P, s: &str, rot: f64, size: Option<f64>) -> Item {
        let mut it = Item::new(Kind::Text, "", vec![p]);
        it.text = s.to_string();
        it.rot = rot;
        it.size = size;
        it
    }
}

// ------------------------------------------------------------ helpers

type M = [f64; 6];
const IDENT: M = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];

fn mul(m: &M, n: &M) -> M {
    [
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    ]
}

fn apply(m: &M, p: P) -> P {
    pt(m[0] * p.x + m[2] * p.y + m[4], m[1] * p.x + m[3] * p.y + m[5])
}

fn apply_v(m: &M, v: P) -> P {
    pt(m[0] * v.x + m[2] * v.y, m[1] * v.x + m[3] * v.y)
}

// The matrix taking node i's group frame into frame f's datum frame.
fn to_frame(ctx: &Ctx, i: usize, f: usize) -> M {
    let mut chain = Vec::new();
    let mut cur = i;
    while cur != f {
        chain.push(cur);
        match ctx.nodes[cur].parent {
            Some(p) => cur = p,
            None => break,
        }
    }
    let mut m = IDENT;
    for &k in chain.iter().rev() {
        m = mul(&m, &crate::render::group_matrix(ctx, k));
    }
    m
}

// Numbers on drawings: two decimals at most, half away from zero.
pub fn fmt_val(v: f64) -> String {
    let r = (v.abs() * 100.0).round() / 100.0;
    let r = if v < 0.0 { -r } else { r };
    let mut s = format!("{:.2}", r);
    while s.contains('.') && s.ends_with('0') {
        s.pop();
    }
    if s.ends_with('.') {
        s.pop();
    }
    if s == "-0" {
        s = "0".into();
    }
    s
}

fn tw(ctx: &Ctx, f: usize, size: f64, s: &str) -> f64 {
    crate::font::text_width(ctx.comp[f].family, 400, size, s)
}

fn is_drawing_layout(lay: &str) -> bool {
    matches!(lay, "drawing" | "floorplan")
}

pub fn is_drawing(ctx: &Ctx, i: usize) -> bool {
    is_drawing_layout(ctx.comp[i].layout.as_str()) && !matches!(ctx.nodes[i].prim, Prim::Text | Prim::Line | Prim::Poly | Prim::Path | Prim::Sketch)
}

pub fn is_dim_op(op: &str) -> bool {
    matches!(op, "(-)" | "(o)" | "(<)")
}

fn prop<'a>(decls: &'a [(String, crate::ast::Value)], k: &str) -> Option<&'a crate::ast::Value> {
    decls.iter().rev().find(|d| d.0 == k).map(|d| &d.1)
}

fn stroke_w(ctx: &Ctx, i: usize) -> f64 {
    if ctx.comp[i].has_stroke {
        ctx.comp[i].stroke_width
    } else {
        0.0
    }
}

// ------------------------------------------------------------ statements

#[derive(Clone, Debug)]
struct St {
    links: Vec<usize>,
    op: String,
    span: Span,
    props: Vec<(String, crate::ast::Value)>,
    label: Option<String>,
    // `a <- [ "x" { … } ]`: bracketed texts with their own styling
    texts: Vec<(String, Vec<(String, crate::ast::Value)>)>,
}

impl St {
    fn get(&self, k: &str) -> Option<&crate::ast::Value> {
        prop(&self.props, k)
    }
    fn ident(&self, k: &str) -> Option<String> {
        self.get(k).and_then(ident_of).map(|s| s.to_string())
    }
}

// The annotation statements written directly in frame f, in source order.
fn statements(ctx: &Ctx, f: usize) -> Vec<St> {
    let mut by: Vec<(usize, Vec<usize>)> = Vec::new();
    for (li, l) in ctx.links.iter().enumerate() {
        if l.container != f {
            continue;
        }
        match by.iter_mut().find(|e| e.0 == l.stmt_index) {
            Some(e) => e.1.push(li),
            None => by.push((l.stmt_index, vec![li])),
        }
    }
    by.sort_by_key(|e| e.0);
    let mut out = Vec::new();
    for (_, links) in by {
        let l = &ctx.links[links[0]];
        let mut props: Vec<(String, crate::ast::Value)> = Vec::new();
        for c in &l.classes {
            if let Some(cr) = ctx.sheet.class(c) {
                for d in &cr.decls {
                    props.push((d.name.clone(), d.value.clone()));
                }
            }
        }
        for d in &l.style {
            props.push((d.name.clone(), d.value.clone()));
        }
        let mut texts = Vec::new();
        for s in &l.labels {
            if let crate::ast::Stmt::Text(t) = s {
                let mut tp: Vec<(String, crate::ast::Value)> = Vec::new();
                for c in &t.classes {
                    if let Some(cr) = ctx.sheet.class(c) {
                        for d in &cr.decls {
                            tp.push((d.name.clone(), d.value.clone()));
                        }
                    }
                }
                for d in t.style.iter().flatten() {
                    tp.push((d.name.clone(), d.value.clone()));
                }
                texts.push((t.text.clone(), tp));
            }
        }
        out.push(St { op: l.op.clone(), span: l.span, props, label: l.label.clone(), texts, links });
    }
    out
}

// ------------------------------------------------------------ references

#[derive(Clone, Debug)]
struct Ref {
    node: usize,
    p: P,
    // outward face normal (side anchors, tagged straight runs)
    n: Option<P>,
    // a straight run (tagged segment)
    run: Option<(P, P)>,
    // a tagged arc: centre, radius
    arc: Option<(P, f64)>,
    // no anchor: the node itself (a feature: hole, boss, wrapper)
    feature: bool,
    // pattern / mirror copies the feature stands for
    copies: usize,
    // read off a whole pattern (its copies counted, even one)
    pattern: bool,
    // a radial pattern read whole: its ring centre (the copies stand round it)
    ring: Option<P>,
    // the same run's twin across a revolve axis
    twin: Option<(P, P)>,
    // the sketch tag the anchor names
    tag: Option<String>,
}

fn side_dir(s: &str) -> Option<P> {
    Some(match s {
        "top" => pt(0.0, -1.0),
        "bottom" => pt(0.0, 1.0),
        "left" => pt(-1.0, 0.0),
        "right" => pt(1.0, 0.0),
        _ => return None,
    })
}

fn corner_dir(s: &str) -> Option<P> {
    Some(match s {
        "top-left" => pt(-1.0, -1.0),
        "top-right" => pt(1.0, -1.0),
        "bottom-left" => pt(-1.0, 1.0),
        "bottom-right" => pt(1.0, 1.0),
        "center" => pt(0.0, 0.0),
        _ => return None,
    })
}

fn is_wrapper(ctx: &Ctx, i: usize) -> bool {
    ctx.sk.wrappers.contains_key(&i)
}

fn copies_of(ctx: &Ctx, i: usize) -> Vec<usize> {
    ctx.nodes[i].children.iter().copied().filter(|c| !ctx.sk.chrome.contains_key(c)).collect()
}

// A segment's own geometry mapped into the frame.
fn map_seg(m: &M, g: &Seg) -> Seg {
    g.map(&|p| apply(m, p), m[0] * m[3] - m[1] * m[2] < 0.0)
}

fn resolve(ctx: &Ctx, f: usize, node: usize, anchor: Option<&str>, index: Option<u32>) -> Result<Ref, String> {
    let mut i = node;
    let mut copies = 1;
    let name = ctx.nodes[node].id.clone().unwrap_or_default();
    if is_wrapper(ctx, i) {
        let cs = copies_of(ctx, i);
        match index {
            Some(k) => match crate::drawing::pattern_copy(ctx, i, k as usize) {
                Some(c) if k >= 1 => i = c,
                _ => return Err(format!("no copy '{}.{}' — the replication places {}", name, k, cs.len())),
            },
            None => {
                copies = cs.len();
                if let Some(&c) = cs.first() {
                    i = c;
                }
            }
        }
    } else if index.is_some() {
        return Err(format!("'{}' has no copies — a numeric segment picks a replication copy", name));
    }
    let m = to_frame(ctx, i, f);
    let n = &ctx.nodes[i];
    let c = pt(-n.geo_off.0, -n.geo_off.1);
    let (hw, hh) = (n.w / 2.0, n.h / 2.0);
    let mut r = Ref { node: i, p: apply(&m, c), n: None, run: None, arc: None, feature: false, copies, pattern: is_wrapper(ctx, node) && index.is_none(), ring: None, twin: None, tag: None };
    // a radial pattern is located by its ring centre (a grid by its first copy)
    if r.pattern && anchor.is_none() {
        if let Some(w) = ctx.sk.wrappers.get(&node) {
            if let Some(&(ox, oy)) = w.offsets.first() {
                if ox != 0.0 || oy != 0.0 {
                    let k = crate::drawing::ps(ctx, f);
                    let centre = r.p.sub(apply_v(&to_frame(ctx, node, f), pt(ox * k, oy * k)));
                    r.p = centre;
                    r.ring = Some(centre);
                }
            }
        }
    }
    let a = match anchor {
        None => {
            r.feature = true;
            return Ok(r);
        }
        Some(a) => a,
    };
    // a sketch's own names come first
    if n.prim == Prim::Sketch {
        let drawn = crate::drawing::drawn_tags(ctx, i);
        let laid = crate::drawing::sketch_tags(ctx, i);
        let mut found: Vec<&crate::sketch::Tag> = drawn.iter().filter(|t| t.name == a).collect();
        let laid_found: Vec<&crate::sketch::Tag> = laid.iter().filter(|t| t.name == a).collect();
        // arcs (fillets) only exist laid out
        if found.is_empty() || laid_found.iter().any(|t| matches!(&t.kind, TagKind::Seg(Seg::Arc { .. }))) {
            found = laid_found;
        }
        // a run a break split names each of its pieces: they read as one
        let merged;
        if found.len() > 1 && found.iter().all(|t| matches!(&t.kind, TagKind::Seg(Seg::Line { .. }))) {
            let mut lo: Option<(f64, P)> = None;
            let mut hi: Option<(f64, P)> = None;
            let d = match &found[0].kind {
                TagKind::Seg(g) => g.end().sub(g.start()).unit(),
                _ => pt(1.0, 0.0),
            };
            for t in &found {
                if let TagKind::Seg(g) = &t.kind {
                    for q in [g.start(), g.end()] {
                        let v = q.dot(d);
                        if lo.map(|l| v < l.0).unwrap_or(true) {
                            lo = Some((v, q));
                        }
                        if hi.map(|h| v > h.0).unwrap_or(true) {
                            hi = Some((v, q));
                        }
                    }
                }
            }
            merged = crate::sketch::Tag { name: a.to_string(), kind: TagKind::Seg(Seg::Line { a: lo.unwrap().1, b: hi.unwrap().1 }) };
            found = vec![&merged];
        }
        if let Some(t) = found.first() {
            r.tag = Some(a.to_string());
            match &t.kind {
                TagKind::Point(q) => {
                    r.p = apply(&m, *q);
                }
                TagKind::Seg(g0) => {
                    // a revolved profile's run has a twin across the axis
                    if let Some(d) = revolve_dir(ctx, i) {
                        let refl = |p: P| {
                            let k = 2.0 * p.dot(d);
                            pt(d.x * k - p.x, d.y * k - p.y)
                        };
                        let tw = g0.map(&refl, true);
                        let tw = map_seg(&m, &tw);
                        r.twin = Some((tw.start(), tw.end()));
                    }
                    let g = map_seg(&m, g0);
                    match &g {
                        Seg::Line { a, b } => {
                            r.p = a.add(*b).mul(0.5);
                            r.run = Some((*a, *b));
                            let d = b.sub(*a).unit();
                            // the material side is unknown here: the normal points away from the node's box centre
                            let mut nn = pt(-d.y, d.x);
                            if nn.dot(r.p.sub(apply(&m, c))) < 0.0 {
                                nn = nn.mul(-1.0);
                            }
                            r.n = Some(nn);
                        }
                        Seg::Arc { c: cc, r: rr, .. } => {
                            let mid = arc_mid(&g);
                            r.p = mid;
                            r.arc = Some((*cc, *rr));
                        }
                        Seg::Cubic { .. } => {
                            r.p = seg_point(&g, 0.5);
                        }
                    }
                }
            }
            return Ok(r);
        }
    }
    if let Some(d) = side_dir(a) {
        let local = pt(c.x + d.x * hw, c.y + d.y * hh);
        r.p = apply(&m, local);
        r.n = Some(apply_v(&m, d).unit());
        let t = pt(-d.y, d.x);
        let (ea, eb) = (pt(local.x - t.x * hw, local.y - t.y * hh), pt(local.x + t.x * hw, local.y + t.y * hh));
        r.run = Some((apply(&m, ea), apply(&m, eb)));
        return Ok(r);
    }
    if let Some(d) = corner_dir(a) {
        r.p = apply(&m, pt(c.x + d.x * hw, c.y + d.y * hh));
        return Ok(r);
    }
    // a sketch suggests its own names
    let mut names: Vec<String> = Vec::new();
    if n.prim == Prim::Sketch {
        for t in crate::drawing::sketch_tags(ctx, i) {
            let s = format!(":{}", t.name);
            if !names.contains(&s) {
                names.push(s);
            }
        }
    }
    Err(format!("no segment ':{}' on '{}'{}", a, name, crate::drawing::suggest(&format!(":{}", a), &names)))
}

// A run's reflection across its sketch's mirror axis (through the draw
// origin), in frame coordinates.
fn mirror_twin(ctx: &Ctx, f: usize, r: &Ref) -> Option<(P, P)> {
    let (a, b) = r.run?;
    let d = match ctx.nodes[r.node].props.get("mirror").and_then(ident_of) {
        Some("x-axis") => pt(1.0, 0.0),
        Some("y-axis") => pt(0.0, -1.0),
        _ => return None,
    };
    let m = to_frame(ctx, r.node, f);
    let o = apply(&m, pt(0.0, 0.0));
    let dd = apply_v(&m, d).unit();
    let refl = |p: P| {
        let v = p.sub(o);
        let k = 2.0 * v.dot(dd);
        o.add(dd.mul(k)).sub(v)
    };
    Some((refl(a), refl(b)))
}

fn revolve_dir(ctx: &Ctx, i: usize) -> Option<P> {
    match ctx.nodes[i].props.get("revolve").and_then(ident_of) {
        Some("x-axis") => Some(pt(1.0, 0.0)),
        Some("y-axis") => Some(pt(0.0, -1.0)),
        _ => None,
    }
}

fn arc_mid(g: &Seg) -> P {
    seg_point(g, 0.5)
}

// The point at parameter t along a segment.
fn seg_point(g: &Seg, t: f64) -> P {
    match g {
        Seg::Line { a, b } => a.add(b.sub(*a).mul(t)),
        Seg::Arc { a, c, sweep, .. } => {
            let v = a.sub(*c);
            let ang = sweep * t;
            let (s, co) = ang.sin_cos();
            c.add(pt(v.x * co - v.y * s, v.x * s + v.y * co))
        }
        Seg::Cubic { a, c1, c2, b } => {
            let u = 1.0 - t;
            let w0 = u * u * u;
            let w1 = 3.0 * u * u * t;
            let w2 = 3.0 * u * t * t;
            let w3 = t * t * t;
            pt(w0 * a.x + w1 * c1.x + w2 * c2.x + w3 * b.x, w0 * a.y + w1 * c1.y + w2 * c2.y + w3 * b.y)
        }
    }
}

// ------------------------------------------------------------ dimension text

#[derive(Clone, Debug, Default)]
struct DimText {
    main: String,
    // stacked deviations (upper, lower)
    stack: Option<(String, String)>,
    // measured widths
    w_main: f64,
    w_stack: f64,
    // a stacked fraction after the whole part: (numerator, denominator) and
    // the widths of numerator, slash, denominator
    frac: Option<(String, String)>,
    w_frac: (f64, f64, f64),
}

impl DimText {
    fn width(&self) -> f64 {
        let main = match &self.frac {
            Some(_) => {
                let gap = if self.main.is_empty() { 0.0 } else { 1.0 };
                self.w_main + gap + self.w_frac.0 + self.w_frac.1 + self.w_frac.2
            }
            None => self.w_main,
        };
        match &self.stack {
            Some(_) => main + 2.0 + self.w_stack,
            None => main,
        }
    }
    // half extent across the reading direction
    fn half_h(&self) -> f64 {
        match &self.stack {
            Some(_) => (font_sz() / 2.0).max(1.1 * font_sz() * TOL_STACK / 2.0 + font_sz() * TOL_STACK / 2.0),
            None => font_sz() / 2.0,
        }
    }
}

fn dev(v: f64) -> String {
    let s = fmt_val(v);
    if s == "0" {
        s
    } else if v > 0.0 {
        format!("+{}", s)
    } else {
        s
    }
}

// The value text with its tolerance (`tol:`) and `format:`.
fn dim_text(ctx: &Ctx, f: usize, st: &St, value: f64, prefix: &str) -> Result<DimText, Diag> {
    dim_text_sfx(ctx, f, st, value, prefix, "")
}

// … with a unit sign right after the number (an angle's °).
fn dim_text_sfx(ctx: &Ctx, f: usize, st: &St, value: f64, prefix: &str, suffix: &str) -> Result<DimText, Diag> {
    let fmt = match st.get("format") {
        Some(v) => Some(crate::chart::model::parse_fmt(v, st.span)?),
        None => None,
    };
    // a fraction stacks its numerator over its denominator
    let mut frac = None;
    let number = match &fmt {
        Some(crate::chart::model::Fmt::Fraction(_)) => {
            let s = crate::chart::scale::fmt_with(value, fmt.as_ref()).unwrap_or_default();
            let (whole, part) = match s.rsplit_once(' ') {
                Some((w, p)) => (w.to_string(), Some(p.to_string())),
                None if s.contains('/') => (String::new(), Some(s.clone())),
                None => (s.clone(), None),
            };
            if let Some(p) = part {
                if let Some((n, d)) = p.split_once('/') {
                    frac = Some((n.to_string(), d.to_string()));
                }
            }
            whole
        }
        Some(crate::chart::model::Fmt::Auto) | None => fmt_val(value),
        Some(_) => crate::chart::scale::fmt_with(value, fmt.as_ref()).unwrap_or_else(|| fmt_val(value)),
    };
    // a plain dimension's label stands for its number (the tolerance follows)
    let replaced = prefix.is_empty() && suffix.is_empty() && st.label.is_some();
    let mut main = if replaced {
        frac = None;
        st.label.clone().unwrap_or_default()
    } else if number.is_empty() && frac.is_some() {
        prefix.to_string()
    } else {
        format!("{}{}{}", prefix, number, suffix)
    };
    // otherwise the label follows the value; the tolerance comes last
    if let Some(l) = &st.label {
        if !replaced {
            main = format!("{} {}", main, l);
        }
    }
    let mut stack = None;
    if let Some(v) = st.get("tol") {
        if v.groups.len() > 1 {
            return Err(Diag::error("layout", "'tol' takes one value, not a comma list", v.span));
        }
        let terms = &v.groups[0];
        let bad = || Diag::error("layout", "'tol' takes a number, '+upper -lower', or a fit ident", st.span);
        let nums: Vec<f64> = terms.iter().filter_map(|t| crate::style::term_num(&ctx.sheet.env, t)).collect();
        if terms.len() == 1 && nums.len() == 1 {
            main = format!("{}±{}", main, fmt_val(nums[0]));
        } else if terms.len() == 2 && nums.len() == 2 {
            stack = Some((dev(nums[0]), dev(nums[1])));
        } else if terms.len() == 1 {
            match &terms[0] {
                crate::ast::Term::Ident(s, _) => main = format!("{} {}", main, s),
                _ => return Err(bad()),
            }
        } else {
            return Err(bad());
        }
    }
    let w_main = tw(ctx, f, font_sz(), &main);
    let w_stack = match &stack {
        Some((a, b)) => tw(ctx, f, font_sz() * TOL_STACK, a).max(tw(ctx, f, font_sz() * TOL_STACK, b)),
        None => 0.0,
    };
    let w_frac = match &frac {
        Some((n, d)) => (tw(ctx, f, font_sz() * TOL_STACK, n), tw(ctx, f, font_sz(), "/"), tw(ctx, f, font_sz() * TOL_STACK, d)),
        None => (0.0, 0.0, 0.0),
    };
    let w_main = if main.is_empty() { 0.0 } else { w_main };
    Ok(DimText { main, stack, w_main, w_stack, frac, w_frac })
}

// Text items for a dimension text centred at c, reading along r (unit).
fn text_items(t: &DimText, c: P, r: P, rot: f64) -> Vec<Item> {
    let up = pt(r.y, -r.x);
    if let Some((num, den)) = &t.frac {
        // the whole part, then the numerator raised, a slash, the
        // denominator lowered — the lot centred
        let w = t.width();
        let k = 1.1 * font_sz() * TOL_STACK / 2.0;
        let sz = Some(font_sz() * TOL_STACK);
        let mut x = -w / 2.0;
        let mut out = Vec::new();
        if !t.main.is_empty() {
            out.push(Item::text(c.add(r.mul(x + t.w_main / 2.0)), &t.main, rot, None));
            x += t.w_main + 1.0;
        }
        let (wn, ws, wd) = t.w_frac;
        out.push(Item::text(c.add(r.mul(x + wn / 2.0)).add(up.mul(k)), num, rot, sz));
        x += wn;
        out.push(Item::text(c.add(r.mul(x + ws / 2.0)), "/", rot, None));
        x += ws;
        out.push(Item::text(c.add(r.mul(x + wd / 2.0)).sub(up.mul(k)), den, rot, sz));
        return out;
    }
    match &t.stack {
        None => vec![Item::text(c, &t.main, rot, None)],
        Some((a, b)) => {
            let w = t.width();
            let cm = c.sub(r.mul(w / 2.0 - t.w_main / 2.0));
            let cs = c.add(r.mul(w / 2.0 - t.w_stack / 2.0));
            let k = 1.1 * font_sz() * TOL_STACK / 2.0;
            let sz = Some(font_sz() * TOL_STACK);
            vec![
                Item::text(cm, &t.main, rot, None),
                Item::text(cs.add(up.mul(k)), a, rot, sz),
                Item::text(cs.sub(up.mul(k)), b, rot, sz),
            ]
        }
    }
}

fn arrow(tip: P, d: P) -> Vec<P> {
    // d: from the tip toward the arrow's base
    let base = tip.add(d.mul(arrow_l()));
    let l = pt(d.y, -d.x);
    vec![tip, base.add(l.mul(arrow_hw())), base.sub(l.mul(arrow_hw()))]
}

// ------------------------------------------------------------ linear dimensions

#[derive(Clone, Copy, Debug, PartialEq)]
enum Axis {
    X,
    Y,
    // aligned: the unit direction a → b
    A(P),
}

struct Layout {
    geo: BBox,
    // leader notes etc. that dimension rows clear
    obstacles: Vec<BBox>,
    // the bands of the dimensions laid so far (what an aligned one clears),
    // as outlines
    bands: Vec<Vec<P>>,
    // the last dimension laid was aligned (its band is in already)
    aligned_last: bool,
    // annotation nodes standing in the frame (placed or seated)
    nodes: Vec<BBox>,
    // arrow tips landing on geometry
    tips: Vec<P>,
}

impl Layout {
    fn new(geo: BBox) -> Layout {
        Layout { geo, obstacles: vec![], bands: vec![], aligned_last: false, nodes: vec![], tips: vec![] }
    }
    // what a leader's note clears: the geometry by NOTE_OFFSET, annotation
    // nodes and other notes by CLEAR
    fn leader_obs(&self) -> Vec<(BBox, f64)> {
        let mut v = vec![(self.geo, NOTE_OFFSET)];
        for b in self.nodes.iter().chain(self.obstacles.iter()) {
            v.push((*b, CLEAR));
        }
        v
    }
}

fn outward(side: &str) -> P {
    side_dir(side).unwrap_or(pt(0.0, 1.0))
}

fn side_static(s: &str) -> &'static str {
    match s {
        "top" => "top",
        "left" => "left",
        "right" => "right",
        _ => "bottom",
    }
}

// Where a band `th` thick over the span lo..hi starts along a side's
// outward axis: the nearest place CLEAR past the geometry that stands CLEAR
// off everything laid over the span (dimensions, notes, annotation nodes) —
// a gap nearer the part takes it.
fn slot(lay: &Layout, side: &str, lo: f64, hi: f64, th: f64) -> f64 {
    let across = matches!(side, "top" | "bottom");
    let out = |b: &BBox| match side {
        "top" => (-b.y1, -b.y0),
        "left" => (-b.x1, -b.x0),
        "right" => (b.x0, b.x1),
        _ => (b.y0, b.y1),
    };
    let mut ivs = Vec::new();
    for b in lay.obstacles.iter().chain(lay.nodes.iter()) {
        let (a0, a1) = if across { (b.x0, b.x1) } else { (b.y0, b.y1) };
        if !b.is_empty() && a0 < hi && lo < a1 {
            ivs.push(out(b));
        }
    }
    let mut near = if lay.geo.is_empty() { 0.0 } else { out(&lay.geo).1 } + CLEAR;
    loop {
        let mut moved = false;
        for &(o0, o1) in &ivs {
            if o0 < near + th + CLEAR && near - CLEAR < o1 {
                near = o1 + CLEAR;
                moved = true;
            }
        }
        if !moved {
            return near;
        }
    }
}

fn dim_axis(a: &Ref, b: &Ref, project: Option<&str>) -> Result<Axis, String> {
    match project {
        Some("horizontal") => return Ok(Axis::X),
        Some("vertical") => return Ok(Axis::Y),
        _ => {}
    }
    let pick = |n: P| if n.x.abs() > n.y.abs() { Axis::X } else { Axis::Y };
    match (a.n, b.n) {
        (Some(na), Some(nb)) => {
            if na.cross(nb).abs() < 1e-6 {
                Ok(pick(na))
            } else {
                Err("perp".into())
            }
        }
        (Some(na), None) => Ok(pick(na)),
        (None, Some(nb)) => Ok(pick(nb)),
        (None, None) => {
            let d = b.p.sub(a.p);
            if d.y.abs() < 1e-6 {
                Ok(Axis::X)
            } else if d.x.abs() < 1e-6 {
                Ok(Axis::Y)
            } else {
                Ok(Axis::A(d.unit()))
            }
        }
    }
}

// What a break folded out of a measured span: both anchors on one broken
// sketch, either side of the cut.
fn break_extra(ctx: &Ctx, f: usize, a: &Ref, b: &Ref, ax: Axis) -> f64 {
    let mut owner = None;
    for r in [a, b] {
        let mut cur = Some(r.node);
        let mut found = None;
        while let Some(c) = cur {
            if c == f {
                break;
            }
            if ctx.sk.laid.get(&c).map(|l| l.brk.is_some()).unwrap_or(false) {
                found = Some(c);
                break;
            }
            cur = ctx.nodes[c].parent;
        }
        match (owner, found) {
            (None, Some(s)) => owner = Some(s),
            (Some(o), Some(s)) if o == s => {}
            _ => return 0.0,
        }
    }
    let s = match owner {
        Some(s) => s,
        None => return 0.0,
    };
    let (along_x, ca, _cb, shift) = ctx.sk.laid[&s].brk.unwrap();
    if (along_x && ax != Axis::X) || (!along_x && ax != Axis::Y) {
        return 0.0;
    }
    let inv = match invert(&to_frame(ctx, s, f)) {
        Some(m) => m,
        None => return 0.0,
    };
    let (pa, pb) = (apply(&inv, a.p), apply(&inv, b.p));
    let (va, vb) = if along_x { (pa.x, pb.x) } else { (pa.y, pb.y) };
    let (lo, hi) = (va.min(vb), va.max(vb));
    if lo <= ca + 1e-9 && hi >= ca + crate::drawing::BREAK_GAP_PX - 1e-9 {
        shift
    } else {
        0.0
    }
}

fn along(ax: Axis, p: P) -> f64 {
    match ax {
        Axis::X => p.x,
        Axis::Y => p.y,
        Axis::A(d) => p.dot(d),
    }
}

struct Lin {
    a: Ref,
    b: Ref,
    li: usize,
}

fn lay_linear(ctx: &Ctx, f: usize, st: &St, lins: &[Lin], lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    lay_linear_pref(ctx, f, st, lins, lay, out, "")
}

fn lay_linear_pref(ctx: &Ctx, f: usize, st: &St, lins: &[Lin], lay: &mut Layout, out: &mut Vec<Item>, prefix: &str) -> Result<(), Diag> {
    if lins.is_empty() {
        return Ok(());
    }
    let project = st.ident("project");
    let ax = match dim_axis(&lins[0].a, &lins[0].b, project.as_deref()) {
        Ok(a) => a,
        Err(_) => {
            let l = &ctx.links[lins[0].li];
            let name = |n: usize, a: &Option<String>| {
                let p = crate::links::path_of(ctx, n);
                match a {
                    Some(a) => format!("{}:{}", p, a),
                    None => p,
                }
            };
            let msg = format!(
                "'{} (-) {}' — perpendicular faces have no shared normal; the angle between edges is '(<)'",
                name(l.from, &l.from_anchor),
                name(l.to, &l.to_anchor)
            );
            return Err(Diag::error("layout", &msg, st.span));
        }
    };
    let k = crate::drawing::ps(ctx, f);
    let want = st.ident("side");
    if let Axis::A(_) = ax {
        if want.as_deref().map(|s| s != "left" && s != "right").unwrap_or(false) {
            return Err(Diag::error("layout", "an aligned dimension sits left or right of its span — read along it, first anchor to second", st.span));
        }
        for lin in lins {
            lay_aligned(ctx, f, st, lin, k, lay, out)?;
        }
        return Ok(());
    }
    match (ax, want.as_deref()) {
        (Axis::X, Some(s)) if s != "top" && s != "bottom" => {
            return Err(Diag::error("layout", "a horizontal dimension stacks on top or bottom", st.span));
        }
        (Axis::Y, Some(s)) if s != "left" && s != "right" => {
            return Err(Diag::error("layout", "a vertical dimension stacks on left or right", st.span));
        }
        _ => {}
    }
    let side: &'static str = match st.ident("side") {
        Some(s) => side_static(&s),
        None => {
            if ax == Axis::X {
                "bottom"
            } else {
                "right"
            }
        }
    };
    let o = outward(side);
    // texts first: the row band depends on them
    let mut texts = Vec::new();
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    for lin in lins {
        let (pa, pb) = (along(ax, lin.a.p), along(ax, lin.b.p));
        let extra = break_extra(ctx, f, &lin.a, &lin.b, ax);
        let t = dim_text(ctx, f, st, ((pb - pa).abs() + extra) / k, prefix)?;
        lo = lo.min(pa.min(pb));
        hi = hi.max(pa.max(pb));
        texts.push(t);
    }
    let carried = carried_nodes(ctx, f, st.span);
    // the band about the dim line along the outward axis, from a probe layout
    let probe = linear_items(ctx, f, ax, o, lins, &texts, &carried, 0.0);
    let (mut smin, mut smax) = (f64::INFINITY, f64::NEG_INFINITY);
    // the row a dimension takes along its axis: its line, arrows and text
    let axis_u = if ax == Axis::X { pt(1.0, 0.0) } else { pt(0.0, 1.0) };
    let (mut alo, mut ahi) = (f64::INFINITY, f64::NEG_INFINITY);
    for it in &probe {
        // the extension lines stay out of the band; a tolerance stack only
        // reaches its far edge
        if it.cls.contains("lini-ext-line") {
            continue;
        }
        let stack = it.kind == Kind::Text && it.size.is_some();
        let mut b = BBox::empty();
        item_bbox(ctx, f, it, &mut b);
        if let Kind::Node(i) = it.kind {
            node_box_at(ctx, i, it.pts[0], &mut b);
        }
        if b.is_empty() {
            continue;
        }
        for (x, y) in [(b.x0, b.y0), (b.x1, b.y1)] {
            let s = pt(x, y).dot(o);
            smax = smax.max(s);
            if stack {
                continue;
            }
            smin = smin.min(s);
            let a = pt(x, y).dot(axis_u);
            alo = alo.min(a);
            ahi = ahi.max(a);
        }
    }
    if !alo.is_finite() {
        alo = lo;
        ahi = hi;
    }
    smax = smax.max(EXT_OVER);
    let ls = slot(lay, side, alo, ahi, smax - smin) - smin;
    // the dim line's position in frame coordinates
    let lpos = match side {
        "top" | "left" => -ls,
        _ => ls,
    };
    out.extend(linear_items(ctx, f, ax, o, lins, &texts, &carried, lpos));
    Ok(())
}

// A dimension's band: its lines, arrows and texts, and the extension lines'
// overshoot (not their runs back to the anchors).
fn band_box(ctx: &Ctx, f: usize, items: &[Item]) -> BBox {
    let mut b = BBox::empty();
    for it in items {
        if it.cls.contains("lini-ext-line") {
            if let Some(e) = it.pts.last() {
                b.add(e.x, e.y);
            }
            continue;
        }
        item_bbox(ctx, f, it, &mut b);
    }
    b
}

// A carried node's outer box with its datum at `at`.
fn node_box_at(ctx: &Ctx, i: usize, at: P, b: &mut BBox) {
    let n = &ctx.nodes[i];
    let sw = stroke_w(ctx, i);
    let (w, h) = (n.w + sw, n.h + sw);
    let c = pt(at.x - n.geo_off.0, at.y - n.geo_off.1);
    b.add(c.x - w / 2.0, c.y - h / 2.0);
    b.add(c.x + w / 2.0, c.y + h / 2.0);
}

// Carried nodes stack under a text (screen-down), 3 apart: their datums.
fn stack_under(ctx: &Ctx, carried: &[usize], c: P, half_y: f64) -> Vec<Item> {
    let mut y = c.y + half_y + 3.0;
    let mut out = Vec::new();
    for &i in carried {
        let n = &ctx.nodes[i];
        let sw = stroke_w(ctx, i);
        let h = n.h + sw;
        let center = pt(c.x, y + h / 2.0);
        let at = pt(center.x + n.geo_off.0, center.y + n.geo_off.1);
        let mut it = Item::new(Kind::Node(i), "lini-carried", vec![at]);
        it.halo = false;
        out.push(it);
        y += h + 3.0;
    }
    out
}

fn linear_items(ctx: &Ctx, f: usize, ax: Axis, o: P, lins: &[Lin], texts: &[DimText], carried: &[usize], lpos: f64) -> Vec<Item> {
    let mut out = Vec::new();
    for (k, (lin, t)) in lins.iter().zip(texts.iter()).enumerate() {
        let on_line = |p: P| -> P {
            match ax {
                Axis::X => pt(p.x, lpos),
                _ => pt(lpos, p.y),
            }
        };
        let (a, b) = (&lin.a, &lin.b);
        let lk = &ctx.links[lin.li];
        // extension lines: a tagged run along them starts at its end nearest the row
        for (r, own) in [(a, lk.from), (b, lk.to)] {
            let q = on_line(r.p);
            let from = match (&r.tag, r.run) {
                (Some(_), Some((r0, r1))) if r1.sub(r0).unit().cross(o).abs() < 1e-9 => {
                    if r0.dot(o) > r1.dot(o) {
                        r0
                    } else {
                        r1
                    }
                }
                _ => r.p,
            };
            let s = from.add(o.mul(EXT_GAP));
            let e = q.add(o.mul(EXT_OVER));
            let mut it = Item::new(Kind::Line, "lini-ext-line", vec![s, e]);
            it.halo = true;
            it.own_nodes = vec![own];
            out.push(it);
        }
        // the dim line and its arrows run in increasing x / y
        let (qa, qb) = {
            let (p1, p2) = (on_line(a.p), on_line(b.p));
            if along(ax, p1) <= along(ax, p2) {
                (p1, p2)
            } else {
                (p2, p1)
            }
        };
        let axis_u = if ax == Axis::X { pt(1.0, 0.0) } else { pt(0.0, 1.0) };
        let span = qb.sub(qa).len();
        let u = if span > 1e-9 { qb.sub(qa).unit() } else { axis_u };
        let tw_all = t.width();
        let inside = span >= tw_all + 30.0;
        let (l0, l1) = if inside { (qa.add(u.mul(line_inset())), qb.sub(u.mul(line_inset()))) } else { (qa.sub(u.mul(arrow_l() + line_inset())), qb.add(u.mul(arrow_l() + line_inset()))) };
        let mut dl = Item::new(Kind::Line, "lini-dim-line", vec![l0, l1]);
        dl.halo = true;
        dl.own_tips = vec![qa, qb];
        out.push(dl);
        let (da, db) = if inside { (u, u.mul(-1.0)) } else { (u.mul(-1.0), u) };
        let mut m1 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(qa, da));
        m1.tip = Some(qa);
        out.push(m1);
        let mut m2 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(qb, db));
        m2.tip = Some(qb);
        out.push(m2);
        // the text: reading left to right / bottom to top
        let (r, rot) = if ax == Axis::X { (pt(1.0, 0.0), 0.0) } else { (pt(0.0, -1.0), -90.0) };
        let up = pt(r.y, -r.x);
        let text_inside = span >= tw_all + 4.0;
        let mid = qa.add(qb).mul(0.5);
        let c = if text_inside {
            mid
        } else {
            // past the end the reading runs toward
            let (tip, dir) = if r.dot(u) >= 0.0 { (qb, u) } else { (qa, u.mul(-1.0)) };
            let end = tip.add(dir.mul(arrow_l() + line_inset() + 4.0));
            end.add(dir.mul(tw_all / 2.0))
        };
        let tc = c.add(up.mul(text_off()));
        out.extend(text_items(t, tc, r, rot));
        if k == 0 && !carried.is_empty() {
            let half_y = if ax == Axis::X { t.half_h() } else { tw_all / 2.0 };
            out.extend(stack_under(ctx, carried, tc, half_y));
        }
        let _ = f;
    }
    out
}
// A dimension along two point anchors' own line: offset to the anchor
// line's left, clear of the anchors alone.
fn lay_aligned(ctx: &Ctx, f: usize, st: &St, lin: &Lin, k: f64, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let (a, b) = (&lin.a, &lin.b);
    let n0 = out.len();
    let d = b.p.sub(a.p).unit();
    // the reading runs left to right; the dimension stands on its upper side
    let mut r = d;
    if r.x < -1e-9 || (r.x.abs() <= 1e-9 && r.y > 0.0) {
        r = r.mul(-1.0);
    }
    let up = pt(r.y, -r.x);
    let t = dim_text(ctx, f, st, b.p.sub(a.p).len() / k, "")?;
    // `side:` reads along the span, first anchor to second; by default the
    // dimension stands on the text's side
    let o = match st.ident("side").as_deref() {
        Some("left") => pt(d.y, -d.x),
        Some("right") => pt(-d.y, d.x),
        _ => {
            // away from the geometry's centre (the text's side on a tie)
            let g = &lay.geo;
            let gc = pt((g.x0 + g.x1) / 2.0, (g.y0 + g.y1) / 2.0);
            let mid = a.p.add(b.p).mul(0.5);
            if !g.is_empty() && gc.sub(mid).dot(up) > 1e-9 {
                up.mul(-1.0)
            } else {
                up
            }
        }
    };
    // the text sits on the dimension's far side, or between it and the span
    let inner = if o.dot(up) > 0.0 { arrow_hw() } else { text_off() + t.half_h() };
    let mut off = CLEAR + inner;
    // the dimensions already laid stand in its way: it stands CLEAR off them
    let (s0, s1) = {
        let (x, y) = (a.p.dot(d), b.p.dot(d));
        (x.min(y), x.max(y))
    };
    for bx in &lay.bands {
        // the part of the band over the span (clipped to the slab)
        let mut poly = bx.clone();
        for (lim, keep_above) in [(s0, true), (s1, false)] {
            let inside = |q: &P| if keep_above { q.dot(d) >= lim - 1e-9 } else { q.dot(d) <= lim + 1e-9 };
            let mut next = Vec::new();
            for k in 0..poly.len() {
                let (p0, p1) = (poly[k], poly[(k + 1) % poly.len()]);
                let (i0, i1) = (inside(&p0), inside(&p1));
                if i0 {
                    next.push(p0);
                }
                if i0 != i1 {
                    let (a0, a1) = (p0.dot(d), p1.dot(d));
                    if (a1 - a0).abs() > 1e-12 {
                        let t = (lim - a0) / (a1 - a0);
                        next.push(p0.add(p1.sub(p0).mul(t)));
                    }
                }
            }
            poly = next;
            if poly.is_empty() {
                break;
            }
        }
        if poly.len() < 2 {
            continue;
        }
        // in the way when it comes within CLEAR of the dimension's band
        let omin = poly.iter().map(|c| c.sub(a.p).dot(o)).fold(f64::INFINITY, f64::min);
        let omax = poly.iter().map(|c| c.sub(a.p).dot(o)).fold(f64::NEG_INFINITY, f64::max);
        let outer_w = if o.dot(up) > 0.0 { (text_off() + t.half_h()).max(EXT_OVER) } else { EXT_OVER.max(arrow_hw()) };
        if omax > 0.0 && omin < off + outer_w + CLEAR && omax > off - inner - CLEAR {
            off = off.max(omax + CLEAR + inner);
        }
    }
    let lk = &ctx.links[lin.li];
    for (e, own) in [(a, lk.from), (b, lk.to)] {
        let mut it = Item::new(Kind::Line, "lini-ext-line", vec![e.p.add(o.mul(EXT_GAP)), e.p.add(o.mul(off + EXT_OVER))]);
        it.halo = true;
        it.own_nodes = vec![own];
        out.push(it);
    }
    // the dim line and its arrows from the left end to the right
    let (pl, pr) = if r.dot(d) > 0.0 { (a.p, b.p) } else { (b.p, a.p) };
    let (qa, qb) = (pl.add(o.mul(off)), pr.add(o.mul(off)));
    let span = qb.sub(qa).len();
    let u = r;
    let inside = span >= t.width() + 30.0;
    let (l0, l1) = if inside { (qa.add(u.mul(line_inset())), qb.sub(u.mul(line_inset()))) } else { (qa.sub(u.mul(arrow_l() + line_inset())), qb.add(u.mul(arrow_l() + line_inset()))) };
    let mut dl = Item::new(Kind::Line, "lini-dim-line", vec![l0, l1]);
    dl.halo = true;
    dl.own_tips = vec![qa, qb];
    out.push(dl);
    let (da, db) = if inside { (u, u.mul(-1.0)) } else { (u.mul(-1.0), u) };
    let mut m1 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(qa, da));
    m1.tip = Some(qa);
    out.push(m1);
    let mut m2 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(qb, db));
    m2.tip = Some(qb);
    out.push(m2);
    let rot = r.y.atan2(r.x).to_degrees();
    let mid = qa.add(qb).mul(0.5);
    out.extend(text_items(&t, mid.add(up.mul(text_off())), r, rot));
    // later rows stand off it: its band along the whole line, from the
    // arrows' (or the text's) inner edge to the text's (or the overshoot's)
    // outer one
    let (inner_w, outer_w) = if o.dot(up) > 0.0 { (arrow_hw(), (text_off() + t.half_h()).max(EXT_OVER)) } else { (text_off() + t.half_h(), EXT_OVER.max(arrow_hw())) };
    let mut bb = band_box(ctx, f, &out[n0..]);
    let band = vec![qa.sub(o.mul(inner_w)), qb.sub(o.mul(inner_w)), qb.add(o.mul(outer_w)), qa.add(o.mul(outer_w))];
    for c in &band {
        bb.add(c.x, c.y);
    }
    if !bb.is_empty() {
        lay.obstacles.push(bb);
        lay.bands.push(band);
        lay.aligned_last = true;
    }
    Ok(())
}
// ------------------------------------------------------------ leaders

// Gap between two boxes (negative when they overlap on both axes).
fn box_gap(a: &BBox, b: &BBox) -> f64 {
    let gx = (a.x0 - b.x1).max(b.x0 - a.x1);
    let gy = (a.y0 - b.y1).max(b.y0 - a.y1);
    gx.max(gy)
}

// How far the ray from p (inside or on the box) runs before leaving it.
fn exit_t(b: &BBox, p: P, u: P) -> f64 {
    let mut t = f64::INFINITY;
    if u.x > 1e-12 {
        t = t.min((b.x1 - p.x) / u.x);
    } else if u.x < -1e-12 {
        t = t.min((b.x0 - p.x) / u.x);
    }
    if u.y > 1e-12 {
        t = t.min((b.y1 - p.y) / u.y);
    } else if u.y < -1e-12 {
        t = t.min((b.y0 - p.y) / u.y);
    }
    if t.is_finite() {
        t.max(0.0)
    } else {
        0.0
    }
}

// A note's box: the landing runs from the knee along h, the text `lead` out.
fn note_box(knee: P, h: f64, lead: f64, w: f64, hh: f64) -> BBox {
    let x0 = knee.x + h * lead;
    let x1 = x0 + h * w;
    let mut b = BBox::empty();
    b.add(x0.min(x1), knee.y - hh);
    b.add(x0.max(x1), knee.y + hh);
    b
}

// The knee on the ray tip + t·u: out of the geometry box by NOTE_OFFSET, then
// further until the note's box (`rel`, about the knee) clears every obstacle
// by its clearance.
fn knee_clear(obs: &[(BBox, f64)], geo: &BBox, tip: P, u: P, rel: &BBox) -> (P, f64) {
    let h = if u.x < -1e-9 { -1.0 } else { 1.0 };
    let at = |t: f64| tip.add(u.mul(t));
    let mut t = exit_t(geo, tip, u) + NOTE_OFFSET;
    let boxed = |t: f64| -> BBox {
        let k = at(t);
        let mut b = BBox::empty();
        b.add(k.x + rel.x0, k.y + rel.y0);
        b.add(k.x + rel.x1, k.y + rel.y1);
        b
    };
    for _ in 0..32 {
        let mut changed = false;
        for (ob, c) in obs {
            if ob.is_empty() || box_gap(&boxed(t), ob) >= c - 1e-9 {
                continue;
            }
            let mut need = f64::INFINITY;
            if u.x > 1e-9 {
                need = need.min((ob.x1 + c - rel.x0 - tip.x) / u.x);
            } else if u.x < -1e-9 {
                need = need.min((ob.x0 - c - rel.x1 - tip.x) / u.x);
            }
            if u.y > 1e-9 {
                need = need.min((ob.y1 + c - rel.y0 - tip.y) / u.y);
            } else if u.y < -1e-9 {
                need = need.min((ob.y0 - c - rel.y1 - tip.y) / u.y);
            }
            if need.is_finite() && need > t + 1e-9 {
                t = need;
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    (at(t), h)
}
// Where a leader's ray meets a node's outline from its centre.
fn rim(ctx: &Ctx, f: usize, i: usize, u: P) -> Option<P> {
    let n = &ctx.nodes[i];
    let m = to_frame(ctx, i, f);
    let c = apply(&m, pt(-n.geo_off.0, -n.geo_off.1));
    match n.prim {
        Prim::Oval => {
            // the ellipse in the node frame (axis-aligned there)
            let inv = invert(&m)?;
            let lu = apply_v(&inv, u);
            let (rx, ry) = (n.w / 2.0, n.h / 2.0);
            if rx <= 0.0 || ry <= 0.0 {
                return Some(c);
            }
            let k = 1.0 / ((lu.x / rx).powi(2) + (lu.y / ry).powi(2)).sqrt();
            Some(c.add(u.mul(k * lu.len() / lu.len().max(1e-12))))
        }
        _ => {
            let (hw, hh) = (n.w / 2.0, n.h / 2.0);
            let inv = invert(&m)?;
            let lu = apply_v(&inv, u);
            let mut t = f64::INFINITY;
            if lu.x.abs() > 1e-12 {
                t = t.min(hw / lu.x.abs());
            }
            if lu.y.abs() > 1e-12 {
                t = t.min(hh / lu.y.abs());
            }
            if !t.is_finite() {
                return Some(c);
            }
            Some(c.add(u.mul(t)))
        }
    }
}

// A ray from a radial pattern's ring centre: where it last leaves a copy it
// passes through (the centre itself when it misses them all).
fn ring_exit(ctx: &Ctx, f: usize, r: &Ref, u: P) -> P {
    let c = match r.ring {
        Some(c) => c,
        None => return r.p,
    };
    let w = match ctx.nodes[r.node].parent {
        Some(w) => w,
        None => return c,
    };
    let mut best: Option<f64> = None;
    for k in copies_of(ctx, w) {
        let cc = origin_in(ctx, f, k);
        let rc = ctx.nodes[k].w / 2.0;
        let v = c.sub(cc);
        let b = v.dot(u);
        let disc = b * b - (v.dot(v) - rc * rc);
        if disc < 0.0 {
            continue;
        }
        let t = -b + disc.sqrt();
        if t > 0.0 && best.map(|x| t > x).unwrap_or(true) {
            best = Some(t);
        }
    }
    match best {
        Some(t) => c.add(u.mul(t)),
        None => c,
    }
}

// Does the segment from p to q (on node i's box) run inside or along the
// box before reaching q?
fn enters_box(ctx: &Ctx, f: usize, i: usize, p: P, q: P) -> bool {
    let n = &ctx.nodes[i];
    let m = to_frame(ctx, i, f);
    let inv = match invert(&m) {
        Some(v) => v,
        None => return false,
    };
    let off = pt(n.geo_off.0, n.geo_off.1);
    let (a, b) = (apply(&inv, p).add(off), apply(&inv, q).add(off));
    let (hw, hh) = (n.w / 2.0 + 1e-6, n.h / 2.0 + 1e-6);
    let d = b.sub(a);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (s, ds, lo, hi) in [(a.x, d.x, -hw, hw), (a.y, d.y, -hh, hh)] {
        if ds.abs() < 1e-12 {
            if s < lo || s > hi {
                return false;
            }
        } else {
            let (mut ta, mut tb) = ((lo - s) / ds, (hi - s) / ds);
            if ta > tb {
                std::mem::swap(&mut ta, &mut tb);
            }
            t0 = t0.max(ta);
            t1 = t1.min(tb);
            if t0 > t1 {
                return false;
            }
        }
    }
    // inside the box for more than the end point itself
    (1.0 - t0) * d.len() > 1e-3
}

// Where the ray from p (on or in node i's box) along u leaves the box.
fn box_exit(ctx: &Ctx, f: usize, i: usize, p: P, u: P) -> P {
    let n = &ctx.nodes[i];
    let m = to_frame(ctx, i, f);
    let inv = match invert(&m) {
        Some(v) => v,
        None => return p,
    };
    let lp = apply(&inv, p).add(pt(n.geo_off.0, n.geo_off.1));
    let lu = apply_v(&inv, u);
    let (hw, hh) = (n.w / 2.0, n.h / 2.0);
    let mut t = f64::INFINITY;
    if lu.x > 1e-12 {
        t = t.min((hw - lp.x) / lu.x);
    } else if lu.x < -1e-12 {
        t = t.min((-hw - lp.x) / lu.x);
    }
    if lu.y > 1e-12 {
        t = t.min((hh - lp.y) / lu.y);
    } else if lu.y < -1e-12 {
        t = t.min((-hh - lp.y) / lu.y);
    }
    if !t.is_finite() || t <= 1e-9 {
        return p;
    }
    p.add(u.mul(t))
}

fn invert(m: &M) -> Option<M> {
    let det = m[0] * m[3] - m[1] * m[2];
    if det.abs() < 1e-12 {
        return None;
    }
    let a = m[3] / det;
    let b = -m[1] / det;
    let c = -m[2] / det;
    let d = m[0] / det;
    let e = -(a * m[4] + c * m[5]);
    let f = -(b * m[4] + d * m[5]);
    Some([a, b, c, d, e, f])
}

// The ray a leader follows from its feature: `side:` turns it to that
// side's normal; otherwise out from the frame datum through the feature.
fn leader_dir(st: &St, through: P) -> P {
    if let Some(s) = st.ident("side") {
        if let Some(d) = side_dir(&s) {
            return d;
        }
    }
    if through.len() < 1e-9 {
        return pt(1.0, -1.0).unit();
    }
    through.unit()
}

// The thread spec a tagged run composes from the geometry ("M8×1.25"): the
// run's diameter (an inner run reads its major, out by 0.54125 × pitch).
fn thread_spec(ctx: &Ctx, f: usize, r: &Ref) -> Option<String> {
    let (seg, pitch, internal) = crate::drawing::thread_info(ctx, r.node)?;
    if seg.is_some() && seg != r.tag {
        return None;
    }
    let (a0, a1) = r.run?;
    let (b0, b1) = r.twin?;
    let d = a0.add(a1).mul(0.5).sub(b0.add(b1).mul(0.5)).len() / crate::drawing::ps(ctx, f);
    let major = if internal { d + 2.0 * 0.54125 * pitch } else { d };
    Some(format!("M{}×{}", fmt_val(major), fmt_val(pitch)))
}

fn label_text(st: &St, base: Option<String>) -> String {
    match (base, &st.label) {
        (Some(b), Some(l)) => format!("{} {}", b, l),
        (Some(b), None) => b,
        (None, Some(l)) => l.clone(),
        (None, None) => String::new(),
    }
}

// One line of a leader's note: its text, width, inline style, nudge.
struct NoteLine {
    text: String,
    w: f64,
    // measured at the regular weight (what the frame box takes)
    bw: f64,
    size: f64,
    css: String,
    vars: Vec<String>,
    off: P,
}

const NOTE_LINE: f64 = 15.0;

// The note's lines: the composed text, then the bracketed texts, each
// measured and styled on its own.
fn note_lines(ctx: &Ctx, f: usize, st: &St, first: &str, weight: u32) -> Result<Vec<NoteLine>, Diag> {
    let fam = ctx.comp[f].family;
    let mut v = Vec::new();
    if !first.is_empty() {
        let w = crate::font::text_width(fam, weight, font_sz(), first);
        v.push(NoteLine { text: first.to_string(), w, bw: w, size: font_sz(), css: String::new(), vars: vec![], off: pt(0.0, 0.0) });
    }
    for (t, props) in &st.texts {
        let mut vars = Vec::new();
        let mut ls: Vec<(String, String)> = Vec::new();
        let mut size = font_sz();
        let mut w8 = 400;
        if let Some(v) = prop(props, "color") {
            if let Some(term) = crate::style::single_term(v) {
                ls.push(("fill".into(), crate::style::color_css(term, &mut vars, v.span)?));
            }
        }
        if let Some(v) = prop(props, "font-size") {
            if let Some(x) = crate::style::value_num(&ctx.sheet.env, v) {
                size = x;
                if x != FONT {
                    ls.push(("font-size".into(), format!("{}px", f4(x))));
                }
            }
        }
        if let Some(v) = prop(props, "font-weight") {
            w8 = crate::style::weight_num(v);
            let css = crate::style::weight_css(v, &mut vars, v.span)?;
            ls.push(("font-weight".into(), css));
        }
        let mut more: Vec<(String, crate::ast::Value)> = Vec::new();
        for k in ["font-style", "text-decoration", "text-shadow"] {
            if let Some(v) = prop(props, k) {
                more.push((k.to_string(), v.clone()));
            }
        }
        if !more.is_empty() {
            ls.extend(crate::render::css_decls(ctx, &more, &mut vars, 2.0, true)?);
        }
        let off = match prop(props, "translate") {
            Some(v) => {
                let xs = crate::style::value_nums(&ctx.sheet.env, v);
                pt(xs.first().copied().unwrap_or(0.0), xs.get(1).copied().unwrap_or(0.0))
            }
            None => pt(0.0, 0.0),
        };
        let css = ls.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ");
        // (the frame measures the text at the regular weight)
        let bw = crate::font::text_width(fam, 400, size, t);
        v.push(NoteLine { text: t.clone(), w: crate::font::text_width(fam, w8, size, t), bw, size, css, vars, off });
    }
    Ok(v)
}

// The note box about the knee: the landing, then the lines stacked down.
fn lines_box(knee: P, h: f64, lines: &[NoteLine]) -> BBox {
    let w = lines.iter().map(|l| l.w).fold(0.0, f64::max);
    let hh = lines.first().map(|l| l.size).unwrap_or(FONT) / 2.0;
    let mut b = note_box(knee, h, NOTE_LANDING + NOTE_GAP, w, hh);
    if lines.len() > 1 {
        b.add(b.x0, knee.y + NOTE_LINE * (lines.len() - 1) as f64 + hh);
    }
    b
}

fn line_items(knee: P, h: f64, lines: Vec<NoteLine>, out: &mut Vec<Item>) {
    for (k, l) in lines.into_iter().enumerate() {
        let c = pt(knee.x + h * (NOTE_LANDING + NOTE_GAP + l.w / 2.0) + l.off.x, knee.y + NOTE_LINE * k as f64 + l.off.y);
        let mut it = Item::text(c, &l.text, 0.0, None);
        it.css = l.css;
        it.css_vars = l.vars;
        it.wh = Some((l.bw, l.size));
        out.push(it);
    }
}

// A leader note: tip on the feature, a ray out to the knee, the landing and
// the text. `marker`: "arrow" | "dot" | "datum".
fn lay_note(ctx: &Ctx, f: usize, st: &St, r: &Ref, text: &str, weight: u32, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let u = match (r.n, st.ident("side")) {
        (Some(n), None) => n,
        _ => leader_dir(st, r.p),
    };
    let tip = if r.ring.is_some() {
        ring_exit(ctx, f, r, u)
    } else if r.feature {
        rim(ctx, f, r.node, u).unwrap_or(r.p)
    } else if r.tag.is_none() {
        // a side, corner or centre: where the ray leaves the part's box
        box_exit(ctx, f, r.node, r.p, u)
    } else {
        // a run along the ray lands its leader on its far end; otherwise mid-run
        match r.run {
            Some((r0, r1)) if r1.sub(r0).unit().cross(u).abs() < 1e-9 => {
                if r0.dot(u) > r1.dot(u) {
                    r0
                } else {
                    r1
                }
            }
            _ => r.p,
        }
    };
    let lines = note_lines(ctx, f, st, text, weight)?;
    if lines.is_empty() {
        return Err(Diag::error("layout", "a leader needs its text — 'bolt <- \"THRU\"'", st.span));
    }
    let h0 = if u.x < -1e-9 { -1.0 } else { 1.0 };
    let rel = lines_box(pt(0.0, 0.0), h0, &lines);
    let (knee, h) = knee_clear(&lay.leader_obs(), &lay.geo, tip, u, &rel);
    let land = knee.add(pt(h * NOTE_LANDING, 0.0));
    let mut line = Item::new(Kind::Polyline, "lini-dim-line", vec![tip.add(u.mul(line_inset())), knee, land]);
    line.halo = true;
    line.own_tips = vec![tip];
    if st.op == "*-" {
        // a surface note: a dot on the face, the wire's own marker
        line.extra.push(link_marker("dot", tip, u.mul(-1.0)));
        line.mask_pts.push(tip);
        out.push(line);
    } else {
        out.push(line);
        let mut m = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(tip, u));
        m.tip = Some(tip);
        out.push(m);
    }
    lay.tips.push(tip);
    lay.obstacles.push(lines_box(knee, h, &lines));
    line_items(knee, h, lines, out);
    Ok(())
}

// A datum: the filled triangle on the face, a leader out to the framed letter.
// On a face the triangle stands on it along its normal (at the run's end a
// `side:` along it points to); elsewhere — a feature's rim, a corner — it is
// the leader's own marker, along the ray.
fn lay_datum(ctx: &Ctx, f: usize, st: &St, r: &Ref, letter: &str, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let u = match (r.n, st.ident("side")) {
        (Some(n), None) => n,
        _ => leader_dir(st, r.p),
    };
    let face = r.n;
    let base = match (face, r.run) {
        (Some(_), _) if r.tag.is_none() => box_exit(ctx, f, r.node, r.p, u),
        (Some(_), Some((r0, r1))) if r1.sub(r0).unit().cross(u).abs() < 1e-9 => {
            if r0.dot(u) > r1.dot(u) {
                r0
            } else {
                r1
            }
        }
        (Some(_), _) => r.p,
        (None, _) if r.ring.is_some() => ring_exit(ctx, f, r, u),
        (None, _) if r.feature => rim(ctx, f, r.node, u).unwrap_or(r.p),
        _ => r.p,
    };
    // (a face turned from the ray lends it the ray's way)
    let nrm = match face {
        Some(n) if n.dot(u) < -1e-9 => u,
        Some(n) => n,
        None => u,
    };
    let apex = base.add(nrm.mul(DATUM_TRI));
    let l = pt(-nrm.y, nrm.x);
    let box_s = 18.0;
    // the frame grows past its square for a longer name
    let box_w = (tw(ctx, f, FONT, letter) + 6.0).max(box_s);
    let h0 = if u.x < -1e-9 { -1.0 } else { 1.0 };
    let rel = note_box(pt(0.0, 0.0), h0, NOTE_LANDING, box_w, box_s / 2.0);
    let (knee, h) = knee_clear(&lay.leader_obs(), &lay.geo, base, u, &rel);
    // the frame box sits right after the landing (no text gap)
    let land = knee.add(pt(h * NOTE_LANDING, 0.0));
    let mut line = Item::new(Kind::Polyline, "lini-dim-line", vec![apex, knee, land]);
    line.halo = true;
    let half = DATUM_TRI / 2.0;
    if face.is_some() {
        out.push(line);
        let tri = vec![base.add(l.mul(half)), base.sub(l.mul(half)), apex];
        let mut m = Item::new(Kind::Polygon, "lini-marker lini-marker-datum", tri);
        // (other lines keep their halos off it)
        m.tip = Some(base);
        out.push(m);
    } else {
        let tri = [base.sub(l.mul(half)), base.add(l.mul(half)), apex];
        line.extra.push(format!("<polygon class=\"lini-marker lini-marker-datum\" points=\"{}\"/>", pts_str(&tri)));
        line.mask_pts.push(base);
        out.push(line);
    }
    let x0 = land.x;
    let x1 = land.x + h * box_w;
    let c = pt((x0 + x1) / 2.0, knee.y);
    out.push(Item::text(c, letter, 0.0, None));
    let (bx0, bx1) = (x0.min(x1), x0.max(x1));
    let (by0, by1) = (knee.y - box_s / 2.0, knee.y + box_s / 2.0);
    let frame = vec![pt(bx0, by0), pt(bx1, by0), pt(bx1, by1), pt(bx0, by1), pt(bx0, by0)];
    out.push(Item::new(Kind::Polyline, "lini-dim-line lini-datum-frame", frame));
    let mut b = BBox::empty();
    b.add(bx0, by0);
    b.add(bx1, by1);
    lay.obstacles.push(b);
    Ok(())
}

// A diameter / radius: through a round feature, at a fillet, or a station ⌀
// on a revolved run.
fn lay_round(ctx: &Ctx, f: usize, st: &St, r: &Ref, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let k = crate::drawing::ps(ctx, f);
    let carried = carried_nodes(ctx, f, st.span);
    if let Some((_, rad)) = r.arc {
        // a radius: the arrow on the arc, the leader out
        let t = dim_text(ctx, f, st, rad / k, "R")?;
        let txt = t.main.clone();
        let u = leader_dir(st, r.p);
        let tip = r.p;
        let w = tw(ctx, f, FONT, &txt);
        let (knee, h, rel) = note_knee(ctx, lay, tip, u, w, &carried);
        let land = knee.add(pt(h * NOTE_LANDING, 0.0));
        let mut line = Item::new(Kind::Polyline, "lini-dim-line", vec![tip.add(u.mul(line_inset())), knee, land]);
        line.halo = true;
        line.own_tips = vec![tip];
        out.push(line);
        let mut m = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(tip, u));
        m.tip = Some(tip);
        out.push(m);
        lay.tips.push(tip);
        note_items(ctx, lay, knee, h, w, &txt, &carried, &rel, out);
        return Ok(());
    }
    if r.feature {
        let n = &ctx.nodes[r.node];
        let d = n.w;
        let prefix = if r.pattern { format!("{}× ⌀", r.copies) } else { "⌀".to_string() };
        let t = dim_text(ctx, f, st, d / k, &prefix)?;
        let txt = t.main.clone();
        let u = leader_dir(st, r.p);
        // (a radial pattern reads its hole as if it stood on the ring centre)
        let (near, far) = match r.ring {
            Some(c) => (c.add(u.mul(n.w / 2.0)), c.sub(u.mul(n.w / 2.0))),
            None => (rim(ctx, f, r.node, u).unwrap_or(r.p), rim(ctx, f, r.node, u.mul(-1.0)).unwrap_or(r.p)),
        };
        let w = tw(ctx, f, FONT, &txt);
        let (knee, h, rel) = note_knee(ctx, lay, near, u, w, &carried);
        let land = knee.add(pt(h * NOTE_LANDING, 0.0));
        let start = far.sub(u.mul(arrow_l() + line_inset()));
        let mut line = Item::new(Kind::Polyline, "lini-dim-line", vec![start, knee, land]);
        line.halo = true;
        line.own_tips = vec![near, far];
        out.push(line);
        let mut m1 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(near, u));
        m1.tip = Some(near);
        out.push(m1);
        let mut m2 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(far, u.mul(-1.0)));
        m2.tip = Some(far);
        out.push(m2);
        lay.tips.push(near);
        lay.tips.push(far);
        note_items(ctx, lay, knee, h, w, &txt, &carried, &rel, out);
        return Ok(());
    }
    Ok(())
}

// A note's knee: its box (text after the landing, carried nodes stacked
// under the text) clear of the geometry and the annotations already placed.
fn note_knee(ctx: &Ctx, lay: &Layout, tip: P, u: P, w: f64, carried: &[usize]) -> (P, f64, BBox) {
    let h0 = if u.x < -1e-9 { -1.0 } else { 1.0 };
    let mut rel = note_box(pt(0.0, 0.0), h0, NOTE_LANDING + NOTE_GAP, w, FONT / 2.0);
    let tc = pt(h0 * (NOTE_LANDING + NOTE_GAP + w / 2.0), 0.0);
    for it in stack_under(ctx, carried, tc, FONT / 2.0) {
        if let Kind::Node(i) = it.kind {
            node_box_at(ctx, i, it.pts[0], &mut rel);
        }
    }
    let (knee, h) = knee_clear(&lay.leader_obs(), &lay.geo, tip, u, &rel);
    (knee, h, rel)
}

// The note's text and carried stack; its box joins the obstacles.
fn note_items(ctx: &Ctx, lay: &mut Layout, knee: P, h: f64, w: f64, txt: &str, carried: &[usize], rel: &BBox, out: &mut Vec<Item>) {
    let cpos = pt(knee.x + h * (NOTE_LANDING + NOTE_GAP + w / 2.0), knee.y);
    out.push(Item::text(cpos, txt, 0.0, None));
    out.extend(stack_under(ctx, carried, cpos, FONT / 2.0));
    let mut b = BBox::empty();
    b.add(knee.x + rel.x0, knee.y + rel.y0);
    b.add(knee.x + rel.x1, knee.y + rel.y1);
    lay.obstacles.push(b);
}
// ------------------------------------------------------------ frame layout

fn first_error(ctx: &mut Ctx, e: Diag) {
    if ctx.an.error.is_none() {
        ctx.an.error = Some(e);
    }
}

fn ref_of(ctx: &Ctx, f: usize, li: usize, to: bool) -> Result<Ref, Diag> {
    let l = &ctx.links[li];
    let (n, a, ix) = if to { (l.to, &l.to_anchor, l.to_index) } else { (l.from, &l.from_anchor, l.from_index) };
    resolve(ctx, f, n, a.as_deref(), ix).map_err(|m| Diag::error("layout", &m, endpoint_span(l.span, a.as_deref(), ix)))
}

// Lay out every annotation written in drawing frame f; `bb` (the parts'
// content box, datum frame) grows to hold them.
pub fn layout(ctx: &mut Ctx, f: usize, bb: &mut BBox) {
    // floor plans read clear spans of their own (another family's code)
    if ctx.comp[f].layout == "floorplan" {
        return;
    }
    let sts = statements(ctx, f);
    if sts.is_empty() {
        return;
    }
    // carried annotation nodes are sized here (they are no parts)
    for i in 0..ctx.nodes.len() {
        if ctx.nodes[i].parent == Some(f) && !ctx.nodes[f].children.contains(&i) && is_gdt(ctx, i) {
            measure_gdt(ctx, i);
        }
    }
    // mates move parts, then seats stand annotation nodes on faces
    let mut moved = false;
    for seats in [false, true] {
        if sts.iter().any(|s| s.op == "||") {
            moved = true;
            if let Err(e) = lay_mates(ctx, f, &sts, seats) {
                first_error(ctx, e);
            }
        }
    }
    if moved {
        let mut nb = BBox::empty();
        for &ch in &ctx.nodes[f].children {
            if ctx.comp[ch].pin.is_some() || crate::drawing::is_plane(ctx, ch) {
                continue;
            }
            crate::drawing::deep_bbox_pub(ctx, ch, &mut nb);
        }
        *bb = nb;
    }
    let mut lay = Layout::new(geometry_box(ctx, f));
    for &ch in &ctx.nodes[f].children {
        if ctx.comp[ch].pin.is_none() && is_annotation_node(ctx, ch) {
            let mut b = BBox::empty();
            crate::drawing::deep_bbox_pub(ctx, ch, &mut b);
            if !b.is_empty() {
                lay.nodes.push(b);
            }
        }
    }
    let mut per: Vec<Vec<Item>> = vec![vec![]; sts.len()];
    let mut errs: Vec<Diag> = Vec::new();
    // each statement's own ink: its stroke width and text size scale it
    let inks: Vec<StInk> = sts.iter().map(|st| st_ink(ctx, st)).collect();
    // pass 1: leaders and datums — they stand off the geometry
    for (k, st) in sts.iter().enumerate() {
        set_ink(inks[k].w, inks[k].font);
        let r = match st.op.as_str() {
            "<-" | "*-" | ">-" | "->" | "-*" => lay_leader_stmt(ctx, f, st, &mut lay, &mut per[k]),
            _ => Ok(()),
        };
        if let Err(e) = r {
            errs.push(e);
        }
    }
    set_ink(1.0, FONT);
    // pass 2: linear dimensions (and station diameters) pack into rows
    for (k, st) in sts.iter().enumerate() {
        set_ink(inks[k].w, inks[k].font);
        let r = match st.op.as_str() {
            "(-)" => {
                let mut lins = Vec::new();
                let mut bad = None;
                for &li in &st.links {
                    match (ref_of(ctx, f, li, false), ref_of(ctx, f, li, true)) {
                        (Ok(a), Ok(b)) => lins.push(Lin { a, b, li }),
                        (Err(e), _) | (_, Err(e)) => {
                            bad = Some(e);
                            break;
                        }
                    }
                }
                match bad {
                    Some(e) => Err(e),
                    None => lay_linear(ctx, f, st, &lins, &mut lay, &mut per[k]),
                }
            }
            "(o)" => lay_round_stmt(ctx, f, st, &mut lay, &mut per[k]),
            "(<)" => {
                let mut r = Ok(());
                for &li in &st.links {
                    if let Err(e) = lay_angle(ctx, f, st, li, &mut per[k]) {
                        r = Err(e);
                        break;
                    }
                }
                r
            }
            _ => Ok(()),
        };
        if let Err(e) = r {
            errs.push(e);
        }
        // a dimension laid stands in the way of what follows (its band:
        // lines, arrows and texts, and the extension lines' overshoot)
        set_ink(1.0, FONT);
        if st.op == "(-)" || st.op == "(<)" {
            let b = band_box(ctx, f, &per[k]);
            if !b.is_empty() && !lay.aligned_last {
                lay.bands.push(vec![pt(b.x0, b.y0), pt(b.x1, b.y0), pt(b.x1, b.y1), pt(b.x0, b.y1)]);
                lay.obstacles.push(b);
            }
            lay.aligned_last = false;
        }
    }
    for e in errs {
        first_error(ctx, e);
    }
    for (k, ink) in inks.iter().enumerate() {
        ink_items(ink, &mut per[k]);
    }
    // `(-) { … }` dresses dimensions alone: their wires wear `lini-dim`
    if ctx.sheet.dim_rules.iter().any(|d| d.name == "stroke" || d.name == "stroke-width") {
        for (k, st) in sts.iter().enumerate() {
            if is_dim_op(&st.op) {
                for it in per[k].iter_mut() {
                    if matches!(it.kind, Kind::Line | Kind::Polyline | Kind::Polygon | Kind::Path) {
                        it.cls.push_str(" lini-dim");
                    }
                }
            }
        }
    }
    let mut items: Vec<Item> = per.into_iter().flatten().collect();
    halos(ctx, f, &lay, &mut items);
    // the frame grows to hold the annotations
    let mut ab = BBox::empty();
    for it in &items {
        item_bbox(ctx, f, it, &mut ab);
    }
    if !ab.is_empty() {
        bb.add(ab.x0, ab.y0);
        bb.add(ab.x1, ab.y1);
    }
    ctx.an.frames.insert(f, Frame { shift: pt(0.0, 0.0), items, bbox: ab });
}

// The parts' content box (datum frame): annotation nodes stand apart.
fn geometry_box(ctx: &Ctx, f: usize) -> BBox {
    let mut bb = BBox::empty();
    for &ch in &ctx.nodes[f].children {
        if ctx.comp[ch].pin.is_some() || is_annotation_node(ctx, ch) || ctx.nodes[ch].is("note") {
            continue;
        }
        crate::drawing::deep_bbox_pub(ctx, ch, &mut bb);
    }
    bb
}

pub fn is_annotation_node(ctx: &Ctx, i: usize) -> bool {
    is_gdt(ctx, i) || ctx.nodes[i].is("balloon")
}

// The frame's centring shift (applied to its children after layout).
pub fn set_shift(ctx: &mut Ctx, f: usize, dx: f64, dy: f64) {
    if let Some(fr) = ctx.an.frames.get_mut(&f) {
        fr.shift = pt(dx, dy);
    }
    ctx.an.shifts.insert(f, pt(dx, dy));
}

// Where a laid-out frame's datum sits relative to its centre (a plain node
// is its own centre).
pub fn datum_offset(ctx: &Ctx, i: usize) -> (f64, f64) {
    match ctx.an.shifts.get(&i) {
        Some(p) => (p.x, p.y),
        None => (0.0, 0.0),
    }
}

fn item_bbox(ctx: &Ctx, f: usize, it: &Item, b: &mut BBox) {
    match it.kind {
        Kind::Text => {
            let size = it.wh.map(|x| x.1).or(it.size).unwrap_or(it.font);
            let w = match it.wh {
                Some((w, _)) => w,
                None => tw(ctx, f, size, &it.text),
            };
            let c = it.pts[0];
            let (hx, hy) = if (it.rot.abs() - 90.0).abs() < 1e-9 { (size / 2.0, w / 2.0) } else { (w / 2.0, size / 2.0) };
            if it.rot != 0.0 && (it.rot.abs() - 90.0).abs() >= 1e-9 {
                let a = it.rot.to_radians();
                let (s, co) = a.sin_cos();
                for (x, y) in [(-w / 2.0, -size / 2.0), (w / 2.0, -size / 2.0), (w / 2.0, size / 2.0), (-w / 2.0, size / 2.0)] {
                    b.add(c.x + x * co - y * s, c.y + x * s + y * co);
                }
            } else {
                b.add(c.x - hx, c.y - hy);
                b.add(c.x + hx, c.y + hy);
            }
        }
        Kind::Node(i) => node_box_at(ctx, i, it.pts[0], b),
        _ => {
            for p in &it.pts {
                b.add(p.x, p.y);
            }
        }
    }
}

fn lay_leader_stmt(ctx: &Ctx, f: usize, st: &St, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    // a fan (`a & b <- "x"`): one note, a ray-cast leg onto each further end
    let ones: Vec<usize> = st.links.iter().copied().filter(|&li| ctx.links[li].one_ended).collect();
    if ones.len() > 1 && st.op != ">-" {
        let r = ref_of(ctx, f, ones[0], false)?;
        let base = if r.run.is_some() && st.op == "<-" { thread_spec(ctx, f, &r) } else { None };
        let weight = if base.is_some() && st.label.is_none() { ctx.comp[f].font_weight } else { 400 };
        let text = label_text(st, base);
        let mut note = Vec::new();
        lay_note(ctx, f, st, &r, &text, weight, lay, &mut note)?;
        let knee = match note.first() {
            Some(it) if it.pts.len() >= 2 => it.pts[1],
            _ => r.p,
        };
        let (txt, rest): (Vec<Item>, Vec<Item>) = note.into_iter().partition(|it| it.kind == Kind::Text);
        out.extend(rest);
        for &li in &ones[1..] {
            let r2 = ref_of(ctx, f, li, false)?;
            let center = if r2.feature { origin_in(ctx, f, r2.node) } else { r2.p };
            let d = knee.sub(center).unit();
            let tip = if r2.feature { rim(ctx, f, r2.node, d).unwrap_or(center) } else { r2.p };
            // a leg must reach its end from outside its own part
            if !r2.feature && enters_box(ctx, f, r2.node, knee, tip) {
                let l2 = &ctx.links[li];
                let mut name = crate::links::path_of(ctx, l2.from);
                if let Some(a) = &l2.from_anchor {
                    name = format!("{}:{}", name, a);
                }
                return Err(Diag::error(
                    "layout",
                    &format!("a fan leg cannot reach '{}' — its own outline blocks the way; anchor the near face or steer the fan with 'side:'", name),
                    endpoint_span(l2.span, l2.from_anchor.as_deref(), l2.from_index),
                ));
            }
            let mut leg = Item::new(Kind::Line, "lini-dim-line", vec![tip.add(d.mul(line_inset())), knee]);
            leg.halo = true;
            leg.own_tips = vec![tip];
            out.push(leg);
            let mut m = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(tip, d));
            m.tip = Some(tip);
            out.push(m);
            lay.tips.push(tip);
        }
        out.extend(txt);
        return Ok(());
    }
    for &li in &st.links {
        if !ctx.links[li].one_ended {
            lay_connector(ctx, f, st, li, lay, out)?;
            continue;
        }
        let mut r = ref_of(ctx, f, li, false)?;
        // a pattern's leader lands on the copy furthest toward its side
        let l = &ctx.links[li];
        if is_wrapper(ctx, l.from) && l.from_index.is_none() {
            if let Some(d) = st.ident("side").and_then(|s| side_dir(&s)) {
                let n = copies_of(ctx, l.from).len();
                let mut best: Option<(f64, Ref)> = None;
                for k in 1..=n {
                    if let Ok(c) = resolve(ctx, f, l.from, l.from_anchor.as_deref(), Some(k as u32)) {
                        let tip = rim(ctx, f, c.node, d).unwrap_or(c.p);
                        let v = tip.dot(d);
                        if best.as_ref().map(|b| v > b.0 + 1e-9).unwrap_or(true) {
                            best = Some((v, c));
                        }
                    }
                }
                if let Some((_, c)) = best {
                    r = c;
                }
            }
        }
        match st.op.as_str() {
            ">-" => {
                let letter = st.label.clone().unwrap_or_default();
                if letter.is_empty() {
                    return Err(Diag::error("layout", "a leader needs its text — 'bolt <- \"THRU\"'", st.span));
                }
                lay_datum(ctx, f, st, &r, &letter, lay, out)?;
            }
            _ => {
                let base = if r.run.is_some() && st.op == "<-" { thread_spec(ctx, f, &r) } else { None };
                // a composed callout standing alone measures at the frame's weight
                let weight = if base.is_some() && st.label.is_none() { ctx.comp[f].font_weight } else { 400 };
                let text = label_text(st, base);
                lay_note(ctx, f, st, &r, &text, weight, lay, out)?;
            }
        }
    }
    Ok(())
}



// A round feature: a hole, or a circle (an oval as wide as it is tall).
fn is_round(ctx: &Ctx, i: usize) -> bool {
    let n = &ctx.nodes[i];
    n.is("hole") || (n.prim == Prim::Oval && (n.w - n.h).abs() < 1e-9)
}

// `(o)` reads what its anchor names: a round feature's diameter (bare or at
// its centre), the diametral line through it (a side or corner), a fillet's
// radius, a revolved run's station, or a part's diameter across a side.
fn lay_round_stmt(ctx: &Ctx, f: usize, st: &St, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    for &li in &st.links {
        let r = ref_of(ctx, f, li, false)?;
        let l = &ctx.links[li];
        let anchor = if r.tag.is_some() { None } else { l.from_anchor.as_deref() };
        let side = anchor.filter(|a| side_dir(a).is_some());
        let corner = anchor.filter(|a| *a != "center" && corner_dir(a).is_some());
        let round = is_round(ctx, r.node);
        // 0 station, 1 feature, 2 diametral line, 3 radius, 4 across a side, 5 no axis
        let kind = if r.run.is_some() && r.twin.is_some() {
            0
        } else if round && (r.feature || anchor == Some("center")) {
            1
        } else if round && (side.is_some() || corner.is_some()) {
            2
        } else if r.arc.is_some() {
            3
        } else if !round && side.is_some() {
            4
        } else {
            5
        };
        let n0 = out.len();
        match kind {
            0 => {
                // a ⌀ station on a revolved run: the run and its twin, measured across
                let (a0, a1) = r.run.unwrap();
                let (b0, b1) = r.twin.unwrap();
                let pa = a0.add(a1).mul(0.5);
                let pb = b0.add(b1).mul(0.5);
                let ra = Ref { run: None, n: None, twin: None, p: pa, ..r.clone() };
                let rb = Ref { run: None, n: None, twin: None, p: pb, ..r.clone() };
                lay_station(ctx, f, st, ra, rb, li, lay, out)?;
            }
            1 => lay_round(ctx, f, st, &Ref { feature: true, ..r.clone() }, lay, out)?,
            2 => lay_inside_diameter(ctx, f, st, &r, lay, out)?,
            3 => lay_round(ctx, f, st, &r, lay, out)?,
            4 => {
                // across the part, from the named side to its opposite
                let opp = match side.unwrap() {
                    "top" => "bottom",
                    "bottom" => "top",
                    "left" => "right",
                    _ => "left",
                };
                let rb = resolve(ctx, f, l.from, Some(opp), l.from_index).map_err(|m| Diag::error("layout", &m, l.span))?;
                let ra = Ref { run: None, n: None, twin: None, ..r.clone() };
                let rb = Ref { run: None, n: None, twin: None, ..rb };
                // the extension lines in increasing x / y
                if matches!(side, Some("bottom") | Some("right")) {
                    lay_station(ctx, f, st, rb, ra, li, lay, out)?;
                } else {
                    lay_station(ctx, f, st, ra, rb, li, lay, out)?;
                }
            }
            _ => {
                let name = ctx.nodes[l.from].id.clone().unwrap_or_default();
                return Err(Diag::error(
                    "layout",
                    &format!("'(o)' can't pick an axis on '{}' — anchor a side ('{}:top (o)') or a segment", name, name),
                    st.span,
                ));
            }
        }
        // a station is a dimension row: its band stands in the way
        if kind == 0 || kind == 4 {
            let b = band_box(ctx, f, &out[n0..]);
            if !b.is_empty() {
                lay.bands.push(vec![pt(b.x0, b.y0), pt(b.x1, b.y0), pt(b.x1, b.y1), pt(b.x0, b.y1)]);
                lay.obstacles.push(b);
            }
        }
    }
    Ok(())
}

// A diameter read across a revolved run and its twin: a dimension row.
fn lay_station(ctx: &Ctx, f: usize, st: &St, a: Ref, b: Ref, li: usize, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let mut tmp = Vec::new();
    // measure as a linear dimension with the ⌀ prefix
    let lins = vec![Lin { a, b, li }];
    lay_linear_pref(ctx, f, st, &lins, lay, &mut tmp, "⌀")?;
    out.extend(tmp);
    Ok(())
}

// ------------------------------------------------------------ halos

#[derive(Clone, Debug)]
enum Outline {
    // a drawn run of segments (a closed loop's closing edge included) and
    // its stroke width
    Path(Vec<Seg>, f64),
    // a nested frame's box (its edges inset by its stroke width)
    Box(Vec<Seg>, f64),
    Ellipse(M, f64, f64, f64),
}

fn outlines(ctx: &Ctx, f: usize) -> Vec<(usize, Outline)> {
    let mut out = Vec::new();
    let mut stack: Vec<usize> = ctx.nodes[f].children.iter().rev().copied().collect();
    while let Some(i) = stack.pop() {
        let n = &ctx.nodes[i];
        if n.prim == Prim::Text || crate::drawing::is_chrome(ctx, i) || ctx.sk.chrome.contains_key(&i) || is_annotation_node(ctx, i) || n.is("note") || is_ring(i) {
            continue;
        }
        // a detail view's clipped copy: its parts count (clipped or not), not its box
        if is_clip(ctx, i) {
            for &ch in n.children.iter().rev() {
                stack.push(ch);
            }
            continue;
        }
        let m = to_frame(ctx, i, f);
        let sw = if ctx.sk.copies.contains(&i) { 0.0 } else { stroke_w(ctx, i) };
        if crate::drawing::is_frame(ctx, i) {
            // a nested frame counts with its box, inset by its stroke width
            let fsw = ctx.comp[i].stroke_width;
            let c = pt(-n.geo_off.0, -n.geo_off.1);
            let (hw, hh) = ((n.w - fsw) / 2.0, (n.h - fsw) / 2.0);
            let cs = [pt(c.x - hw, c.y - hh), pt(c.x + hw, c.y - hh), pt(c.x + hw, c.y + hh), pt(c.x - hw, c.y + hh)];
            let segs = (0..4).map(|k| Seg::Line { a: apply(&m, cs[k]), b: apply(&m, cs[(k + 1) % 4]) }).collect();
            out.push((i, Outline::Box(segs, fsw)));
        }
        if !is_wrapper(ctx, i) && ctx.comp[i].has_stroke && !crate::drawing::is_frame(ctx, i) {
            let c = pt(-n.geo_off.0, -n.geo_off.1);
            let (hw, hh) = (n.w / 2.0, n.h / 2.0);
            let poly = |ps: &[P]| -> Outline {
                let segs: Vec<Seg> = (0..ps.len()).map(|k| Seg::Line { a: apply(&m, ps[k]), b: apply(&m, ps[(k + 1) % ps.len()]) }).collect();
                Outline::Path(segs, sw)
            };
            match n.prim {
                Prim::Oval => {
                    let mm = mul(&m, &[1.0, 0.0, 0.0, 1.0, c.x, c.y]);
                    out.push((i, Outline::Ellipse(mm, hw, hh, sw)));
                }
                Prim::Sketch => {
                    if let Some(l) = ctx.sk.laid.get(&i) {
                        for s in &l.shape.subs {
                            let mut segs: Vec<Seg> = s.segs.iter().map(|g| map_seg(&m, g)).collect();
                            if s.closed && !s.end().near(s.start) {
                                segs.push(map_seg(&m, &Seg::Line { a: s.end(), b: s.start }));
                            }
                            out.push((i, Outline::Path(segs, sw)));
                        }
                    }
                }
                Prim::Block if n.w > 0.0 && n.h > 0.0 => {
                    out.push((i, poly(&[pt(c.x - hw, c.y - hh), pt(c.x + hw, c.y - hh), pt(c.x + hw, c.y + hh), pt(c.x - hw, c.y + hh)])));
                }
                Prim::Hex if n.w > 0.0 && n.h > 0.0 => {
                    let ps: Vec<P> = [pt(-hw, 0.0), pt(-hw / 2.0, -hh), pt(hw / 2.0, -hh), pt(hw, 0.0), pt(hw / 2.0, hh), pt(-hw / 2.0, hh)].iter().map(|p| p.add(c)).collect();
                    out.push((i, poly(&ps)));
                }
                Prim::Diamond if n.w > 0.0 && n.h > 0.0 => {
                    let ps: Vec<P> = [pt(0.0, -hh), pt(hw, 0.0), pt(0.0, hh), pt(-hw, 0.0)].iter().map(|p| p.add(c)).collect();
                    out.push((i, poly(&ps)));
                }
                _ => {}
            }
        }
        for &ch in n.children.iter().rev() {
            stack.push(ch);
        }
    }
    out
}

// Crossings of segment p→q with one outline segment: (t along p→q, s along
// the outline segment, sin of the crossing angle).
fn seg_hits(p: P, q: P, g: &Seg) -> Vec<(f64, f64, f64)> {
    let d = q.sub(p);
    let len = d.len();
    if len < 1e-12 {
        return vec![];
    }
    let u = d.mul(1.0 / len);
    let mut out = Vec::new();
    match g {
        Seg::Line { a, b } => {
            let e = b.sub(*a);
            let den = d.cross(e);
            if den.abs() < 1e-12 {
                return out;
            }
            let w = a.sub(p);
            let t = w.cross(e) / den;
            let s = w.cross(d) / den;
            if t > 1e-9 && t < 1.0 - 1e-9 && s > -1e-9 && s < 1.0 + 1e-9 {
                out.push((t, s.clamp(0.0, 1.0), u.cross(e.unit()).abs()));
            }
        }
        Seg::Arc { c, r, sweep, .. } => {
            let f0 = p.sub(*c);
            let a2 = d.dot(d);
            let b2 = 2.0 * f0.dot(d);
            let c2 = f0.dot(f0) - r * r;
            let disc = b2 * b2 - 4.0 * a2 * c2;
            if disc < 0.0 {
                return out;
            }
            let sq = disc.sqrt();
            for t in [(-b2 - sq) / (2.0 * a2), (-b2 + sq) / (2.0 * a2)] {
                if t > 1e-9 && t < 1.0 - 1e-9 {
                    let x = p.add(d.mul(t));
                    if let Some(s) = arc_param(g, x) {
                        let nrm = x.sub(*c).unit();
                        let _ = sweep;
                        out.push((t, s, u.dot(nrm).abs()));
                    }
                }
            }
        }
        Seg::Cubic { .. } => {
            let n = 64;
            let mut prev = seg_point(g, 0.0);
            for k in 1..=n {
                let cur = seg_point(g, k as f64 / n as f64);
                let e = cur.sub(prev);
                let den = d.cross(e);
                if den.abs() > 1e-12 {
                    let w = prev.sub(p);
                    let t = w.cross(e) / den;
                    let s = w.cross(d) / den;
                    if t > 1e-9 && t < 1.0 - 1e-9 && s >= 0.0 && s < 1.0 {
                        out.push((t, ((k - 1) as f64 + s) / n as f64, u.cross(e.unit()).abs()));
                    }
                }
                prev = cur;
            }
        }
    }
    out
}

// The parameter (0..1) of a point on an arc, if it lies on it: the angle
// from the start, turned the sweep's way, with no slack before the start.
fn arc_param(g: &Seg, x: P) -> Option<f64> {
    if let Seg::Arc { a, c, sweep, .. } = g {
        let v0 = a.sub(*c);
        let v1 = x.sub(*c);
        let ang = v0.cross(v1).atan2(v0.dot(v1));
        let mut ang = if *sweep >= 0.0 { ang } else { -ang };
        if ang < 0.0 {
            ang += 2.0 * std::f64::consts::PI;
        }
        let sw = sweep.abs();
        if sw > 0.0 && ang <= sw + 1e-9 {
            return Some((ang / sw).clamp(0.0, 1.0));
        }
    }
    None
}

// Crossings of segment p→q with an outline: (t along p→q, sin of the angle,
// whether it falls on an edge's end).
fn crossings(p: P, q: P, o: &Outline) -> Vec<(f64, f64, bool)> {
    let d = q.sub(p);
    if d.len() < 1e-12 {
        return vec![];
    }
    let mut out = Vec::new();
    match o {
        Outline::Path(segs, _) | Outline::Box(segs, _) => {
            for g in segs {
                for (t, s, sin) in seg_hits(p, q, g) {
                    out.push((t, sin, s <= 1e-9 || s >= 1.0 - 1e-9));
                }
            }
        }
        Outline::Ellipse(m, rx, ry, _) => {
            let u = d.unit();
            let inv = match invert(m) {
                Some(v) => v,
                None => return out,
            };
            let lp = apply(&inv, p);
            let ld = apply_v(&inv, d);
            if *rx <= 0.0 || *ry <= 0.0 {
                return out;
            }
            let a2 = (ld.x / rx).powi(2) + (ld.y / ry).powi(2);
            let b2 = 2.0 * (lp.x * ld.x / (rx * rx) + lp.y * ld.y / (ry * ry));
            let c2 = (lp.x / rx).powi(2) + (lp.y / ry).powi(2) - 1.0;
            let disc = b2 * b2 - 4.0 * a2 * c2;
            if disc <= 0.0 {
                return out;
            }
            let sq = disc.sqrt();
            for t in [(-b2 - sq) / (2.0 * a2), (-b2 + sq) / (2.0 * a2)] {
                if t > 1e-9 && t < 1.0 - 1e-9 {
                    let lx = lp.add(ld.mul(t));
                    let ln = pt(lx.x / (rx * rx), lx.y / (ry * ry));
                    let nrm = apply_v(&[inv[0], inv[2], inv[1], inv[3], 0.0, 0.0], ln).unit();
                    out.push((t, u.dot(nrm).abs(), false));
                }
            }
        }
    }
    out
}
// Does segment a→b touch box b (edges included)?
fn seg_meets_box(a: P, b: P, bx: &BBox) -> bool {
    let eps = 1e-6;
    let d = b.sub(a);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (p, dp, lo, hi) in [(a.x, d.x, bx.x0, bx.x1), (a.y, d.y, bx.y0, bx.y1)] {
        if dp.abs() < 1e-12 {
            if p < lo - eps || p > hi + eps {
                return false;
            }
        } else {
            let (mut ta, mut tb) = ((lo - eps - p) / dp, (hi + eps - p) / dp);
            if ta > tb {
                std::mem::swap(&mut ta, &mut tb);
            }
            t0 = t0.max(ta);
            t1 = t1.min(tb);
            if t0 > t1 {
                return false;
            }
        }
    }
    true
}

fn outline_sw(o: &Outline) -> f64 {
    match o {
        Outline::Path(_, sw) => *sw,
        Outline::Box(_, sw) => *sw,
        Outline::Ellipse(_, _, _, sw) => *sw,
    }
}

fn halos(ctx: &Ctx, f: usize, lay: &Layout, items: &mut [Item]) {
    if !items.iter().any(|it| it.halo) {
        return;
    }
    let outs = outlines(ctx, f);
    let tips: Vec<P> = items.iter().filter_map(|it| it.tip).chain(lay.tips.iter().copied()).collect();
    let base = match crate::links::path_of(ctx, f) {
        p if p.is_empty() => "lini-halo-".to_string(),
        p => format!("lini-halo-{}-", p),
    };
    let mut seq = 0;
    // the arrowheads' boxes, by tip
    let heads: Vec<(P, BBox)> = items
        .iter()
        .filter(|it| it.kind == Kind::Polygon && it.tip.is_some())
        .map(|it| {
            let mut b = BBox::empty();
            for q in &it.pts {
                b.add(q.x, q.y);
            }
            (it.tip.unwrap(), b)
        })
        .collect();
    for it in items.iter_mut() {
        if !it.halo || it.pts.len() < 2 {
            continue;
        }
        // (position along the line, ends, dropped)
        let mut segs: Vec<(f64, P, P, bool)> = Vec::new();
        let mut acc = 0.0;
        let heads = &heads;
        for w in it.pts.windows(2) {
            let (p, q) = (w[0], w[1]);
            let len = q.sub(p).len();
            if len < 1e-12 {
                continue;
            }
            let u = q.sub(p).mul(1.0 / len);
            // every outline's crossings; one on an edge's end counts only
            // in company (a vertex, or shapes meeting there)
            let mut hits: Vec<(f64, f64, f64, bool)> = Vec::new();
            for (_on, o) in &outs {
                for (t, sin, end) in crossings(p, q, o) {
                    // a tangent touch is no crossing
                    if sin < 1e-4 {
                        continue;
                    }
                    hits.push((t, sin, outline_sw(o), end));
                }
            }
            for (i, h) in hits.iter().enumerate() {
                if h.3 && !hits.iter().enumerate().any(|(j, g)| j != i && ((g.0 - h.0) * len).abs() < 1e-6) {
                    continue;
                }
                let x = p.add(q.sub(p).mul(h.0));
                let hl = (h.2 / 2.0 + HALO_MARGIN) / h.1;
                let (h0, h1) = (x.sub(u.mul(hl)), x.add(u.mul(hl)));
                // no halo at the line's own tips or reaching under its
                // arrowheads (their boxes), nor where a leader lands — nor
                // one merging with such
                let under = |tp: &P| match heads.iter().find(|(t, _)| t.sub(*tp).len() < 1e-9) {
                    Some((_, b)) => tp.sub(x).len() < 1e-6 || seg_meets_box(h0, h1, b),
                    None => tp.sub(x).len() <= ARROW_L + 1e-6,
                };
                // an extension line's halo reaching back to within its gap of
                // the line's start would leave no stub: none
                let stub = it.cls.contains("lini-ext-line") && acc + h.0 * len - hl < EXT_GAP;
                // nor one reaching under another line's arrowhead
                let other_head = heads.iter().any(|(tp, b)| !it.own_tips.iter().any(|o| o.sub(*tp).len() < 1e-9) && seg_meets_box(h0, h1, b));
                let drop = stub || other_head || it.own_tips.iter().any(under) || tips.iter().any(|tp| tp.sub(x).len() < 1e-6);
                segs.push((acc + h.0 * len, h0, h1, drop));
            }
            acc += len;
        }
        if segs.is_empty() {
            continue;
        }
        segs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        // overlapping halos merge
        let mut merged: Vec<(f64, P, P, bool)> = Vec::new();
        for sg in segs {
            if let Some(last) = merged.last_mut() {
                let lu = last.2.sub(last.1);
                let reach = sg.1.sub(last.1).dot(lu.unit());
                if reach <= lu.len() + 1e-9 {
                    if sg.2.sub(last.1).dot(lu.unit()) > lu.len() {
                        last.2 = sg.2;
                    }
                    last.3 = last.3 || sg.3;
                    continue;
                }
            }
            merged.push(sg);
        }
        let segs: Vec<(f64, P, P)> = merged.into_iter().filter(|s| !s.3).map(|s| (s.0, s.1, s.2)).collect();
        if segs.is_empty() {
            continue;
        }
        let mut b = BBox::empty();
        for p in it.pts.iter().chain(it.mask_pts.iter()) {
            b.add(p.x, p.y);
        }
        let hw = HALO_W / 2.0;
        let bx = (b.x0 - hw, b.y0 - hw, b.x1 - b.x0 + HALO_W, b.y1 - b.y0 + HALO_W);
        it.mask = Some((format!("{}{}", base, seq), bx, segs.into_iter().map(|s| (s.1, s.2)).collect()));
        seq += 1;
    }
}

// ------------------------------------------------------------ render

fn push_rule(out: &mut Out, slot: &str, rule: &str) {
    let r = (slot.to_string(), rule.to_string());
    if !out.extra_rules.contains(&r) {
        out.extra_rules.push(r);
    }
}

fn pts_str(ps: &[P]) -> String {
    ps.iter().map(|p| format!("{},{}", f4(p.x), f4(p.y))).collect::<Vec<_>>().join(" ")
}

// Write frame f's annotations (after its children, before pinned ones).
pub fn render(ctx: &Ctx, f: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let fr = match ctx.an.frames.get(&f) {
        Some(fr) => fr,
        None => return Ok(()),
    };
    let pad = " ".repeat(ind_n);
    let inner = " ".repeat(ind_n + 2);
    let (sx, sy) = (fr.shift.x, fr.shift.y);
    let mut any = (false, false, false, false, false, false, false);
    for it in &fr.items {
        match &it.kind {
            Kind::Text => {
                any.0 = true;
                let p = pt(it.pts[0].x + sx, it.pts[0].y + sy);
                let style = match it.size {
                    Some(sz) => format!(" style=\"font-size: {}px\"", f4(sz)),
                    None if !it.css.is_empty() => format!(" style=\"{}\"", xml_escape(&it.css)),
                    None => String::new(),
                };
                for v in &it.css_vars {
                    use_var(&mut out.vars, v);
                }
                let rot = if it.rot != 0.0 { format!(" transform=\"rotate({} {} {})\"", f4(it.rot), f4(p.x), f4(p.y)) } else { String::new() };
                s.push_str(&format!(
                    "{}<text class=\"lini-text lini-dim-text\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}{}>{}</text>\n",
                    pad,
                    f4(p.x),
                    f4(p.y),
                    style,
                    rot,
                    xml_escape(&it.text)
                ));
            }
            Kind::Node(i) => {
                let at = pt(it.pts[0].x + sx, it.pts[0].y + sy);
                if is_gdt(ctx, *i) {
                    render_gdt_at(ctx, *i, ind_n, s, out, &it.cls, Some(at))?;
                } else {
                    crate::render::render_node(ctx, *i, ind_n, s, out)?;
                }
            }
            k => {
                let prim = match k {
                    Kind::Polygon => "lini-poly",
                    Kind::Path => "lini-path",
                    _ => "lini-line",
                };
                if *k == Kind::Path {
                    push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
                }
                if *k == Kind::Polygon {
                    any.1 = true;
                } else if *k != Kind::Path {
                    any.2 = true;
                }
                if it.cls.contains("lini-dim-line") {
                    any.3 = true;
                }
                if it.cls.contains("lini-ext-line") {
                    any.4 = true;
                }
                if it.cls.contains("lini-marker-datum") {
                    any.6 = true;
                }
                let gstyle = if it.css.is_empty() { String::new() } else { format!(" style=\"{}\"", xml_escape(&it.css)) };
                for v in &it.css_vars {
                    use_var(&mut out.vars, v);
                }
                s.push_str(&format!("{}<g class=\"lini-node {} {}\"{} transform=\"translate({},{})\">\n", pad, it.cls, prim, gstyle, f4(sx), f4(sy)));
                let mut mask_attr = String::new();
                if let Some((id, (x, y, w, h), segs)) = &it.mask {
                    any.5 = true;
                    let mut m = format!(
                        "<mask id=\"{}\" maskUnits=\"userSpaceOnUse\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"><rect class=\"lini-cut-bg\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>",
                        id,
                        f4(*x),
                        f4(*y),
                        f4(*w),
                        f4(*h),
                        f4(*x),
                        f4(*y),
                        f4(*w),
                        f4(*h)
                    );
                    for (a, b) in segs {
                        m.push_str(&format!("<polyline class=\"lini-halo\" fill=\"none\" stroke-width=\"3\" points=\"{}\"/>", pts_str(&[*a, *b])));
                    }
                    m.push_str("</mask>");
                    s.push_str(&format!("{}{}\n", inner, m));
                    mask_attr = format!(" mask=\"url(#{})\"", id);
                }
                match k {
                    Kind::Line => s.push_str(&format!(
                        "{}<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"{}/>\n",
                        inner,
                        f4(it.pts[0].x),
                        f4(it.pts[0].y),
                        f4(it.pts[1].x),
                        f4(it.pts[1].y),
                        mask_attr
                    )),
                    Kind::Polyline => s.push_str(&format!("{}<polyline points=\"{}\"{}/>\n", inner, pts_str(&it.pts), mask_attr)),
                    Kind::Path => s.push_str(&format!("{}<path d=\"{}\"{}/>\n", inner, it.text, mask_attr)),
                    _ => s.push_str(&format!("{}<polygon points=\"{}\"{}/>\n", inner, pts_str(&it.pts), mask_attr)),
                }
                for e in &it.extra {
                    s.push_str(&format!("{}{}\n", inner, e));
                }
                s.push_str(&format!("{}</g>\n", pad));
            }
        }
    }
    let (txt, poly, line, dim, ext, halo, datum) = any;
    // the annotation ink: `|-| { stroke }` recolours every wire
    let mut vars = Vec::new();
    let link_ink = rule_color(&ctx.sheet.link_rules, "stroke", &mut vars);
    let dim_ink = rule_color(&ctx.sheet.dim_rules, "stroke", &mut vars);
    for v in vars {
        use_var(&mut out.vars, &v);
    }
    let dark = match &link_ink {
        Some(c) => c.clone(),
        None => "var(--lini-stroke-dark)".to_string(),
    };
    let light = match &link_ink {
        Some(c) => c.clone(),
        None => "var(--lini-stroke-light)".to_string(),
    };
    let ink = |out: &mut Out, dark_used: bool| {
        if link_ink.is_none() {
            use_var(&mut out.vars, if dark_used { "stroke-dark" } else { "stroke-light" });
        }
    };
    if fr.items.iter().any(|it| !it.extra.is_empty()) {
        // link markers riding a connector take the annotation ink
        out.markers = true;
        push_rule(out, "marker-in-dim", &format!(".lini-dim-line .lini-marker {{ fill: {}; }}", dark));
        ink(out, true);
    }
    // a link rule's width, and a dimension rule's (its ink defaults to the
    // annotation's own)
    let link_w = rule_num(ctx, &ctx.sheet.link_rules, "stroke-width").filter(|w| *w > 0.0).unwrap_or(1.0);
    let dim_w = rule_num(ctx, &ctx.sheet.dim_rules, "stroke-width").filter(|w| *w > 0.0);
    if dim_ink.is_some() || dim_w.is_some() {
        let has = |k: &str| fr.items.iter().any(|it| it.cls.contains(k) && it.cls.contains("lini-dim ") || it.cls.ends_with("lini-dim") && it.cls.contains(k));
        let w = f4(dim_w.unwrap_or(1.0));
        let (dc, lc) = match &dim_ink {
            Some(c) => (c.clone(), c.clone()),
            None => (dark.clone(), light.clone()),
        };
        if has("lini-dim-line") {
            push_rule(out, "dim-class", &format!(".lini-dim-line.lini-dim {{ stroke: {}; stroke-width: {}; }}", dc, w));
            if dim_ink.is_none() {
                ink(out, true);
            }
        }
        if has("lini-ext-line") {
            push_rule(out, "dim-class", &format!(".lini-ext-line.lini-dim {{ stroke: {}; stroke-width: {}; }}", lc, w));
            if dim_ink.is_none() {
                ink(out, false);
            }
        }
        if has("lini-marker-dim") {
            push_rule(out, "dim-class", &format!(".lini-marker-dim.lini-dim {{ fill: {}; }}", dc));
        }
    }
    if txt {
        out.any_text = true;
        push_rule(out, "dim-text", ".lini-dim-text { font-size: 12px; font-weight: var(--lini-link-font-weight); }");
        use_var(&mut out.vars, "link-font-weight");
    }
    if line {
        push_rule(out, "line", ".lini-line { stroke-dasharray: none; }");
    }
    if poly {
        push_rule(out, "poly", ".lini-poly { stroke-dasharray: none; }");
        out.markers = true;
        if fr.items.iter().any(|it| it.cls.contains("lini-marker-dim")) {
            push_rule(out, "marker-dim", &format!(".lini-marker-dim {{ fill: {}; }}", dark));
            ink(out, true);
        }
        if datum {
            push_rule(out, "marker-datum", &format!(".lini-marker-datum {{ fill: {}; }}", dark));
            ink(out, true);
        }
    }
    if dim {
        push_rule(out, "dim-line", &format!(".lini-dim-line {{ fill: none; stroke: {}; stroke-width: {}; }}", dark, f4(link_w)));
        ink(out, true);
    }
    if ext {
        push_rule(out, "ext-line", &format!(".lini-ext-line {{ fill: none; stroke: {}; stroke-width: {}; }}", light, f4(link_w)));
        ink(out, false);
    }
    if halo {
        push_rule(out, "halo-cut-bg", ".lini-cut-bg { fill: white; stroke: none; }");
        push_rule(out, "halo", ".lini-halo { stroke: black; }");
    }
    Ok(())
}

// A rule's number.
fn rule_num(ctx: &Ctx, decls: &[crate::ast::Decl], k: &str) -> Option<f64> {
    let d = decls.iter().rev().find(|d| d.name == k)?;
    crate::style::value_num(&ctx.sheet.env, &d.value)
}

// A statement's own ink and the rules it falls under: the stroke width its
// arrowheads scale by, its text size, and what it writes inline.
struct StInk {
    w: f64,
    font: f64,
    stroke: Option<String>,
    width: Option<f64>,
    color: Option<String>,
    vars: Vec<String>,
}

fn st_ink(ctx: &Ctx, st: &St) -> StInk {
    let dim = is_dim_op(&st.op);
    let mut vars = Vec::new();
    let own_num = |k: &str| st.get(k).and_then(|v| crate::style::value_num(&ctx.sheet.env, v));
    let width = own_num("stroke-width");
    let rules = |k: &str| -> Option<f64> {
        let d = if dim { rule_num(ctx, &ctx.sheet.dim_rules, k) } else { None };
        d.or_else(|| rule_num(ctx, &ctx.sheet.link_rules, k))
    };
    let w = width.or_else(|| rules("stroke-width")).filter(|x| *x > 0.0).unwrap_or(1.0);
    let font = own_num("font-size").or_else(|| rules("font-size")).filter(|x| *x > 0.0).unwrap_or(FONT);
    let stroke = st.get("stroke").and_then(crate::style::single_term).and_then(|t| crate::style::color_css(t, &mut vars, st.span).ok());
    let color = if dim {
        None
    } else {
        match st.get("color").and_then(crate::style::single_term) {
            Some(t) => crate::style::color_css(t, &mut vars, st.span).ok(),
            None => rule_color(&ctx.sheet.link_rules, "color", &mut vars),
        }
    };
    StInk { w, font, stroke, width, color, vars }
}

// Write a statement's own ink onto its items.
fn ink_items(ink: &StInk, items: &mut [Item]) {
    for it in items.iter_mut() {
        match it.kind {
            Kind::Text => {
                if !it.css.is_empty() || it.size.is_some() {
                    continue;
                }
                let mut ls: Vec<String> = Vec::new();
                if let Some(c) = &ink.color {
                    ls.push(format!("fill: {}", c));
                }
                if (ink.font - FONT).abs() > 1e-9 {
                    ls.push(format!("font-size: {}px", f4(ink.font)));
                }
                it.css = ls.join("; ");
                it.css_vars = ink.vars.clone();
            }
            Kind::Polygon if it.cls.contains("lini-marker") => {
                if let Some(c) = &ink.stroke {
                    it.css = format!("fill: {}", c);
                    it.css_vars = ink.vars.clone();
                }
            }
            Kind::Line | Kind::Polyline => {
                let mut ls: Vec<String> = Vec::new();
                if let Some(c) = &ink.stroke {
                    ls.push(format!("stroke: {}", c));
                }
                if let Some(w) = ink.width {
                    ls.push(format!("stroke-width: {}", f4(w)));
                }
                it.css = ls.join("; ");
                it.css_vars = ink.vars.clone();
            }
            _ => {}
        }
    }
}

fn rule_color(decls: &[crate::ast::Decl], k: &str, vars: &mut Vec<String>) -> Option<String> {
    let d = decls.iter().rev().find(|d| d.name == k)?;
    let t = crate::style::single_term(&d.value)?;
    crate::style::color_css(t, vars, d.value.span).ok()
}

// The root frame's annotations widen the view.
pub fn extend_bbox(ctx: &Ctx, f: usize, b: &mut [f64; 4]) {
    if let Some(fr) = ctx.an.frames.get(&f) {
        if !fr.bbox.is_empty() {
            b[0] = b[0].min(fr.bbox.x0 + fr.shift.x);
            b[1] = b[1].min(fr.bbox.y0 + fr.shift.y);
            b[2] = b[2].max(fr.bbox.x1 + fr.shift.x);
            b[3] = b[3].max(fr.bbox.y1 + fr.shift.y);
        }
    }
}

// Layout-time errors surface once measure is done.
pub fn check(ctx: &Ctx) -> Result<(), Diag> {
    match &ctx.an.error {
        Some(e) => Err(e.clone()),
        None => Ok(()),
    }
}

// ------------------------------------------------------------ resolve-time checks

fn node_layout(b: &crate::scene::Builder, i: usize) -> String {
    let n = &b.nodes[i];
    let props = if i == 0 { n.inline.iter().map(|d| (d.name.clone(), d.value.clone())).collect() } else { crate::compile::cascade(b.sheet, n).1 };
    props.iter().rev().find(|e| e.0 == "layout").and_then(|e| ident_of(&e.1)).unwrap_or("flow").to_string()
}

fn builder_is_drawing(b: &crate::scene::Builder, i: usize) -> bool {
    if matches!(b.nodes[i].prim, Prim::Text | Prim::Line | Prim::Poly | Prim::Path | Prim::Sketch) {
        return false;
    }
    is_drawing_layout(&node_layout(b, i))
}

// Is a statement written directly in a drawing (its container a drawing)?
pub fn stmt_in_drawing(b: &crate::scene::Builder, container: usize) -> bool {
    builder_is_drawing(b, container)
}

fn inside_drawing(b: &crate::scene::Builder, i: usize) -> bool {
    let mut cur = b.nodes[i].parent;
    while let Some(p) = cur {
        if builder_is_drawing(b, p) {
            return true;
        }
        cur = b.nodes[p].parent;
    }
    false
}

// A statement's placement: dimension and mate operators belong in drawings.
// Each statement's written endpoints (anchor, copy index, span), by the
// statement's start: anchor errors point at the endpoint itself.
thread_local! {
    static ENDPOINTS: std::cell::RefCell<HashMap<usize, Vec<(Option<String>, Option<u32>, Span)>>> = std::cell::RefCell::new(HashMap::new());
}

fn endpoint_span(stmt: Span, anchor: Option<&str>, index: Option<u32>) -> Span {
    ENDPOINTS.with(|e| {
        e.borrow()
            .get(&stmt.start)
            .and_then(|v| v.iter().find(|(a, i, _)| a.as_deref() == anchor && *i == index).map(|x| x.2))
            .unwrap_or(stmt)
    })
}

pub fn check_stmt(b: &crate::scene::Builder, container: usize, l: &crate::ast::LinkStmt, in_dwg: bool) -> Result<(), Diag> {
    // a label text's classes must exist
    for s in l.labels.iter().flatten() {
        if let crate::ast::Stmt::Text(t) = s {
            for c in &t.classes {
                if b.sheet.class(c).is_none() {
                    return Err(Diag::error("unknown-class", &format!("unknown class '.{}'", c), t.span));
                }
            }
        }
    }
    let eps: Vec<(Option<String>, Option<u32>, Span)> = l
        .groups
        .iter()
        .flatten()
        .filter_map(|ep| match ep {
            crate::ast::Endpoint::Path(p) => Some((p.anchor.clone(), p.index, p.span)),
            _ => None,
        })
        .collect();
    ENDPOINTS.with(|e| e.borrow_mut().insert(l.span.start, eps));
    let has = |k: &str| l.style.iter().flatten().any(|d| d.name == k);
    if in_dwg {
        // a round feature is one thing: no span between two
        if l.groups.len() > 1 && l.ops.iter().any(|(o, _)| o == "(o)") {
            return Err(Diag::error("layout", "'(o)' measures one round feature — write 'a:top (o)' for a span", l.span));
        }
        if has("gap") && l.ops.iter().any(|(o, _)| is_dim_op(o)) {
            return Err(Diag::error("layout", "a dimension stands off by 'clearance' — 'gap' is a mate's separation", l.span));
        }
        return Ok(());
    }
    let scope = b.child_scope(container);
    let into_drawing = || {
        l.groups.iter().flatten().any(|ep| match ep {
            crate::ast::Endpoint::Path(p) => b.lookup(scope, &p.parts).map(|n| inside_drawing(b, n)).unwrap_or(false),
            _ => false,
        })
    };
    for (op, _) in &l.ops {
        if is_dim_op(op) {
            if into_drawing() {
                return Err(Diag::error("layout", "a dimension reads one view — a cross-view correspondence is a construction link ('a - b')", l.span));
            }
            return Err(Diag::error(
                "layout",
                &format!("'{}' draws a dimension — it belongs in a 'layout: drawing' (or its 'floorplan' dialect)", op),
                l.span,
            ));
        }
        if op == "||" {
            return Err(Diag::error(
                "layout",
                "a mate seats a drawing's parts — '||' belongs in a 'layout: drawing' (or its 'floorplan' dialect)",
                l.span,
            ));
        }
    }
    // a dimension's own properties, on a link outside a drawing (a lone end
    // fails on its own count first)
    if l.groups.len() > 1 {
        if has("tol") {
            return Err(Diag::error("layout", "'tol' composes a dimension's text — it belongs in a 'layout: drawing' (or its 'floorplan' dialect)", l.span));
        }
        if has("project") {
            return Err(Diag::error("layout", "'project' picks a dimension's axis — it belongs in a 'layout: drawing' (or its 'floorplan' dialect)", l.span));
        }
    }
    if l.groups.len() == 1 && l.ops.iter().any(|(o, _)| matches!(o.as_str(), "<-" | "*-" | ">-")) && into_drawing() {
        return Err(Diag::error("layout", "a projection line is unmarked — write 'side.screw:head - end.od:top'", l.span));
    }
    Ok(())
}

// In a drawing an endpoint must exist — nothing is auto-created.
pub fn endpoint_strict(b: &crate::scene::Builder, container: usize, p: &crate::ast::PathRef) -> Result<usize, Diag> {
    let scope = b.child_scope(container);
    if let Some(n) = b.lookup(scope, &p.parts) {
        return Ok(n);
    }
    let mut msg = if scope == 0 {
        format!("dimension endpoint '{}' not found at scene root", p.parts.join("."))
    } else {
        format!("dimension endpoint '{}' not found in '{}'", p.parts.join("."), b.path_of(scope))
    };
    // nodes of that name further down the scope, by their named path
    if let Some(last) = p.parts.last() {
        let mut cands: Vec<String> = Vec::new();
        for (k, n) in b.nodes.iter().enumerate() {
            if k == scope || n.prim == Prim::Text || n.id.as_deref() != Some(last.as_str()) {
                continue;
            }
            let mut parts = vec![last.clone()];
            let mut cur = n.parent;
            let mut inside = false;
            while let Some(c) = cur {
                if c == scope {
                    inside = true;
                    break;
                }
                if let Some(id) = &b.nodes[c].id {
                    parts.push(id.clone());
                }
                cur = b.nodes[c].parent;
            }
            if !inside {
                continue;
            }
            parts.reverse();
            let path = parts.join(".");
            if !cands.contains(&path) {
                cands.push(path);
            }
        }
        cands.sort();
        if !cands.is_empty() {
            let list: Vec<String> = cands.iter().map(|c| format!("'{}'", c)).collect();
            msg.push_str(&format!("; did you mean {}?", list.join(", ")));
        }
    }
    Err(Diag::error("unknown-endpoint", &msg, p.span))
}

// One-ended forms ('a (o)', 'a <- "x"') stand alone in a drawing.
pub fn one_ended_ok(op: &str, in_dwg: bool) -> bool {
    in_dwg && matches!(op, "(o)" | "<-" | "*-" | ">-" | "(-)" | "(<)")
}

// ------------------------------------------------------------ drafting glyphs

// The shared drafting-glyph registry: stroked paths and filled paths in a
// 100-unit box (SPEC 15.9).
fn glyph(name: &str) -> Option<(&'static [&'static str], &'static [&'static str])> {
    Some(match name {
        "straightness" => (&["M 15 50 L 85 50"], &[]),
        "flatness" => (&["M 20 68 L 42 32 L 84 32 L 62 68 Z"], &[]),
        "circularity" => (&["M 18 50 A 32 32 0 1 1 82 50 A 32 32 0 1 1 18 50"], &[]),
        "cylindricity" => (&["M 24 54 A 26 26 0 1 1 76 54 A 26 26 0 1 1 24 54 M 12 86 L 32 22 M 68 86 L 88 22"], &[]),
        "profile-line" => (&["M 16 68 A 34 34 0 0 1 84 68"], &[]),
        "profile-surface" => (&["M 16 68 A 34 34 0 0 1 84 68 Z"], &[]),
        "angularity" => (&["M 18 78 L 72 24 M 18 78 L 86 78"], &[]),
        "perpendicularity" => (&["M 50 22 L 50 78 M 16 78 L 84 78"], &[]),
        "parallelism" => (&["M 26 84 L 52 16 M 54 84 L 80 16"], &[]),
        "position" => (&["M 24 50 A 26 26 0 1 1 76 50 A 26 26 0 1 1 24 50 M 50 12 L 50 88 M 12 50 L 88 50"], &[]),
        "concentricity" => (&["M 36 50 A 14 14 0 1 1 64 50 A 14 14 0 1 1 36 50 M 20 50 A 30 30 0 1 1 80 50 A 30 30 0 1 1 20 50"], &[]),
        "symmetry" => (&["M 16 50 L 84 50 M 30 34 L 70 34 M 30 66 L 70 66"], &[]),
        "circular-runout" => (&["M 22 82 L 64 40"], &["M 80 24 L 68.3 46.3 L 57.7 35.7 Z"]),
        "total-runout" => (&["M 14 84 L 56 84 M 14 84 L 42 56 M 56 84 L 84 56"], &["M 54 44 L 46.2 60.2 L 37.8 51.8 Z", "M 96 44 L 88.2 60.2 L 79.8 51.8 Z"]),
        "maximum" => (&["M 4 50 A 46 46 0 1 1 96 50 A 46 46 0 1 1 4 50 M 32 72 L 32 28 L 50 52 L 68 28 L 68 72"], &[]),
        "least" => (&["M 4 50 A 46 46 0 1 1 96 50 A 46 46 0 1 1 4 50 M 40 28 L 40 72 L 66 72"], &[]),
        "projected" => (&["M 4 50 A 46 46 0 1 1 96 50 A 46 46 0 1 1 4 50 M 40 72 L 40 28 L 54 28 A 13 13 0 0 1 54 54 L 40 54"], &[]),
        "free-state" => (&["M 4 50 A 46 46 0 1 1 96 50 A 46 46 0 1 1 4 50 M 64 28 L 38 28 L 38 72 M 38 48 L 60 48"], &[]),
        "tangent-plane" => (&["M 4 50 A 46 46 0 1 1 96 50 A 46 46 0 1 1 4 50 M 32 28 L 68 28 M 50 28 L 50 72"], &[]),
        "sf-basic" => (&["M 4 55 L 30 100 L 87.7 0"], &[]),
        "sf-machined" => (&["M 4 55 L 30 100 L 87.7 0 M 4 55 L 56 55"], &[]),
        "sf-prohibited" => (&["M 4 55 L 30 100 L 87.7 0 M 16 72 A 14 14 0 1 1 44 72 A 14 14 0 1 1 16 72"], &[]),
        _ => return None,
    })
}

const FORM: &[&str] = &["straightness", "flatness", "circularity", "cylindricity"];
// controls whose zone may be cylindrical or spherical
const AXIS_ZONE: &[&str] = &["straightness", "angularity", "perpendicularity", "parallelism", "position", "concentricity"];
// feature-of-size controls (a material condition applies)
const SIZE_CONTROL: &[&str] = &["straightness", "angularity", "perpendicularity", "parallelism", "position"];
const NEEDS_DATUM: &[&str] = &["angularity", "perpendicularity", "parallelism", "concentricity", "symmetry", "circular-runout", "total-runout"];

// One glyph icon group: centred at (cx, cy), `size` px tall, origin offset
// (ox, oy) in glyph units.
fn glyph_svg(pad: &str, name: &str, cx: f64, cy: f64, size: f64, ox: f64, oy: f64, color: &str) -> String {
    let (strokes, fills) = glyph(name).unwrap_or((&[], &[]));
    let k = size / 100.0;
    let mut s = String::new();
    s.push_str(&format!("{}<g class=\"lini-node lini-drafting-glyph lini-icon\" transform=\"translate({},{})\">\n", pad, f4(cx), f4(cy)));
    s.push_str(&format!("{}  <g transform=\"scale({}) translate({} {})\">\n", pad, f4(k), f4(-ox), f4(-oy)));
    if !strokes.is_empty() {
        s.push_str(&format!(
            "{}    <g fill=\"none\" stroke=\"{}\" stroke-width=\"{}\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n",
            pad,
            color,
            f4(1.0 / k)
        ));
        for d in strokes {
            s.push_str(&format!("{}      <path d=\"{}\"/>\n", pad, d));
        }
        s.push_str(&format!("{}    </g>\n", pad));
    }
    if !fills.is_empty() {
        s.push_str(&format!("{}    <g fill=\"{}\" stroke=\"none\">\n", pad, color));
        for d in fills {
            s.push_str(&format!("{}      <path d=\"{}\"/>\n", pad, d));
        }
        s.push_str(&format!("{}    </g>\n", pad));
    }
    s.push_str(&format!("{}  </g>\n", pad));
    s.push_str(&format!("{}</g>\n", pad));
    s
}

// ------------------------------------------------------------ GD&T nodes

// A datum node's frame: a square, wider for a longer name.
fn datum_w(ctx: &Ctx, i: usize) -> f64 {
    let letter = ctx.nodes[i].label.clone().unwrap_or_default();
    (fc_text_w(ctx, i, &letter) + 6.0).max(18.0)
}

pub fn is_gdt(ctx: &Ctx, i: usize) -> bool {
    let n = &ctx.nodes[i];
    n.prim != Prim::Text && (n.is("feature-control") || n.is("datum") || n.is("surface-finish"))
}

#[derive(Clone, Debug)]
enum Part {
    Text(String),
    Glyph(&'static str),
}

#[derive(Clone, Debug)]
struct FcRow {
    sym: String,
    parts: Vec<Part>,
    // datum letters, each with its material modifier glyph
    datums: Vec<(String, Option<&'static str>)>,
}

#[derive(Clone, Debug)]
enum Cell {
    // centre x, width, contents
    Sym(f64, String),
    Tol(f64, f64, Vec<(Part, f64)>),
    Datum(f64, f64, Vec<(Part, f64)>),
}

fn fc_text_w(ctx: &Ctx, i: usize, s: &str) -> f64 {
    crate::font::text_width(ctx.comp[i].family, ctx.comp[i].font_weight, ctx.comp[i].font_size, s)
}

fn static_name(s: &str) -> Option<&'static str> {
    ["maximum", "least", "projected", "free-state", "tangent-plane"].iter().copied().find(|x| *x == s)
}

// The datum letters declared in drawing f: |datum| nodes first (document
// order), then the statements' — `>-` leaders and carried |datum|s — in
// statement order.
fn declared_datums(ctx: &Ctx, f: usize) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut add = |l: &Option<String>| {
        if let Some(l) = l {
            if !out.contains(l) {
                out.push(l.clone());
            }
        }
    };
    for (k, n) in ctx.nodes.iter().enumerate() {
        let authored = n.parent.map(|p| ctx.nodes[p].children.contains(&k)).unwrap_or(false);
        if n.prim != Prim::Text && n.is("datum") && authored && drawing_of(ctx, k) == Some(f) {
            add(&n.label);
        }
    }
    for st in statements(ctx, f) {
        if st.op == ">-" {
            add(&st.label);
        }
        for c in carried_nodes(ctx, f, st.span) {
            if ctx.nodes[c].is("datum") {
                add(&ctx.nodes[c].label);
            }
        }
    }
    out
}

// A datum letter is placed once per drawing [SPEC 15.9] (checked as the
// statements resolve): nodes first, then the statements in order.
fn datum_duplicates(b: &crate::scene::Builder) -> Result<(), Diag> {
    // the drawing a node sits in, at build time
    let drawing_of_b = |i: usize| -> Option<usize> {
        let mut cur = b.nodes[i].parent;
        while let Some(p) = cur {
            if builder_is_drawing(b, p) {
                return Some(p);
            }
            cur = b.nodes[p].parent;
        }
        None
    };
    let mut seen: HashMap<(usize, String), Span> = HashMap::new();
    let mut place = |f: usize, letter: &str, span: Span| -> Result<(), Diag> {
        if let Some(prev) = seen.get(&(f, letter.to_string())) {
            let (l, c) = crate::diag::line_col(b.src, prev.start);
            return Err(Diag::error("layout", &format!("datum '{}' is already placed (previously at {}:{})", letter, l, c), span));
        }
        seen.insert((f, letter.to_string()), span);
        Ok(())
    };
    for i in 0..b.nodes.len() {
        let n = &b.nodes[i];
        if n.prim != Prim::Text && n.is("datum") {
            if let (Some(f), Some(l)) = (drawing_of_b(i), &n.label) {
                place(f, l, n.span)?;
            }
        }
    }
    for (container, l, _) in &b.pending_links {
        if !builder_is_drawing(b, *container) {
            continue;
        }
        if l.ops.iter().any(|(o, _)| o == ">-") {
            if let Some((t, sp)) = &l.label {
                place(*container, t, *sp)?;
            }
        }
        for st in l.labels.iter().flatten() {
            if let crate::ast::Stmt::Node(ns) = st {
                let is_datum = ns.type_name.as_deref().and_then(|t| crate::scene::type_chain(b.sheet, t)).map(|(_, ch)| ch.iter().any(|x| x == "datum")).unwrap_or(false);
                if is_datum {
                    if let Some((t, _)) = &ns.label {
                        place(*container, t, ns.span)?;
                    }
                }
            }
        }
    }
    Ok(())
}

// The drawing frame a node sits in (its nearest frame, if it draws).
fn drawing_of(ctx: &Ctx, i: usize) -> Option<usize> {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if crate::drawing::is_frame(ctx, p) {
            return if matches!(ctx.comp[p].layout.as_str(), "drawing" | "floorplan") { Some(p) } else { None };
        }
        cur = ctx.nodes[p].parent;
    }
    None
}

// One frame row from its node's properties (the frame's own, or a
// |control| row's): validated in the reference's order.
fn fc_row(ctx: &Ctx, i: usize, row: usize, props: &HashMap<String, crate::ast::Value>, label: Option<&str>) -> Result<FcRow, Diag> {
    let span = ctx.nodes[row].span;
    let sym = match props.get("characteristic").and_then(ident_of) {
        Some(s) => s.to_string(),
        None => label.unwrap_or("").to_string(),
    };
    if sym.is_empty() {
        return Err(Diag::error("layout", "a control names its characteristic — its label or 'characteristic:'", span));
    }
    if glyph(&sym).is_none() || static_name(&sym).is_some() || sym.starts_with("sf-") {
        return Err(Diag::error("layout", &format!("unknown characteristic '{}'", sym), span));
    }
    let mut parts = Vec::new();
    let mut text = String::new();
    let tol = match props.get("tol") {
        Some(t) if t.groups.len() > 1 => {
            // the whole declaration is pointed at
            let at = ctx.nodes[row].inline.iter().rev().find(|d| d.name == "tol").map(|d| d.span).unwrap_or(t.span);
            return Err(Diag::error("layout", "'tol' takes one value, not a comma list", at));
        }
        Some(t) => crate::style::value_num(&ctx.sheet.env, t).filter(|x| *x > 0.0),
        None => None,
    };
    let tol = match tol {
        Some(x) => x,
        None => return Err(Diag::error("layout", "a control row needs 'tol' — its zone width", span)),
    };
    if let Some(z) = props.get("zone") {
        let zv = match ident_of(z) {
            Some("diameter") => "diameter",
            Some("spherical") => "spherical",
            _ => return Err(Diag::error("layout", "'zone' takes 'diameter' or 'spherical'", span)),
        };
        // a cylindrical / spherical zone bounds an axis or a point
        if !AXIS_ZONE.contains(&sym.as_str()) {
            return Err(Diag::error("layout", &format!("'zone: {}' has no meaning on '{}' — its zone is a width, not an axis", zv, sym), span));
        }
        text.push_str(if zv == "diameter" { "⌀" } else { "S⌀" });
    }
    text.push_str(&fmt_val(tol));
    parts.push(Part::Text(text));
    if let Some(m) = props.get("material") {
        let g = match ident_of(m) {
            Some("maximum") => "maximum",
            Some("least") => "least",
            _ => return Err(Diag::error("layout", "'material' takes 'maximum' or 'least'", span)),
        };
        if !SIZE_CONTROL.contains(&sym.as_str()) {
            return Err(Diag::error("layout", "'material' modifies a feature-of-size control — position, orientation, or straightness", span));
        }
        parts.push(Part::Glyph(g));
    }
    if let Some(m) = props.get("modifiers") {
        let bad = || Diag::error("layout", "'modifiers' takes projected N, free-state, or tangent-plane", span);
        for g in &m.groups {
            match g.first() {
                Some(crate::ast::Term::Ident(s, _)) if s == "projected" => {
                    if g.len() != 2 {
                        return Err(bad());
                    }
                    let v = crate::style::term_num(&ctx.sheet.env, &g[1]).ok_or_else(bad)?;
                    parts.push(Part::Glyph("projected"));
                    parts.push(Part::Text(fmt_val(v)));
                }
                Some(crate::ast::Term::Ident(s, _)) if (s == "free-state" || s == "tangent-plane") && g.len() == 1 => {
                    parts.push(Part::Glyph(static_name(s).unwrap()));
                }
                _ => return Err(bad()),
            }
        }
    }
    // `datums: A, B maximum, C` — up to three letters, each with an optional
    // material modifier
    let mut datums: Vec<(String, Option<&'static str>)> = Vec::new();
    if let Some(d) = props.get("datums") {
        let bad = || Diag::error("layout", "'datums' takes letters, each with an optional 'maximum' / 'least'", span);
        for g in &d.groups {
            let letter = match g.first() {
                Some(crate::ast::Term::Ident(s, _)) if s != "maximum" && s != "least" => s.clone(),
                _ => return Err(bad()),
            };
            let m = match g.get(1) {
                None => None,
                Some(crate::ast::Term::Ident(s, _)) if g.len() == 2 => match s.as_str() {
                    "maximum" => Some("maximum"),
                    "least" => Some("least"),
                    _ => return Err(bad()),
                },
                _ => return Err(bad()),
            };
            if datums.iter().any(|x| x.0 == letter) {
                return Err(bad());
            }
            datums.push((letter, m));
        }
        if datums.len() > 3 {
            return Err(bad());
        }
    }
    if NEEDS_DATUM.contains(&sym.as_str()) && datums.is_empty() {
        return Err(Diag::error("layout", &format!("'{}' measures against a datum — name one in 'datums:'", sym), span));
    }
    if FORM.contains(&sym.as_str()) && !datums.is_empty() {
        return Err(Diag::error("layout", &format!("'{}' is a form control — it takes no datum", sym), span));
    }
    // every letter must be declared in the drawing
    if !datums.is_empty() {
        let declared = drawing_of(ctx, i).map(|f| declared_datums(ctx, f)).unwrap_or_default();
        for (d, _) in &datums {
            if !declared.contains(d) {
                let tail = if declared.is_empty() { "none declared".to_string() } else { format!("declared: {}", declared.join(", ")) };
                return Err(Diag::error("layout", &format!("no datum '{}' in this drawing — {}", d, tail), span));
            }
        }
    }
    Ok(FcRow { sym, parts, datums })
}

const CELL: f64 = 17.0;
const CELL_PAD: f64 = 2.5;
const PART_GAP: f64 = 2.0;

// Cells of one frame row, centred on x = 0: outer boxes (stroke 1) abut.
fn fc_cells(ctx: &Ctx, i: usize, row: &FcRow) -> (Vec<Cell>, f64) {
    let (_, total) = fc_cells_at(ctx, i, row, 0.0);
    fc_cells_at(ctx, i, row, -total / 2.0)
}

// A frame row's cells laid from the frame's left edge.
fn fc_cells_at(ctx: &Ctx, i: usize, row: &FcRow, left: f64) -> (Vec<Cell>, f64) {
    let fs = ctx.comp[i].font_size;
    let mut widths: Vec<f64> = vec![fs + 5.0];
    let mut tol_w = 0.0;
    let mut pw = Vec::new();
    for (k, p) in row.parts.iter().enumerate() {
        let w = match p {
            Part::Text(s) => fc_text_w(ctx, i, s),
            Part::Glyph(_) => fs,
        };
        if k > 0 {
            tol_w += PART_GAP;
        }
        pw.push(w);
        tol_w += w;
    }
    widths.push((tol_w + 2.0 * CELL_PAD).max(fs + 5.0));
    let datum_parts = |d: &(String, Option<&'static str>)| -> Vec<(Part, f64)> {
        let mut v = vec![(Part::Text(d.0.clone()), fc_text_w(ctx, i, &d.0))];
        if let Some(g) = d.1 {
            v.push((Part::Glyph(g), fs));
        }
        v
    };
    for d in &row.datums {
        let ps = datum_parts(d);
        let inner: f64 = ps.iter().map(|p| p.1).sum::<f64>() + PART_GAP * (ps.len() as f64 - 1.0);
        widths.push((inner + 2.0 * CELL_PAD).max(fs + 5.0));
    }
    let total: f64 = widths.iter().map(|w| w + 1.0).sum();
    let mut x = left;
    let mut cells = Vec::new();
    for (k, w) in widths.iter().enumerate() {
        let c = x + (w + 1.0) / 2.0;
        x += w + 1.0;
        if k == 0 {
            cells.push(Cell::Sym(c, row.sym.clone()));
        } else if k == 1 {
            // the parts centred in the cell (a narrow one keeps its floor)
            let mut px = c - tol_w / 2.0;
            let mut items = Vec::new();
            for (p, wp) in row.parts.iter().zip(pw.iter()) {
                items.push((p.clone(), px + wp / 2.0));
                px += wp + PART_GAP;
            }
            cells.push(Cell::Tol(c, *w, items));
        } else {
            let ps = datum_parts(&row.datums[k - 2]);
            let inner: f64 = ps.iter().map(|p| p.1).sum::<f64>() + PART_GAP * (ps.len() as f64 - 1.0);
            let mut px = c - inner / 2.0;
            let mut items = Vec::new();
            for (p, wp) in ps {
                items.push((p, px + wp / 2.0));
                px += wp + PART_GAP;
            }
            cells.push(Cell::Datum(c, *w, items));
        }
    }
    (cells, total)
}

fn node_props(ctx: &Ctx, i: usize) -> HashMap<String, crate::ast::Value> {
    ctx.nodes[i].props.clone()
}

fn sf_geom(ctx: &Ctx, i: usize) -> (f64, P, f64, f64, f64) {
    // (glyph size, icon origin, text left, text centre y, text width (layout))
    let fs = ctx.comp[i].font_size;
    let size = 3.0 * fs;
    let k = size / 100.0;
    let org = pt(-k * (30.0 - 44.0), -k * (100.0 - 50.0));
    let arm = pt(org.x + k * (87.7 - 44.0), org.y + k * (0.0 - 50.0));
    let text = ctx.nodes[i].label.clone().unwrap_or_default();
    let w = if text.is_empty() { 0.0 } else { fc_text_w(ctx, i, &text) };
    (size, org, arm.x + 3.0, arm.y - fs / 2.0, w)
}

// Size a GD&T node: its box is the frame / symbol drawn about its datum.
pub fn measure_gdt(ctx: &mut Ctx, i: usize) {
    let mut bb = BBox::empty();
    let sw = stroke_w(ctx, i);
    if ctx.nodes[i].is("surface-finish") {
        let (size, org, tx, ty, w) = sf_geom(ctx, i);
        let k = size / 100.0;
        // the glyph's own box: 88 × 100 units
        bb.add(org.x + k * (0.0 - 44.0), org.y + k * (0.0 - 50.0));
        bb.add(org.x + k * (88.0 - 44.0), org.y + k * (100.0 - 50.0));
        let text = ctx.nodes[i].label.clone().unwrap_or_default();
        if !text.is_empty() {
            let fs = ctx.comp[i].font_size;
            let wr = tw(ctx, i, fs, &text);
            let c = tx + w / 2.0;
            bb.add(c - wr / 2.0, ty - fs / 2.0);
            bb.add(c + wr / 2.0, ty + fs / 2.0);
        }
    } else if ctx.nodes[i].is("datum") {
        let hw = datum_w(ctx, i) / 2.0;
        bb.add(-hw, -9.0);
        bb.add(hw, 9.0);
    } else {
        let rows = fc_rows(ctx, i).unwrap_or_default();
        let n = rows.len().max(1) as f64;
        let mut w: f64 = 0.0;
        for r in &rows {
            let (_, total) = fc_cells(ctx, i, r);
            w = w.max(total);
        }
        let h = n * (CELL + 1.0);
        bb.add(-w / 2.0, -h / 2.0);
        bb.add(w / 2.0, h / 2.0);
        let _ = sw;
    }
    let sw = stroke_w(ctx, i);
    let n = &mut ctx.nodes[i];
    n.w = (bb.w() - sw).max(0.0);
    n.h = (bb.h() - sw).max(0.0);
    n.geo_off = (-bb.cx(), -bb.cy());
    n.x = bb.cx();
    n.y = bb.cy();
}

fn fc_rows(ctx: &Ctx, i: usize) -> Result<Vec<FcRow>, Diag> {
    let kids: Vec<usize> = ctx.nodes[i].children.iter().copied().filter(|&c| ctx.nodes[c].is("control")).collect();
    if kids.is_empty() {
        let label = ctx.nodes[i].label.clone();
        return Ok(vec![fc_row(ctx, i, i, &node_props(ctx, i), label.as_deref())?]);
    }
    let own = ["characteristic", "tol", "zone", "material", "modifiers", "datums"];
    if own.iter().any(|k| ctx.nodes[i].props.contains_key(*k)) {
        return Err(Diag::error("layout", "a frame is one row or '|control|' rows — not both", ctx.nodes[i].span));
    }
    let mut out = Vec::new();
    for c in kids {
        let label = ctx.nodes[c].label.clone();
        out.push(fc_row(ctx, i, c, &node_props(ctx, c), label.as_deref())?);
    }
    Ok(out)
}

// The classes of a GD&T node: its type chain on the path primitive.
fn gdt_classes(ctx: &Ctx, i: usize, out: &mut Out, extra: &str) -> String {
    let n = &ctx.nodes[i];
    let mut cls = vec!["lini-node".to_string()];
    for t in &n.chain {
        if t == "block" {
            continue;
        }
        cls.push(format!("lini-{}", t));
        if !out.used_types.contains(t) {
            out.used_types.push(t.clone());
        }
    }
    for c in &n.classes {
        cls.push(format!("lini-style-{}", c));
        if !out.used_classes.contains(c) {
            out.used_classes.push(c.clone());
        }
    }
    if !extra.is_empty() {
        cls.push(extra.to_string());
    }
    cls.push("lini-path".to_string());
    cls.join(" ")
}

fn cell_rect(pad: &str, cls: &str, cx: f64, cy: f64, w: f64, h: f64) -> String {
    format!(
        "{}<g class=\"lini-node {} lini-block\" transform=\"translate({},{})\">\n{}  <rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"0\" ry=\"0\"/>\n{}</g>\n",
        pad,
        cls,
        f4(cx),
        f4(cy),
        pad,
        f4(-w / 2.0),
        f4(-h / 2.0),
        f4(w),
        f4(h),
        pad
    )
}

fn dim_text_el(pad: &str, x: f64, y: f64, s: &str) -> String {
    format!("{}<text class=\"lini-text lini-dim-text\" x=\"{}\" y=\"{}\" dy=\"0.358em\">{}</text>\n", pad, f4(x), f4(y), xml_escape(s))
}

// Render a GD&T node (feature-control frame, datum, surface finish).
pub fn render_gdt(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out, extra: &str) -> Result<(), Diag> {
    render_gdt_at(ctx, i, ind_n, s, out, extra, None)
}

fn render_gdt_at(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out, extra: &str, at: Option<P>) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let pad = " ".repeat(ind_n);
    let inner = " ".repeat(ind_n + 2);
    let cls = gdt_classes(ctx, i, out, extra);
    let style = crate::render::inline_style(ctx, i, out, false)?;
    let mut head = format!("{}<g class=\"{}\"", pad, cls);
    if let Some(id) = &n.id {
        head.push_str(&format!(" data-id=\"{}\"", xml_escape(id)));
    }
    if !style.is_empty() {
        head.push_str(&format!(" style=\"{}\"", xml_escape(&style)));
    }
    let (tx, ty) = match at {
        Some(p) => (p.x, p.y),
        None => (n.x + c.translate.0 + n.geo_off.0, n.y + c.translate.1 + n.geo_off.1),
    };
    head.push_str(&format!(" transform=\"translate({},{})\">\n", f4(tx), f4(ty)));
    s.push_str(&head);
    let color = "var(--lini-stroke-dark)";
    use_var(&mut out.vars, "stroke-dark");
    out.any_text = true;
    push_rule(out, "dim-text", ".lini-dim-text { font-size: 12px; font-weight: var(--lini-link-font-weight); }");
    use_var(&mut out.vars, "link-font-weight");
    push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
    if n.is("surface-finish") {
        let sym = match n.props.get("symbol").and_then(ident_of) {
            Some("machined") => "sf-machined",
            Some("prohibited") => "sf-prohibited",
            _ => "sf-basic",
        };
        let (size, org, tx0, ty0, w) = sf_geom(ctx, i);
        s.push_str(&glyph_svg(&inner, sym, org.x, org.y, size, 44.0, 50.0, color));
        if let Some(t) = n.label.clone().filter(|t| !t.is_empty()) {
            s.push_str(&dim_text_el(&inner, tx0 + w / 2.0, ty0, &t));
        }
        push_rule(out, "icon", ".lini-icon { stroke-dasharray: none; }");
        push_rule(out, "drafting-glyph", ".lini-drafting-glyph { fill: none; stroke: var(--lini-stroke-dark); stroke-width: 1; }");
    } else if n.is("datum") {
        let dw = datum_w(ctx, i);
        let hw = f4(dw / 2.0);
        s.push_str(&cell_rect(&inner, "lini-frame-plate", 0.0, 0.0, dw, 18.0));
        s.push_str(&format!(
            "{}<g class=\"lini-node lini-dim-line lini-datum-frame lini-line\" transform=\"translate(0,0)\">\n{}  <polyline points=\"-{hw},-9 {hw},-9 {hw},9 -{hw},9 -{hw},-9\"/>\n{}</g>\n",
            inner, inner, inner, hw = hw
        ));
        let letter = n.label.clone().unwrap_or_default();
        s.push_str(&dim_text_el(&inner, 0.0, 0.0, &letter));
        push_rule(out, "frame-plate", ".lini-frame-plate { fill: var(--lini-bg); stroke: none; stroke-width: 0; }");
        use_var(&mut out.vars, "bg");
        push_rule(out, "dim-line", ".lini-dim-line { fill: none; stroke: var(--lini-stroke-dark); stroke-width: 1; }");
        push_rule(out, "line", ".lini-line { stroke-dasharray: none; }");
    } else {
        let rows = fc_rows(ctx, i)?;
        let nr = rows.len() as f64;
        // a composite frame: rows flush left, adjacent rows sharing a
        // characteristic share its symbol cell
        let wmax = rows.iter().map(|r| fc_cells_at(ctx, i, r, 0.0).1).fold(0.0, f64::max);
        let left = -wmax / 2.0;
        let row_y = |ri: usize| -(nr - 1.0) * (CELL + 1.0) / 2.0 + ri as f64 * (CELL + 1.0);
        // the symbol column first, then each row's compartments
        for pass in 0..2 {
        for (ri, row) in rows.iter().enumerate() {
            let cy = row_y(ri);
            let (cells, _) = fc_cells_at(ctx, i, row, left);
            for cell in &cells {
                if matches!(cell, Cell::Sym(..)) != (pass == 0) {
                    continue;
                }
                match cell {
                    Cell::Sym(cx, sym) => {
                        if ri > 0 && rows[ri - 1].sym == row.sym {
                            continue;
                        }
                        let mut last = ri;
                        while last + 1 < rows.len() && rows[last + 1].sym == row.sym {
                            last += 1;
                        }
                        let n = (last - ri + 1) as f64;
                        let my = (row_y(ri) + row_y(last)) / 2.0;
                        s.push_str(&cell_rect(&inner, "lini-frame-cell", *cx, my, CELL, n * (CELL + 1.0) - 1.0));
                        s.push_str(&glyph_svg(&inner, sym, *cx, my, ctx.comp[i].font_size, 50.0, 50.0, color));
                    }
                    Cell::Tol(cx, w, parts) => {
                        s.push_str(&cell_rect(&inner, "lini-frame-cell", *cx, cy, *w, CELL));
                        for (p, px) in parts {
                            match p {
                                Part::Text(t) => s.push_str(&dim_text_el(&inner, *px, cy, t)),
                                Part::Glyph(g) => s.push_str(&glyph_svg(&inner, g, *px, cy, ctx.comp[i].font_size, 50.0, 50.0, color)),
                            }
                        }
                    }
                    Cell::Datum(cx, w, parts) => {
                        s.push_str(&cell_rect(&inner, "lini-frame-cell", *cx, cy, *w, CELL));
                        for (p, px) in parts {
                            match p {
                                Part::Text(t) => s.push_str(&dim_text_el(&inner, *px, cy, t)),
                                Part::Glyph(g) => s.push_str(&glyph_svg(&inner, g, *px, cy, ctx.comp[i].font_size, 50.0, 50.0, color)),
                            }
                        }
                    }
                }
            }
        }
        }
        push_rule(out, "icon", ".lini-icon { stroke-dasharray: none; }");
        push_rule(out, "frame-cell", ".lini-frame-cell { fill: var(--lini-bg); stroke: var(--lini-stroke-dark); stroke-width: 1; }");
        use_var(&mut out.vars, "bg");
        push_rule(out, "drafting-glyph", ".lini-drafting-glyph { fill: none; stroke: var(--lini-stroke-dark); stroke-width: 1; }");
    }
    s.push_str(&format!("{}</g>\n", pad));
    Ok(())
}

// Annotation nodes a dimension carries (`a (-) b [ |datum| "C" ]`): built
// under the drawing but kept out of its parts (annotation layout seats them).
pub fn build_carried(b: &mut crate::scene::Builder, container: usize, l: &crate::ast::LinkStmt) -> Result<(), Diag> {
    let labels = match &l.labels {
        Some(v) => v.clone(),
        None => return Ok(()),
    };
    for s in &labels {
        if let crate::ast::Stmt::Node(ns) = s {
            let i = b.build_node(ns, container)?;
            b.nodes[container].children.retain(|&c| c != i);
        }
    }
    Ok(())
}

// The nodes a statement carries: built under frame f, detached, within its span.
fn carried_nodes(ctx: &Ctx, f: usize, span: Span) -> Vec<usize> {
    (0..ctx.nodes.len())
        .filter(|&i| {
            ctx.nodes[i].parent == Some(f)
                && !ctx.nodes[f].children.contains(&i)
                && ctx.nodes[i].span.start >= span.start
                && ctx.nodes[i].span.end <= span.end
                && ctx.nodes[i].prim != Prim::Text
        })
        .collect()
}

// ------------------------------------------------------------ mates and seats

// The frame-level part holding node i.
fn part_of(ctx: &Ctx, f: usize, i: usize) -> usize {
    let mut cur = i;
    while let Some(p) = ctx.nodes[cur].parent {
        if p == f {
            return cur;
        }
        cur = p;
    }
    i
}

// An annotation end: a GD&T node, or a bundle holding only annotation nodes.
fn is_annotation_end(ctx: &Ctx, i: usize) -> bool {
    if is_annotation_node(ctx, i) {
        return true;
    }
    let kids: Vec<usize> = ctx.nodes[i].children.iter().copied().filter(|&c| ctx.nodes[c].prim != Prim::Text).collect();
    !kids.is_empty() && kids.iter().all(|&c| is_annotation_end(ctx, c))
}

fn origin_in(ctx: &Ctx, f: usize, i: usize) -> P {
    apply(&to_frame(ctx, i, f), pt(0.0, 0.0))
}

fn gap_of(ctx: &Ctx, st: &St, f: usize) -> f64 {
    st.get("gap").and_then(|v| crate::style::value_num(&ctx.sheet.env, v)).unwrap_or(0.0) * crate::drawing::ps(ctx, f)
}

// `a || b`: parts seat along a shared normal — the later part moves to the
// earlier; an annotation end seats on the face (both axes, translate on top).
fn lay_mates(ctx: &mut Ctx, f: usize, sts: &[St], seats: bool) -> Result<(), Diag> {
    for st in sts {
        if st.op != "||" {
            continue;
        }
        for &li in &st.links {
            let (from, to) = (ctx.links[li].from, ctx.links[li].to);
            let seat = is_annotation_end(ctx, from) || is_annotation_end(ctx, to);
            if seat != seats {
                continue;
            }
            let gap = gap_of(ctx, st, f);
            if seat {
                let (node, face_to) = if is_annotation_end(ctx, from) { (from, true) } else { (to, false) };
                let face = ref_of(ctx, f, li, face_to)?;
                let n = face.n.unwrap_or(pt(0.0, 0.0));
                let target = face.p.add(n.mul(gap));
                let part = part_of(ctx, f, node);
                let cur = origin_in(ctx, f, part);
                let delta = if ctx.nodes[part].is("surface-finish") {
                    target.sub(cur)
                } else {
                    // the box's near side flush on the face
                    let nd = &ctx.nodes[part];
                    let (hw, hh) = (nd.w / 2.0, nd.h / 2.0);
                    let center = pt(nd.x, nd.y);
                    let want = target.add(pt(n.x * hw, n.y * hh));
                    want.sub(center)
                };
                ctx.nodes[part].x += delta.x;
                ctx.nodes[part].y += delta.y;
                continue;
            }
            let (pa, pb) = (part_of(ctx, f, from), part_of(ctx, f, to));
            let (mover, fixed_to) = if pb > pa { (pb, false) } else { (pa, true) };
            let l = &ctx.links[li];
            let delta = if l.from_anchor.is_none() && l.to_anchor.is_none() {
                let (fixed_node, moving_node) = if fixed_to { (to, from) } else { (from, to) };
                let t = ctx.comp[mover].translate;
                origin_in(ctx, f, fixed_node).sub(origin_in(ctx, f, moving_node)).add(pt(t.0, t.1))
            } else {
                let ra = ref_of(ctx, f, li, false)?;
                let rb = ref_of(ctx, f, li, true)?;
                let (fx, mv) = if fixed_to { (rb, ra) } else { (ra, rb) };
                let (nf, nm) = (fx.n.unwrap_or(pt(0.0, 0.0)), mv.n.unwrap_or(pt(0.0, 0.0)));
                if nf.cross(nm).abs() > 1e-6 || nf.len() < 1e-9 {
                    let name = |n: usize, a: &Option<String>| {
                        let p = crate::links::path_of(ctx, n);
                        match a {
                            Some(a) => format!("{}:{}", p, a),
                            None => p,
                        }
                    };
                    let msg = format!(
                        "mated anchors must face along one axis — '{} || {}' has no shared normal",
                        name(l.from, &l.from_anchor),
                        name(l.to, &l.to_anchor)
                    );
                    return Err(Diag::error("layout", &msg, st.span));
                }
                let want = fx.p.add(nf.mul(gap));
                // the mover's own translate still applies on top
                let t = ctx.comp[mover].translate;
                let d = want.sub(mv.p).add(pt(t.0, t.1));
                // along the shared normal only
                let ax = pt(nf.x.abs(), nf.y.abs());
                pt(d.x * ax.x, d.y * ax.y)
            };
            ctx.nodes[mover].x += delta.x;
            ctx.nodes[mover].y += delta.y;
        }
    }
    Ok(())
}

// ------------------------------------------------------------ connectors

// Is an endpoint a node standing on its own (annotation node, balloon,
// note, any non-part) rather than a feature of the geometry?
fn is_node_end(ctx: &Ctx, r: &Ref, anchored: bool) -> bool {
    if anchored {
        return false;
    }
    let n = &ctx.nodes[r.node];
    is_annotation_node(ctx, r.node) || n.is("note") || n.is("balloon")
}

// Where a line from `from` along d leaves node i's outline (its geometry).
fn outline_exit(ctx: &Ctx, f: usize, i: usize, from: P, d: P) -> P {
    let n = &ctx.nodes[i];
    if n.is("surface-finish") {
        return from;
    }
    let m = to_frame(ctx, i, f);
    let inv = match invert(&m) {
        Some(v) => v,
        None => return from,
    };
    let c = pt(-n.geo_off.0, -n.geo_off.1);
    let lp = apply(&inv, from).sub(c);
    let ld = apply_v(&inv, d);
    let (rx, ry) = (n.w / 2.0, n.h / 2.0);
    let t = if n.prim == Prim::Oval {
        // from inside the ellipse outwards
        let a2 = (ld.x / rx).powi(2) + (ld.y / ry).powi(2);
        let b2 = 2.0 * (lp.x * ld.x / (rx * rx) + lp.y * ld.y / (ry * ry));
        let c2 = (lp.x / rx).powi(2) + (lp.y / ry).powi(2) - 1.0;
        let disc = (b2 * b2 - 4.0 * a2 * c2).max(0.0);
        (-b2 + disc.sqrt()) / (2.0 * a2)
    } else {
        let mut t = f64::INFINITY;
        if ld.x.abs() > 1e-12 {
            t = t.min(((if ld.x > 0.0 { rx } else { -rx }) - lp.x) / ld.x);
        }
        if ld.y.abs() > 1e-12 {
            t = t.min(((if ld.y > 0.0 { ry } else { -ry }) - lp.y) / ld.y);
        }
        if t.is_finite() {
            t
        } else {
            0.0
        }
    };
    from.add(d.mul(t))
}

fn link_marker(kind: &str, tip: P, d_out: P) -> String {
    let m = crate::markers::marker_full(kind, (tip.x, tip.y), (d_out.x, d_out.y), 1.0);
    m.elems.join("")
}

// A straight connector between two ends (a leader onto a node, a balloon's
// fly-out, a note's arrow): link markers on the marked ends.
fn lay_connector(ctx: &Ctx, f: usize, st: &St, li: usize, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let l = &ctx.links[li];
    let ra = ref_of(ctx, f, li, false)?;
    let rb = ref_of(ctx, f, li, true)?;
    let na = is_node_end(ctx, &ra, l.from_anchor.is_some());
    let nb = is_node_end(ctx, &rb, l.to_anchor.is_some());
    let origin = |r: &Ref, node: bool| if node { origin_in(ctx, f, r.node) } else { r.p };
    let (pa, pb) = (origin(&ra, na), origin(&rb, nb));
    let d = pb.sub(pa).unit();
    let end = |r: &Ref, node: bool, p: P, dir: P| -> P {
        if node {
            outline_exit(ctx, f, r.node, p, dir)
        } else if r.feature {
            rim(ctx, f, r.node, dir).unwrap_or(p)
        } else {
            p
        }
    };
    let (lo, _, ro) = crate::links::split_op(&st.op);
    let mark = |s: &str, left: bool| -> Option<&'static str> {
        match (s, left) {
            ("<", true) | (">", false) => Some("arrow"),
            ("*", _) => Some("dot"),
            _ => None,
        }
    };
    // a dot marks the part itself: it sits on the part's origin
    let mut a = if mark(&lo, true) == Some("dot") { pa } else { end(&ra, na, pa, d) };
    let mut b = if mark(&ro, false) == Some("dot") { pb } else { end(&rb, nb, pb, d.mul(-1.0)) };
    let mut extra = Vec::new();
    let mut tips = Vec::new();
    if let Some(k) = mark(&lo, true) {
        extra.push(link_marker(k, a, d.mul(-1.0)));
        lay.tips.push(a);
        tips.push(a);
        a = a.add(d.mul(2.0));
    }
    if let Some(k) = mark(&ro, false) {
        extra.push(link_marker(k, b, d));
        lay.tips.push(b);
        tips.push(b);
        b = b.sub(d.mul(2.0));
    }
    let mut it = Item::new(Kind::Line, "lini-dim-line", vec![a, b]);
    it.halo = true;
    it.extra = extra;
    it.own_tips = tips.clone();
    it.mask_pts = tips;
    out.push(it);
    Ok(())
}

// ------------------------------------------------------------ hatching

thread_local! {
    static HATCHES: std::cell::RefCell<Vec<(String, String)>> = std::cell::RefCell::new(Vec::new());
}

fn expr_num(e: &crate::ast::Expr) -> Option<f64> {
    match e {
        crate::ast::Expr::Num(v, _) => Some(*v),
        crate::ast::Expr::Unary(o, b, _) if o == "-" => expr_num(b).map(|v| -v),
        _ => None,
    }
}

fn expr_term(e: &crate::ast::Expr) -> Option<crate::ast::Term> {
    Some(match e {
        crate::ast::Expr::Ident(s, sp) => crate::ast::Term::Ident(s.clone(), *sp),
        crate::ast::Expr::Var(s, sp) => crate::ast::Term::Var(s.clone(), *sp),
        crate::ast::Expr::Hash(s, sp) => crate::ast::Term::Hash(s.clone(), *sp),
        crate::ast::Expr::Call(n, a, sp) => crate::ast::Term::Call(n.clone(), a.clone(), *sp),
        _ => return None,
    })
}

// The evaluated value's debug form (the hatch id key spells its colour so).
fn debug_value(e: &crate::ast::Expr) -> String {
    use crate::ast::Expr;
    match e {
        Expr::Var(n, _) => format!("LiveVar {{ name: {:?}, raw: false }}", n),
        Expr::Ident(s, _) => format!("Ident({:?})", s),
        Expr::Hash(h, _) => format!("Hex({:?})", h),
        Expr::Str(s, _) => format!("String({:?})", s),
        Expr::Num(v, _) => format!("Number({:?})", v),
        Expr::Percent(v, _) => format!("Percent({:?})", v),
        Expr::Unary(o, b, _) if o == "-" => match expr_num(b) {
            Some(v) => format!("Number({:?})", -v),
            None => String::new(),
        },
        Expr::Tuple(xs, _) => format!("Tuple([{}])", xs.iter().map(debug_value).collect::<Vec<_>>().join(", ")),
        Expr::Call(n, args, _) if n == "oklch" => {
            let nums: Vec<f64> = args.iter().filter_map(expr_num).collect();
            let hex = crate::color::oklch_hex(nums.first().copied().unwrap_or(0.0), nums.get(1).copied().unwrap_or(0.0), nums.get(2).copied().unwrap_or(0.0), nums.get(3).copied());
            format!("Hex({:?})", hex.trim_start_matches('#'))
        }
        Expr::Call(n, args, _) => format!(
            "Call(ResolvedCall {{ name: {:?}, args: [{}] }})",
            n,
            args.iter().map(debug_value).collect::<Vec<_>>().join(", ")
        ),
        _ => String::new(),
    }
}

// `fill: hatch(angle, pitch[, colour])` → url(#…), registering the pattern.
// Its id hashes `{angles:?} {pitch} {colour:?}`.
pub fn hatch_css(args: &[crate::ast::Expr], vars: &mut Vec<String>, span: Span) -> Result<String, Diag> {
    if args.is_empty() {
        return Ok("hatch()".to_string());
    }
    // the angles: one, or a space list (`45 -45` is two, `45 - 45` one)
    let angles: Option<Vec<f64>> = match args.first() {
        Some(crate::ast::Expr::Tuple(xs, _)) => xs.iter().map(hatch_num).collect(),
        Some(e) => hatch_angles(e),
        None => Some(vec![45.0]),
    };
    let angles = match angles {
        Some(a) if !a.is_empty() => a,
        // not numbers: the call passes through as written
        _ => return Ok(format!("hatch({})", args.iter().map(expr_text).collect::<Vec<_>>().join(", "))),
    };
    let angle = angles[0];
    let pitch = args.get(1).and_then(expr_num).filter(|p| *p > 0.0).unwrap_or(6.0);
    let (color, dbg) = match args.get(2) {
        Some(e) => match (expr_num(e), expr_term(e)) {
            (Some(v), _) => (f4(v), debug_value(e)),
            (None, Some(t)) => (crate::style::color_css(&t, vars, span)?, debug_value(e)),
            _ => return Err(Diag::error("invalid-color", "invalid color", span)),
        },
        None => {
            use_var(vars, "stroke");
            ("var(--lini-stroke)".to_string(), "LiveVar { name: \"stroke\", raw: false }".to_string())
        }
    };
    let id = format!("lini-hatch-{}", crate::util::hash8(&format!("{:?} {} {}", angles, f4(pitch), dbg)));
    // the tile turns with the first angle; every further family is a line
    // at its angle from the first, through the tile's centre
    let h = pitch / 2.0;
    let mut lines = String::new();
    for (k, a) in angles.iter().enumerate() {
        let rel = if k == 0 { 0.0 } else { a - angle };
        let m = rel.rem_euclid(180.0);
        let (x1, y1, x2, y2) = if m.abs() < 1e-9 || (m - 180.0).abs() < 1e-9 {
            (h, 0.0, h, pitch)
        } else if (m - 90.0).abs() < 1e-9 {
            (0.0, h, pitch, h)
        } else {
            let t = rel.to_radians();
            let mut d = pt(t.sin(), -t.cos());
            if d.x < 0.0 {
                d = d.mul(-1.0);
            }
            (h - d.x * pitch, h - d.y * pitch, h + d.x * pitch, h + d.y * pitch)
        };
        lines.push_str(&format!("<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>", f4(x1), f4(y1), f4(x2), f4(y2)));
    }
    let def = format!(
        "<pattern id=\"{}\" patternUnits=\"userSpaceOnUse\" width=\"{}\" height=\"{}\" patternTransform=\"rotate({})\"><g style=\"stroke: {}\" stroke-width=\"0.75\">{}</g></pattern>",
        id,
        f4(pitch),
        f4(pitch),
        f4(angle),
        color,
        lines
    );
    HATCHES.with(|h| {
        let mut h = h.borrow_mut();
        if !h.iter().any(|e| e.0 == id) {
            h.push((id.clone(), def));
        }
    });
    Ok(format!("url(#{})", id))
}

// A number in a hatch call (a sum or difference folds).
fn hatch_num(e: &crate::ast::Expr) -> Option<f64> {
    match e {
        crate::ast::Expr::Bin(o, a, b, _) => {
            let (x, y) = (hatch_num(a)?, hatch_num(b)?);
            Some(match o.as_str() {
                "+" => x + y,
                "-" => x - y,
                "*" => x * y,
                "/" => x / y,
                _ => return None,
            })
        }
        _ => expr_num(e),
    }
}

// A hatch's angles: `45 -45` reads as two (a negative literal right after a
// value), `45 - 45` as one difference.
fn hatch_angles(e: &crate::ast::Expr) -> Option<Vec<f64>> {
    if let crate::ast::Expr::Bin(o, a, b, _) = e {
        if o == "-" {
            if let crate::ast::Expr::Num(v, sp) = b.as_ref() {
                // the minus belongs to the literal (its span covers it)
                if sp.end - sp.start > f4(*v).len() {
                    let mut out = hatch_angles(a)?;
                    out.push(-v);
                    return Some(out);
                }
            }
        }
    }
    hatch_num(e).map(|v| vec![v])
}

// An argument as written (for a call passed through).
fn expr_text(e: &crate::ast::Expr) -> String {
    match e {
        crate::ast::Expr::Num(v, _) => f4(*v),
        crate::ast::Expr::Ident(s, _) => s.clone(),
        crate::ast::Expr::Var(s, _) => format!("--{}", s),
        crate::ast::Expr::Hash(s, _) => format!("#{}", s),
        crate::ast::Expr::Str(s, _) => format!("{:?}", s),
        crate::ast::Expr::Unary(o, b, _) => format!("{}{}", o, expr_text(b)),
        crate::ast::Expr::Tuple(xs, _) => xs.iter().map(expr_text).collect::<Vec<_>>().join(" "),
        crate::ast::Expr::Bin(o, a, b, _) => format!("{} {} {}", expr_text(a), o, expr_text(b)),
        _ => String::new(),
    }
}

// The hatch patterns registered so far (drained).
pub fn take_hatches() -> Vec<String> {
    HATCHES.with(|h| h.borrow_mut().drain(..).map(|e| e.1).collect())
}

// ------------------------------------------------------------ inside diameters, angles

// `hole:top-right (o)`: the diametral line through a round feature along the
// anchor's direction, arrows inside on the rims. The value sits over the
// centre when the line holds it with both arrows (span >= text + 32); else
// it stands out past the anchor's rim, its box NOTE_OFFSET clear of the
// geometry, the line running on under it.
fn lay_inside_diameter(ctx: &Ctx, f: usize, st: &St, r: &Ref, lay: &mut Layout, out: &mut Vec<Item>) -> Result<(), Diag> {
    let k = crate::drawing::ps(ctx, f);
    let n = &ctx.nodes[r.node];
    let m = to_frame(ctx, r.node, f);
    let c = apply(&m, pt(-n.geo_off.0, -n.geo_off.1));
    // toward the anchor, and the reading direction
    let ua = r.p.sub(c).unit();
    let mut u = ua;
    if u.x < -1e-9 || (u.x.abs() <= 1e-9 && u.y > 0.0) {
        u = u.mul(-1.0);
    }
    let near = rim(ctx, f, r.node, ua).unwrap_or(c);
    let far = rim(ctx, f, r.node, ua.mul(-1.0)).unwrap_or(c);
    let t = dim_text(ctx, f, st, n.w / k, "⌀")?;
    let w = t.width();
    let rot = u.y.atan2(u.x).to_degrees();
    let up = pt(u.y, -u.x);
    let span = near.sub(far).len();
    let start = far.add(ua.mul(line_inset()));
    let (end, tc) = if span >= w + 32.0 {
        (near.sub(ua.mul(line_inset())), c.add(up.mul(text_off())))
    } else {
        let (hw, hh) = (w / 2.0, t.half_h());
        let hx = u.x.abs() * hw + u.y.abs() * hh;
        let hy = u.y.abs() * hw + u.x.abs() * hh;
        let o = c.add(up.mul(text_off()));
        let g = &lay.geo;
        let mut s = f64::INFINITY;
        if ua.x > 1e-9 {
            s = s.min((g.x1 + NOTE_OFFSET + hx - o.x) / ua.x);
        }
        if ua.x < -1e-9 {
            s = s.min((g.x0 - NOTE_OFFSET - hx - o.x) / ua.x);
        }
        if ua.y > 1e-9 {
            s = s.min((g.y1 + NOTE_OFFSET + hy - o.y) / ua.y);
        }
        if ua.y < -1e-9 {
            s = s.min((g.y0 - NOTE_OFFSET - hy - o.y) / ua.y);
        }
        let tc = o.add(ua.mul(s));
        let mut b = BBox::empty();
        b.add(tc.x - hx, tc.y - hy);
        b.add(tc.x + hx, tc.y + hy);
        lay.obstacles.push(b);
        (c.add(ua.mul(s + hw + 4.0)), tc)
    };
    let mut dl = Item::new(Kind::Line, "lini-dim-line", vec![start, end]);
    dl.halo = true;
    dl.own_tips = vec![near, far];
    out.push(dl);
    let mut m1 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(near, ua.mul(-1.0)));
    m1.tip = Some(near);
    out.push(m1);
    let mut m2 = Item::new(Kind::Polygon, "lini-marker lini-marker-dim", arrow(far, ua));
    m2.tip = Some(far);
    out.push(m2);
    out.extend(text_items(&t, tc, u, rot));
    Ok(())
}

// Where two lines cross (None when parallel).
fn line_cross(p: P, d: P, q: P, e: P) -> Option<P> {
    let den = d.cross(e);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = q.sub(p).cross(e) / den;
    Some(p.add(d.mul(t)))
}

// `a (<) b`: the angle between two edges — an arc about their crossing,
// the value out along the bisector.
fn lay_angle(ctx: &Ctx, f: usize, st: &St, li: usize, out: &mut Vec<Item>) -> Result<(), Diag> {
    let l = &ctx.links[li];
    let ra = ref_of(ctx, f, li, false)?;
    let rb = if l.one_ended {
        // a lone edge measures against its twin across the mirror (or
        // revolve) axis
        let tw = ra.twin.or_else(|| mirror_twin(ctx, f, &ra));
        match (ra.run, tw) {
            (Some(_), Some(t)) => Ref { run: Some(t), ..ra.clone() },
            _ => {
                let name = l.from_anchor.clone().unwrap_or_default();
                return Err(Diag::error("layout", &format!("'(<)' on ':{}' needs 'mirror:' — no twin to measure against", name), st.span));
            }
        }
    } else {
        ref_of(ctx, f, li, true)?
    };
    let ((a0, a1), (b0, b1)) = match (ra.run, rb.run) {
        (Some(x), Some(y)) => (x, y),
        _ => return Err(Diag::error("layout", "an angle reads two edges — a named segment, a '|line|', or a side", st.span)),
    };
    let v = match line_cross(a0, a1.sub(a0), b0, b1.sub(b0)) {
        Some(v) => v,
        None => return Err(Diag::error("layout", "the angle's edges are parallel — they never meet", st.span)),
    };
    // each edge points away from the crossing
    let far = |p0: P, p1: P| if p0.sub(v).len() > p1.sub(v).len() { p0 } else { p1 };
    let ua = far(a0, a1).sub(v).unit();
    let ub = far(b0, b1).sub(v).unit();
    let la = a1.sub(a0).len();
    let lb = b1.sub(b0).len();
    let rad = (la.min(lb) / 2.0).clamp(14.0, 40.0);
    let pa = v.add(ua.mul(rad));
    let pb = v.add(ub.mul(rad));
    let ang = ua.dot(ub).clamp(-1.0, 1.0).acos().to_degrees();
    let sweep = if ua.cross(ub) > 0.0 { 1 } else { 0 };
    let fmt = crate::sketch::fmt3;
    let d = format!("M {} {} A {} {} 0 0 {} {} {}", fmt(pa.x), fmt(pa.y), fmt(rad), fmt(rad), sweep, fmt(pb.x), fmt(pb.y));
    let mut it = Item::new(Kind::Path, "lini-dim-line", vec![pa, pb]);
    it.text = d;
    out.push(it);
    let bis = ua.add(ub).unit();
    let t = dim_text_sfx(ctx, f, st, ang, "", "°")?;
    out.extend(text_items(&t, v.add(bis.mul(rad + 12.0)), pt(1.0, 0.0), 0.0));
    Ok(())
}

// A balloon sizes to its number in natural units (its `width` stays a px floor).
pub fn measure_balloon(ctx: &mut Ctx, i: usize) {
    let floor = ctx.nodes[i].props.get("width").and_then(|v| crate::style::value_num(&ctx.sheet.env, v));
    ctx.comp[i].width = None;
    ctx.comp[i].height = None;
    crate::layout::measure(ctx, i, None);
    if let Some(fw) = floor {
        if ctx.nodes[i].w < fw {
            ctx.nodes[i].w = fw;
        }
    }
}

// ------------------------------------------------------------ notes

// A |note| in a drawing reads at 13 px with 6 / 10 padding (`|drawing| |note|`).
pub fn measure_note(ctx: &mut Ctx, i: usize) {
    let fs = 13.0;
    ctx.comp[i].font_size = fs;
    ctx.comp[i].padding = [6.0, 10.0, 6.0, 10.0];
    ctx.comp[i].width = None;
    ctx.comp[i].height = None;
    for c in ctx.nodes[i].children.clone() {
        if ctx.nodes[c].prim == Prim::Text {
            ctx.comp[c].font_size = fs;
        }
    }
    crate::layout::measure(ctx, i, None);
}

pub fn is_note(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].prim == Prim::Block && ctx.nodes[i].chain.first().map(|s| s == "note").unwrap_or(false)
}

// The drawing a note stands in (its nearest drawing ancestor).
fn note_frame(ctx: &Ctx, i: usize) -> Option<usize> {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if is_drawing(ctx, p) {
            return Some(p);
        }
        cur = ctx.nodes[p].parent;
    }
    None
}

fn in_drawing_frame(ctx: &Ctx, i: usize) -> bool {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if is_drawing(ctx, p) {
            return true;
        }
        cur = ctx.nodes[p].parent;
    }
    false
}

// A note: its outline folded at the top-right corner.
pub fn render_note(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let pad = " ".repeat(ind_n);
    let inner = " ".repeat(ind_n + 2);
    // (a note draws a path: it wears no block rule of its own)
    let had_block = out.used_types.iter().any(|t| t == "block");
    let cls = crate::render::node_classes(ctx, i, out).replace(" lini-block", " lini-path");
    if !had_block {
        out.used_types.retain(|t| t != "block");
    }
    let sw = c.stroke_width;
    let mut style = format!("stroke-width: {}", f4(sw));
    // a drawing that is no |drawing| element (the sheet itself) gives no
    // descendant rule to lean on: the note carries its size
    let frame = note_frame(ctx, i);
    let classed = frame.map(|f| ctx.nodes[f].is("drawing")).unwrap_or(false);
    if frame.is_some() && !classed && !ctx.nodes[i].props.contains_key("font-size") {
        style.push_str("; font-size: 13px");
    }
    let own = crate::render::inline_style(ctx, i, out, false)?;
    if !own.is_empty() {
        style = format!("{}; {}", style, own);
    }
    let mut head = format!("{}<g class=\"{}\"", pad, cls);
    if let Some(id) = &n.id {
        head.push_str(&format!(" data-id=\"{}\"", xml_escape(id)));
    }
    let tx = n.x + c.translate.0 + n.geo_off.0;
    let ty = n.y + c.translate.1 + n.geo_off.1;
    head.push_str(&format!(" style=\"{}\" transform=\"translate({},{})\">\n", xml_escape(&style), f4(tx), f4(ty)));
    s.push_str(&head);
    let w = (n.w + sw) / 2.0;
    let h = (n.h + sw) / 2.0;
    let fold = (0.34 * (n.h + sw)).min(15.0);
    s.push_str(&format!(
        "{}<path d=\"M {} {} L {} {} L {} {} L {} {} L {} {} Z\"/>\n",
        inner,
        -w,
        -h,
        w - fold,
        -h,
        w,
        -h + fold,
        w,
        h,
        -w,
        h
    ));
    s.push_str(&format!(
        "{}<g class=\"lini-node lini-path\" style=\"fill: var(--lini-stroke); stroke: none; stroke-width: 0\" transform=\"translate(0,0)\">\n",
        inner
    ));
    s.push_str(&format!("{}  <path d=\"M {} {} L {} {} L {} {} Z\"/>\n", inner, w - fold, -h, w, -h + fold, w - fold, -h + fold));
    s.push_str(&format!("{}</g>\n", inner));
    use_var(&mut out.vars, "stroke");
    if !out.used_types.iter().any(|t| t == "path") {
        push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
    }
    if classed {
        push_rule(out, "desc", ".lini-drawing .lini-note { font-size: 13px; }");
    }
    for &ch in &n.children {
        crate::render::render_node(ctx, ch, ind_n + 2, s, out)?;
    }
    s.push_str(&format!("{}</g>\n", pad));
    Ok(())
}

// ------------------------------------------------------------ descendant rules

fn compound_matches(c: &crate::ast::Compound, n: &crate::scene::Node) -> bool {
    if let Some(t) = &c.type_name {
        if !n.is(t) {
            return false;
        }
    }
    if let Some(id) = &c.id {
        if n.id.as_deref() != Some(id.as_str()) {
            return false;
        }
    }
    c.classes.iter().all(|k| n.classes.contains(k))
}

fn has_ancestor(nodes: &[crate::scene::Node], i: usize, c: &crate::ast::Compound) -> bool {
    let mut cur = nodes[i].parent;
    while let Some(p) = cur {
        if p != 0 && compound_matches(c, &nodes[p]) {
            return true;
        }
        cur = nodes[p].parent;
    }
    false
}

// The declarations descendant rules give node i, minus what its own id
// rules and inline style set.
pub fn desc_decls(sheet: &crate::scene::SheetModel, nodes: &[crate::scene::Node], i: usize) -> Vec<(String, crate::ast::Value)> {
    let n = &nodes[i];
    let mut out: Vec<(String, crate::ast::Value)> = Vec::new();
    for (anc, desc, decls) in &sheet.desc_rules {
        if !compound_matches(desc, n) || !has_ancestor(nodes, i, anc) {
            continue;
        }
        for d in decls {
            let own = n.inline.iter().any(|x| x.name == d.name)
                || sheet.id_rules.iter().any(|(rid, ds)| Some(rid.as_str()) == n.id.as_deref() && ds.iter().any(|x| x.name == d.name));
            if own {
                continue;
            }
            out.retain(|e| e.0 != d.name);
            out.push((d.name.clone(), d.value.clone()));
        }
    }
    out
}

// Descendant rules between types become stylesheet rules; an id or class
// ancestor's ride inline (see `desc_inline`).
pub fn desc_css(ctx: &Ctx, out: &mut Out) -> Result<(), Diag> {
    for (anc, desc, decls) in &ctx.sheet.desc_rules {
        let (Some(at), Some(dt)) = (&anc.type_name, &desc.type_name) else { continue };
        if anc.id.is_some() || !anc.classes.is_empty() {
            continue;
        }
        let used = (1..ctx.nodes.len()).any(|i| compound_matches(desc, &ctx.nodes[i]) && has_ancestor(&ctx.nodes, i, anc));
        if !used {
            continue;
        }
        let props: Vec<(String, crate::ast::Value)> = decls.iter().map(|d| (d.name.clone(), d.value.clone())).collect();
        let mut vars = Vec::new();
        let css = crate::render::css_decls(ctx, &props, &mut vars, 2.0, false)?;
        for v in vars {
            use_var(&mut out.vars, &v);
        }
        if css.is_empty() {
            continue;
        }
        let body = css.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ");
        push_rule(out, "desc", &format!(".lini-{} .lini-{} {{ {}; }}", at, dt, body));
    }
    Ok(())
}

// Declarations an id / class ancestor's descendant rule puts inline.
pub fn desc_inline(ctx: &Ctx, i: usize) -> Vec<(String, crate::ast::Value)> {
    let n = &ctx.nodes[i];
    let mut out: Vec<(String, crate::ast::Value)> = Vec::new();
    for (anc, desc, decls) in &ctx.sheet.desc_rules {
        if anc.id.is_none() && anc.classes.is_empty() {
            continue;
        }
        if !compound_matches(desc, n) || !has_ancestor(&ctx.nodes, i, anc) {
            continue;
        }
        for d in decls {
            out.retain(|e| e.0 != d.name);
            out.push((d.name.clone(), d.value.clone()));
        }
    }
    out
}

// ------------------------------------------------------------ detail and section views

#[derive(Clone, Copy, Debug)]
struct Detail {
    // the drawing holding the view, the clipped copy, the ring, the magnifier
    det: usize,
    clip: usize,
    ring: usize,
    mag: usize,
}

thread_local! {
    static DETAILS: std::cell::RefCell<Vec<Detail>> = std::cell::RefCell::new(Vec::new());
}

fn details() -> Vec<Detail> {
    DETAILS.with(|d| d.borrow().clone())
}

fn decl_ident(n: &crate::scene::Node, k: &str) -> Option<String> {
    n.inline.iter().rev().find(|d| d.name == k).and_then(|d| ident_of(&d.value)).map(|s| s.to_string())
}

fn decl_num(n: &crate::scene::Node, k: &str) -> Option<f64> {
    let d = n.inline.iter().rev().find(|d| d.name == k)?;
    match crate::style::single_term(&d.value)? {
        crate::ast::Term::Num(v, _, _) => Some(*v),
        _ => None,
    }
}

// Deep-copy a subtree under `parent` (ids register in the new scope).
fn clone_into(b: &mut crate::scene::Builder, src: usize, parent: usize) -> usize {
    let mut n = b.nodes[src].clone();
    n.children = vec![];
    n.parent = None;
    let id = n.id.clone();
    let i = b.add(n, Some(parent));
    if let Some(id) = id {
        let scope = b.child_scope(parent);
        b.ids.entry((scope, id)).or_insert(i);
    }
    for c in b.nodes[src].children.clone() {
        clone_into(b, c, i);
    }
    i
}

fn ratio_text(k: f64) -> String {
    if k >= 1.0 {
        format!("{}:1", fmt_val(k))
    } else {
        format!("1:{}", fmt_val(1.0 / k))
    }
}

// Views whose `of:` names no marker: (view, the name written).
thread_local! {
    static OF_MISSING: std::cell::RefCell<HashMap<usize, String>> = std::cell::RefCell::new(HashMap::new());
}

// `|drawing| { of: c }`: a detail view re-lays the ringed drawing's parts,
// clipped to the ring; `{ of: a }` a section view. Both caption themselves.
pub fn detail_views(b: &mut crate::scene::Builder) -> Result<(), Diag> {
    datum_duplicates(b)?;
    DETAILS.with(|d| d.borrow_mut().clear());
    OF_MISSING.with(|d| d.borrow_mut().clear());
    let n0 = b.nodes.len();
    // (the sheet itself is no view)
    for det in 1..n0 {
        let decl = match b.nodes[det].inline.iter().rev().find(|d| d.name == "of") {
            Some(d) => d.value.clone(),
            None => continue,
        };
        let span = b.nodes[det].span;
        let (src, scale) = match ident_of(&decl).map(|s| s.to_string()) {
            Some(target) => {
                match (0..n0).find(|&k| b.nodes[k].id.as_deref() == Some(target.as_str()) && (b.nodes[k].is("magnifier") || b.nodes[k].is("plane"))) {
                    Some(s) => (Some(s), decl_num(&b.nodes[det], "scale").unwrap_or(1.0)),
                    None => {
                        OF_MISSING.with(|d| d.borrow_mut().insert(det, target));
                        continue;
                    }
                }
            }
            None => (None, 1.0),
        };
        let text = match src {
            Some(src) => {
                let letter = b.nodes[src].label.clone().unwrap_or_default();
                if b.nodes[src].is("magnifier") {
                    if let Some(frame) = b.nodes[src].parent {
                        let mut clip = crate::scene::Node::new(Prim::Block, vec!["block".to_string()], span);
                        clip.auto = false;
                        let ci = b.add(clip, Some(det));
                        // the view's own place in the drawing stays out of the copy
                        let mut up = Vec::new();
                        let mut cur = Some(det);
                        while let Some(c) = cur {
                            up.push(c);
                            cur = b.nodes[c].parent;
                        }
                        for c in b.nodes[frame].children.clone() {
                            let n = &b.nodes[c];
                            if c == src || up.contains(&c) || n.prim == Prim::Text || n.is("plane") || n.is("caption") || n.is("magnifier") {
                                continue;
                            }
                            clone_into(b, c, ci);
                        }
                        let ring = crate::scene::Node::new(Prim::Oval, vec!["magnifier".to_string(), "oval".to_string()], span);
                        let ri = b.add(ring, Some(det));
                        // the copy and its ring come before the view's own children
                        let ch = &mut b.nodes[det].children;
                        ch.retain(|&x| x != ci && x != ri);
                        ch.insert(0, ri);
                        ch.insert(0, ci);
                        DETAILS.with(|d| d.borrow_mut().push(Detail { det, clip: ci, ring: ri, mag: src }));
                    }
                }
                if b.nodes[src].is("plane") {
                    Some(format!("{}-{} ({})", letter, letter, ratio_text(scale)))
                } else {
                    Some(format!("{} ({})", letter, ratio_text(scale)))
                }
            }
            None => None,
        };
        let cn = crate::scene::Node::new(Prim::Block, vec!["footnote".to_string(), "caption".to_string(), "block".to_string()], span);
        let cap = b.add(cn, Some(det));
        if let Some(text) = text {
            b.text_node(&text, &[], None, span, cap);
        }
    }
    Ok(())
}

// Whether node i sits in a drawing (its nearest frame draws).
fn under_drawing(ctx: &Ctx, i: usize) -> bool {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if crate::drawing::is_frame(ctx, p) {
            return matches!(ctx.comp[p].layout.as_str(), "drawing" | "floorplan");
        }
        cur = ctx.nodes[p].parent;
    }
    false
}

// Placement checks, node by node in document order (the drawing layout
// pass): a view's marker, GD&T symbols outside a drawing, a control outside
// its frame, a magnifier's diameter.
pub fn node_check(ctx: &Ctx, i: usize) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    if let Some(t) = OF_MISSING.with(|d| d.borrow().get(&i).cloned()) {
        return Err(Diag::error("layout", &format!("'of' finds no marker '{}'", t), n.span));
    }
    if n.prim == Prim::Text {
        return Ok(());
    }
    for t in ["feature-control", "control", "surface-finish", "datum"] {
        if n.is(t) {
            if !under_drawing(ctx, i) {
                return Err(Diag::error(
                    "layout",
                    &format!("'|{}|' annotates a drawing — it belongs in a 'layout: drawing' (or its 'floorplan' dialect)", t),
                    n.span,
                ));
            }
            if t == "control" && !n.parent.map(|p| ctx.nodes[p].is("feature-control")).unwrap_or(false) {
                return Err(Diag::error("layout", "'|control|' is a '|feature-control|' row", n.span));
            }
            break;
        }
    }
    // a frame validates its rows (characteristic, tol, datums declared)
    if n.is("feature-control") && n.prim != Prim::Text {
        fc_rows(ctx, i)?;
    }
    if n.is("magnifier") && under_drawing(ctx, i) && !n.props.contains_key("width") && !is_ring(i) {
        return Err(Diag::error("missing-required-property", "'|magnifier|' requires 'width' — its diameter", n.span));
    }
    Ok(())
}

// Children that are no part of a drawing's geometry: annotations and notes.
pub fn not_geometry(ctx: &Ctx, i: usize) -> bool {
    is_annotation_node(ctx, i) || ctx.nodes[i].is("note")
}

pub fn is_clip(ctx: &Ctx, i: usize) -> bool {
    let _ = ctx;
    details().iter().any(|d| d.clip == i)
}

pub fn is_ring(i: usize) -> bool {
    details().iter().any(|d| d.ring == i)
}

// The magnifier's radius and centre in its drawing's units.
fn mag_geom(ctx: &Ctx, mag: usize) -> (f64, P) {
    let n = &ctx.nodes[mag];
    let w = n.props.get("width").and_then(|v| crate::style::value_num(&ctx.sheet.env, v)).unwrap_or(0.0);
    let t = n.props.get("translate").map(|v| crate::style::value_nums(&ctx.sheet.env, v)).unwrap_or_default();
    let c = if t.len() == 2 { pt(t[0], t[1]) } else { pt(0.0, 0.0) };
    (w / 2.0, c)
}

// The clipped copy: the ring's circle box, the parts about the ring's centre.
pub fn measure_clip(ctx: &mut Ctx, i: usize) {
    let d = match details().into_iter().find(|d| d.clip == i) {
        Some(d) => d,
        None => return,
    };
    let k = crate::drawing::ps(ctx, d.det);
    let (r, c) = mag_geom(ctx, d.mag);
    let rr = r * k;
    ctx.nodes[i].w = 2.0 * rr;
    ctx.nodes[i].h = 2.0 * rr;
    for ch in ctx.nodes[i].children.clone() {
        crate::drawing::measure_part_pub(ctx, ch);
        let n = &mut ctx.nodes[ch];
        n.x = -c.x * k - n.geo_off.0;
        n.y = -c.y * k - n.geo_off.1;
    }
}

pub fn measure_ring(ctx: &mut Ctx, i: usize) {
    let d = match details().into_iter().find(|d| d.ring == i) {
        Some(d) => d,
        None => return,
    };
    let k = crate::drawing::ps(ctx, d.det);
    let (r, _) = mag_geom(ctx, d.mag);
    let sw = stroke_w(ctx, i);
    ctx.nodes[i].w = 2.0 * r * k - sw;
    ctx.nodes[i].h = 2.0 * r * k - sw;
}

// The clipped copy: a block clipped to the ring's circle.
pub fn render_clip(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let pad = " ".repeat(ind_n);
    let r = n.w / 2.0;
    let id = format!("lini-clip-{}", crate::util::hash8(&f4(r)));
    let def = format!("<clipPath id=\"{}\" clipPathUnits=\"userSpaceOnUse\"><circle r=\"{}\"/></clipPath>", id, f4(r));
    if !out.defs.contains(&def) {
        out.defs.push(def);
    }
    let cls = crate::render::node_classes(ctx, i, out);
    let tx = n.x + c.translate.0 + n.geo_off.0;
    let ty = n.y + c.translate.1 + n.geo_off.1;
    s.push_str(&format!("{}<g class=\"{}\" clip-path=\"url(#{})\" transform=\"translate({},{})\">\n", pad, cls, id, f4(tx), f4(ty)));
    s.push_str(&format!(
        "{}  <rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"0\" ry=\"0\"/>\n",
        pad,
        f4(-n.w / 2.0),
        f4(-n.h / 2.0),
        f4(n.w),
        f4(n.h)
    ));
    for &ch in &n.children {
        crate::render::render_node(ctx, ch, ind_n + 2, s, out)?;
    }
    s.push_str(&format!("{}</g>\n", pad));
    Ok(())
}
