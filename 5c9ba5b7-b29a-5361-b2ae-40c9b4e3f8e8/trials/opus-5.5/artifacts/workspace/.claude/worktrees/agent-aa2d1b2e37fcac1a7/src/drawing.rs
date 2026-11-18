// Drawings and stacks [SPEC 12, 15]: the shared-datum layouts, px-per-unit
// scaling, sketch geometry (mirror / revolve / break / thread), holes, the
// generated drafting chrome (centrelines, shoulders, thread and break lines,
// pitch circles), and `pattern:` copies.
//
// Pipeline: `expand` (after the first cascade) runs every pen, adds chrome
// nodes and pattern copies; the cascade is recomputed; `prepare` scales the
// length properties by each node's px scale; `measure` lays out frames.
//
// Model notes (for annotations, which read this geometry):
// - px scale: `ps(ctx, i)` = px per unit for node i (frame px-per-unit ×
//   inherited `scale`); widths / heights / translates arrive already scaled.
// - A frame (drawing / stack) puts every child's origin on its datum; a
//   nested frame then centres its content (a root frame keeps its datum).
//   Parts in a drawing are sized by width / height (or padding), never by
//   their content; their children sit on the part's origin too.
// - A sketch's node box is its path's bounds: `geo_off` = −(bounds centre),
//   so its group transform is its pen origin. Path and children draw in the
//   pen frame.
// - `ctx.sk.laid[&i]`: the laid-out sketch (shape in px, path data, bounds,
//   break = (along x, cut a, cut b, shift) in px); `sketch_tags` lists its
//   `:name` segments and point() stations in that frame.
// - Patterns and mirrored features turn a node into a wrapper (keeps its id;
//   `ctx.sk.wrappers`) whose children are the copies (`pattern_copy`).

use crate::ast::{Decl, Term, Value};
use crate::compile::Ctx;
use crate::diag::{Diag, Span};
use crate::geom::BBox;
use crate::render::Out;
use crate::scene::Node;
use crate::sketch::{self, fmt3, pt, Seg, Shape, Sub, P};
use crate::style::{ident_of, single_term, value_nums};
use crate::types::Prim;
use crate::util::f4;
use std::collections::{HashMap, HashSet};

// Drafting constants (px) [SPEC 15.7].
const AXIS_OVERHANG: f64 = 4.0;
const BREAK_GAP: f64 = 12.0;
const THREAD_EXTERNAL: f64 = 0.61343;
const THREAD_INTERNAL: f64 = 0.54125;

#[derive(Clone, Debug)]
pub enum Chrome {
    // a mirror / revolve axis centreline along direction d
    Axis(P),
    HoleX,
    HoleY,
    Edges,
    Thread,
    Break(usize),
    // a hole's ¾ thread arc, pitch
    ThreadArc(f64),
    // a radial pattern's pitch circle, radius in units
    Ring(f64),
}

#[derive(Clone, Debug)]
pub enum Geom {
    Line(P, P),
    Poly(Vec<P>),
    Path(String),
}

#[derive(Clone, Debug)]
pub struct Wrapper {
    // copy offsets in units, scaled at layout
    pub offsets: Vec<(f64, f64)>,
    // a mirror's images keep the wrapper on the feature's own origin (a
    // pattern's wrapper is centred on its copies instead)
    pub mirror: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Laid {
    pub shape: Shape,
    pub path: String,
    pub bbox: Option<BBox>,
    // break: (axis is x, cut a, cut b, shift) in px
    pub brk: Option<(bool, f64, f64, f64)>,
    pub edges: Vec<(f64, f64)>,
    // edges / thread run along x (else y)
    pub along_x: bool,
    pub thread: Vec<(P, P)>,
    pub breaks: Vec<Vec<P>>,
}

#[derive(Default)]
pub struct State {
    // the pen's result per sketch node, in units
    pub base: HashMap<usize, Shape>,
    // laid out per sketch node: px, in the pen frame
    pub laid: HashMap<usize, Laid>,
    pub chrome: HashMap<usize, Chrome>,
    pub geoms: HashMap<usize, Vec<Geom>>,
    pub wrappers: HashMap<usize, Wrapper>,
    pub copies: HashSet<usize>,
    // mirrored feature copies: the mirror's axis direction
    pub reflect: HashMap<usize, Vec<P>>,
    // px per unit (frame px-per-unit × scale) per node
    pub ps: Vec<f64>,
    // laid-out section planes
    pub planes: HashMap<usize, PlaneGeo>,
}

// ------------------------------------------------------------ frames

fn layout_of(ctx: &Ctx, i: usize) -> &str {
    ctx.comp[i].layout.as_str()
}

fn is_container(ctx: &Ctx, i: usize) -> bool {
    !matches!(ctx.nodes[i].prim, Prim::Text | Prim::Line | Prim::Poly | Prim::Path | Prim::Sketch)
}

// "drawing" (incl. floorplan), "stack", or None for a node that is a frame.
fn frame_kind(ctx: &Ctx, i: usize) -> Option<&'static str> {
    if !is_container(ctx, i) {
        return None;
    }
    match layout_of(ctx, i) {
        "drawing" | "floorplan" => Some("drawing"),
        "stack" => Some("stack"),
        _ => None,
    }
}

pub fn is_frame(ctx: &Ctx, i: usize) -> bool {
    frame_kind(ctx, i).is_some()
}

// The nearest frame strictly above `i`.
fn enclosing_frame(ctx: &Ctx, i: usize) -> Option<usize> {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if frame_kind(ctx, p).is_some() {
            return Some(p);
        }
        cur = ctx.nodes[p].parent;
    }
    None
}

// A node keeping its own (flow / grid / …) layout even inside a drawing.
fn is_layout_container(ctx: &Ctx, i: usize) -> bool {
    let lay = ctx.comp[i].layout.as_str();
    (lay != "flow" && !lay.is_empty() && frame_kind(ctx, i).is_none()) || ctx.nodes[i].is("row") || ctx.nodes[i].is("column")
}

// Is `i` a part of a drawing (not inside a stack or a layout container)?
pub fn in_drawing(ctx: &Ctx, i: usize) -> bool {
    let mut cur = ctx.nodes[i].parent;
    while let Some(p) = cur {
        if let Some(k) = frame_kind(ctx, p) {
            return k == "drawing";
        }
        if is_layout_container(ctx, p) {
            return false;
        }
        cur = ctx.nodes[p].parent;
    }
    false
}

fn unit_mm(u: &str) -> Option<f64> {
    match u {
        "px" => Some(0.0),
        "mm" => Some(1.0),
        "cm" => Some(10.0),
        "m" => Some(1000.0),
        "in" => Some(25.4),
        _ => None,
    }
}

fn density(ctx: &Ctx) -> f64 {
    ctx.nodes[0].props.get("density").and_then(|v| crate::style::value_num(&ctx.sheet.env, v)).unwrap_or(4.0)
}

// px per unit of a frame node (before scale).
fn frame_ppu(ctx: &Ctx, f: usize) -> f64 {
    let mut cur = Some(f);
    let mut unit: Option<String> = None;
    while let Some(k) = cur {
        if frame_kind(ctx, k).is_some() {
            if let Some(u) = ctx.nodes[k].props.get("unit").and_then(ident_of) {
                unit = Some(u.to_string());
                break;
            }
        }
        cur = ctx.nodes[k].parent;
    }
    match unit.as_deref().and_then(unit_mm) {
        Some(0.0) => 1.0,
        Some(mm) => density(ctx) * mm,
        None => {
            if frame_kind(ctx, f) == Some("drawing") {
                density(ctx)
            } else {
                1.0
            }
        }
    }
}

fn scale_of(ctx: &Ctx, i: usize) -> f64 {
    let mut cur = Some(i);
    while let Some(k) = cur {
        if let Some(v) = ctx.nodes[k].props.get("scale") {
            let xs = value_nums(&ctx.sheet.env, v);
            if xs.len() == 1 {
                return xs[0];
            }
            return 1.0;
        }
        cur = ctx.nodes[k].parent;
    }
    1.0
}

fn ps_self(ctx: &Ctx, i: usize) -> f64 {
    let mut cur = Some(i);
    let mut ppu = 1.0;
    while let Some(k) = cur {
        if frame_kind(ctx, k).is_some() {
            ppu = frame_ppu(ctx, k);
            break;
        }
        cur = ctx.nodes[k].parent;
    }
    ppu * scale_of(ctx, i)
}

pub fn ps(ctx: &Ctx, i: usize) -> f64 {
    ctx.sk.ps.get(i).copied().unwrap_or(1.0)
}

// ------------------------------------------------------------ helpers

fn decl_span(ctx: &Ctx, i: usize, name: &str) -> Span {
    let n = &ctx.nodes[i];
    if let Some(d) = n.inline.iter().rev().find(|d| d.name == name) {
        return d.span;
    }
    if let Some(id) = &n.id {
        for (rid, ds) in ctx.sheet.id_rules.iter().rev() {
            if rid == id {
                if let Some(d) = ds.iter().rev().find(|d| d.name == name) {
                    return d.span;
                }
            }
        }
    }
    for c in n.classes.iter().rev() {
        if let Some(cr) = ctx.sheet.class(c) {
            if let Some(d) = cr.decls.iter().rev().find(|d| d.name == name) {
                return d.span;
            }
        }
    }
    for t in &n.chain {
        if let Some(d) = ctx.sheet.type_rule(t).into_iter().rev().find(|d| d.name == name) {
            return d.span;
        }
        if let Some(df) = ctx.sheet.define(t) {
            if let Some(d) = df.decls.iter().rev().find(|d| d.name == name) {
                return d.span;
            }
        }
    }
    n.props.get(name).map(|v| v.span).unwrap_or(n.span)
}

fn has(ctx: &Ctx, i: usize, name: &str) -> bool {
    ctx.nodes[i].props.contains_key(name)
}

fn is_hole(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].is("hole")
}

fn mk_decl(name: &str, v: Term, span: Span) -> Decl {
    Decl { name: name.to_string(), name_span: span, value: Value { groups: vec![vec![v]], span }, span }
}

fn ident(s: &str, span: Span) -> Term {
    Term::Ident(s.to_string(), span)
}

fn num(x: f64, span: Span) -> Term {
    Term::Num(x, f4(x), span)
}

// Axis directions of the `mirror:` / `revolve:` vocabulary.
fn axis_dir(v: &Term, env: &crate::eval::Env) -> Option<P> {
    match v {
        Term::Ident(s, _) if s == "x-axis" => Some(pt(1.0, 0.0)),
        Term::Ident(s, _) if s == "y-axis" => Some(pt(0.0, -1.0)),
        _ => crate::style::term_num(env, v).map(|b| sketch::bearing_dir(b.to_radians())),
    }
}

// The mirror steps of a node (None = no mirror).
fn mirror_steps(ctx: &Ctx, i: usize) -> Result<Vec<P>, Diag> {
    let v = match ctx.nodes[i].props.get("mirror") {
        Some(v) => v.clone(),
        None => return Ok(vec![]),
    };
    if v.groups.len() > 1 {
        return Err(Diag::error("malformed-value", "'mirror' takes one value, not a comma list", decl_span(ctx, i, "mirror")));
    }
    let mut out = Vec::new();
    for t in &v.groups[0] {
        if let Term::Ident(s, _) = t {
            if s == "none" {
                continue;
            }
        }
        match axis_dir(t, &ctx.sheet.env) {
            Some(d) => out.push(d),
            None => return Err(Diag::error("layout", "'mirror' takes x-axis, y-axis, a bearing, or none", ctx.nodes[i].span)),
        }
    }
    Ok(out)
}

fn revolve_axis(ctx: &Ctx, i: usize) -> Result<Option<P>, Diag> {
    let v = match ctx.nodes[i].props.get("revolve") {
        Some(v) => v,
        None => return Ok(None),
    };
    match ident_of(v) {
        Some("x-axis") => Ok(Some(pt(1.0, 0.0))),
        Some("y-axis") => Ok(Some(pt(0.0, -1.0))),
        _ => Err(Diag::error("layout", "'revolve' takes x-axis or y-axis", ctx.nodes[i].span)),
    }
}

// break: a b [x-axis|y-axis] → (along x?, a, b) in units
fn break_spec(ctx: &Ctx, i: usize) -> Result<Option<(bool, f64, f64)>, Diag> {
    let v = match ctx.nodes[i].props.get("break") {
        Some(v) => v,
        None => return Ok(None),
    };
    let bad = || {
        Diag::error(
            "layout",
            "'break' takes two stations 'a b' — a < b — and an optional x-axis / y-axis",
            ctx.nodes[i].span,
        )
    };
    let mut nums = Vec::new();
    let mut along_x = true;
    for g in &v.groups {
        for t in g {
            match t {
                Term::Ident(s, _) if s == "x-axis" => along_x = true,
                Term::Ident(s, _) if s == "y-axis" => along_x = false,
                _ => match crate::style::term_num(&ctx.sheet.env, t) {
                    Some(x) => nums.push(x),
                    None => return Err(bad()),
                },
            }
        }
    }
    if nums.len() != 2 || nums[0] >= nums[1] {
        return Err(bad());
    }
    Ok(Some((along_x, nums[0], nums[1])))
}

// Validate a sketch's `thread:` (segment + pitch, on a revolved profile).
fn check_thread(ctx: &Ctx, i: usize, rev: Option<P>) -> Result<Option<(Option<String>, f64)>, Diag> {
    if !has(ctx, i, "thread") {
        return Ok(None);
    }
    let span = ctx.nodes[i].span;
    let spec = thread_spec(ctx, i);
    let (seg, pitch) = match spec.clone() {
        Some((Some(s), p)) if p > 0.0 => (s, p),
        _ => return Err(Diag::error("layout", "'thread' takes a segment and its pitch — 'thread: m8 1.5'", span)),
    };
    if rev.is_none() {
        return Err(Diag::error("layout", "'thread' dresses a revolved profile — add 'revolve: x-axis'", span));
    }
    let base = &ctx.sk.base[&i];
    let tags = base.tags();
    let tag = match tags.iter().find(|t| t.name == seg) {
        Some(t) => t,
        None => {
            let names: Vec<String> = tags.iter().map(|t| t.name.clone()).collect();
            let msg = format!("no segment '{}' in this 'draw:'{}", seg, suggest(&seg, &names));
            return Err(Diag::error("layout", &msg, span));
        }
    };
    let ok = match &tag.kind {
        sketch::TagKind::Seg(Seg::Line { a, b }) => {
            let d = rev.unwrap();
            let v = b.sub(*a);
            v.len() > 0.0 && v.cross(d).abs() < 1e-9 * v.len().max(1.0)
        }
        _ => false,
    };
    if !ok {
        return Err(Diag::error(
            "layout",
            &format!("'thread' runs along the axis — '{}' must be a straight run parallel to it", seg),
            span,
        ));
    }
    Ok(Some((Some(seg), pitch)))
}

// "; did you mean 'a', 'b'?" — up to two names within edit distance 2.
pub fn suggest(name: &str, names: &[String]) -> String {
    let mut c: Vec<(usize, usize, &String)> = names
        .iter()
        .enumerate()
        .map(|(k, n)| (crate::util::levenshtein(name, n), k, n))
        .filter(|(d, _, _)| *d <= 2)
        .collect();
    c.sort_by_key(|(d, k, _)| (*d, *k));
    c.truncate(2);
    if c.is_empty() {
        return String::new();
    }
    let list: Vec<String> = c.iter().map(|(_, _, n)| format!("'{}'", n)).collect();
    format!("; did you mean {}?", list.join(", "))
}

// thread: [segment] pitch
fn thread_spec(ctx: &Ctx, i: usize) -> Option<(Option<String>, f64)> {
    let v = ctx.nodes[i].props.get("thread")?;
    let mut seg = None;
    let mut pitch = None;
    for t in v.groups.iter().flatten() {
        match t {
            Term::Ident(s, _) => seg = Some(s.clone()),
            _ => {
                if let Some(x) = crate::style::term_num(&ctx.sheet.env, t) {
                    pitch = Some(x);
                }
            }
        }
    }
    pitch.map(|p| (seg, p))
}

// ------------------------------------------------------------ expansion

fn add_node(ctx: &mut Ctx, mut n: Node, parent: usize) -> usize {
    n.parent = Some(parent);
    n.scope = ctx.nodes[parent].scope;
    let i = ctx.nodes.len();
    ctx.nodes.push(n);
    ctx.comp.push(ctx.comp[parent].clone());
    ctx.nodes[parent].children.push(i);
    i
}

fn add_chrome(ctx: &mut Ctx, parent: usize, chain: &[&str], prim: Prim, kind: Chrome) -> usize {
    let span = ctx.nodes[parent].span;
    let n = Node::new(prim, chain.iter().map(|s| s.to_string()).collect(), span);
    let i = add_node(ctx, n, parent);
    ctx.sk.chrome.insert(i, kind);
    i
}

// The declarations `#id` rules give a node: its copies (which carry no id)
// wear them inline.
fn id_decls(ctx: &Ctx, i: usize) -> Vec<Decl> {
    let mut out = Vec::new();
    if let Some(id) = &ctx.nodes[i].id {
        for (rid, ds) in &ctx.sheet.id_rules {
            if rid == id {
                out.extend(ds.iter().cloned());
            }
        }
    }
    out
}

fn reflect(p: P, d: P) -> P {
    let k = 2.0 * p.dot(d);
    clean(pt(d.x * k - p.x, d.y * k - p.y))
}

// Turn node `c` (at `p`) into a wrapper of its mirror images (units).
fn mirror_wrap(ctx: &mut Ctx, c: usize, p: P, images: &[(P, Vec<P>)]) {
    let kids = std::mem::take(&mut ctx.nodes[c].children);
    let was_wrapper = ctx.sk.wrappers.remove(&c);
    for (_, ds) in images {
        let mut n = ctx.nodes[c].clone();
        n.children = vec![];
        n.id = None;
        n.inline = id_decls(ctx, c).into_iter().chain(n.inline.into_iter()).collect();
        n.inline.retain(|d| d.name != "translate");
        n.props.remove("translate");
        let cp = add_node(ctx, n, c);
        ctx.comp[cp] = ctx.comp[c].clone();
        ctx.sk.copies.insert(cp);
        if let Some(w) = &was_wrapper {
            ctx.sk.wrappers.insert(cp, w.clone());
        }
        if let Some(b) = ctx.sk.base.get(&c).cloned() {
            ctx.sk.base.insert(cp, b);
        }
        if !ds.is_empty() {
            ctx.sk.reflect.insert(cp, ds.clone());
            // a sketch copy draws its pen reflected about its own origin
            if let Some(b) = ctx.sk.base.get(&c).cloned() {
                let mut m = b;
                for d in ds {
                    let d = *d;
                    m = Shape {
                        subs: m.subs.iter().map(|s| s.map(&move |q| reflect(q, d), true)).collect(),
                        points: m.points.iter().map(|(n, q)| (n.clone(), reflect(*q, d))).collect(),
                    };
                }
                ctx.sk.base.insert(cp, m);
            }
        }
        for &kid in &kids {
            clone_tree(ctx, kid, cp);
        }
    }
    let sp = ctx.nodes[c].span;
    if was_wrapper.is_none() {
        ctx.nodes[c].inline.push(mk_decl("fill", ident("none", sp), sp));
        ctx.nodes[c].inline.push(mk_decl("stroke", ident("none", sp), sp));
        ctx.nodes[c].inline.push(mk_decl("stroke-width", num(0.0, sp), sp));
        ctx.nodes[c].inline.push(mk_decl("opacity", num(1.0, sp), sp));
    }
    let offs = images.iter().map(|(q, _)| (q.x - p.x, q.y - p.y)).collect();
    ctx.sk.base.remove(&c);
    ctx.sk.wrappers.insert(c, Wrapper { offsets: offs, mirror: true });
}

// The reflections a node's mirrored feature copy carries (innermost first).
fn reflected(ctx: &Ctx, i: usize) -> Vec<P> {
    let mut out = Vec::new();
    let mut cur = Some(i);
    while let Some(k) = cur {
        if let Some(ds) = ctx.sk.reflect.get(&k) {
            out.extend(ds.iter().cloned());
        }
        if ctx.nodes[k].prim == Prim::Sketch {
            break;
        }
        cur = ctx.nodes[k].parent;
    }
    out
}

fn reflect_all(p: P, ds: &[P]) -> P {
    ds.iter().fold(p, |q, d| reflect(q, *d))
}

// Deep-copy a subtree under `parent`.
fn clone_tree(ctx: &mut Ctx, src: usize, parent: usize) -> usize {
    let mut n = ctx.nodes[src].clone();
    n.children = vec![];
    n.id = None;
    let i = add_node(ctx, n, parent);
    ctx.comp[i] = ctx.comp[src].clone();
    if let Some(k) = ctx.sk.chrome.get(&src).cloned() {
        ctx.sk.chrome.insert(i, k);
    }
    if let Some(b) = ctx.sk.base.get(&src).cloned() {
        ctx.sk.base.insert(i, b);
    }
    if let Some(w) = ctx.sk.wrappers.get(&src).cloned() {
        ctx.sk.wrappers.insert(i, w);
    }
    if ctx.sk.copies.contains(&src) {
        ctx.sk.copies.insert(i);
    }
    if let Some(d) = ctx.sk.reflect.get(&src).cloned() {
        ctx.sk.reflect.insert(i, d);
    }
    for ch in ctx.nodes[src].children.clone() {
        clone_tree(ctx, ch, i);
    }
    i
}

fn pattern_offsets(ctx: &Ctx, i: usize) -> Result<Option<(Vec<(f64, f64)>, Option<f64>)>, Diag> {
    let v = match ctx.nodes[i].props.get("pattern") {
        Some(v) => v.clone(),
        None => return Ok(None),
    };
    let span = decl_span(ctx, i, "pattern");
    let bad = || Diag::error("resolve", "'pattern' takes grid(cols, rows, dx, dy) or radial(count, radius)", span);
    let t = match single_term(&v) {
        Some(t) => t.clone(),
        None => return Err(bad()),
    };
    let (name, args) = match &t {
        Term::Call(n, a, _) => (n.clone(), a.clone()),
        _ => return Err(bad()),
    };
    let env = &ctx.sheet.env;
    let mut xs = Vec::new();
    for a in &args {
        match env.eval(a, &HashMap::new()) {
            Ok(x) => match x.num() {
                Some(x) => xs.push(x),
                None => return Err(bad()),
            },
            Err(d) => return Err(Diag { span, ..d }),
        }
    }
    match (name.as_str(), xs.len()) {
        ("grid", 4) => {
            let cols = xs[0].trunc();
            let rows = xs[1].trunc();
            if cols < 1.0 || rows < 1.0 {
                return Err(Diag::error("resolve", "'grid' needs cols ≥ 1 and rows ≥ 1", span));
            }
            let mut out = Vec::new();
            for r in 0..rows as usize {
                for c in 0..cols as usize {
                    out.push((c as f64 * xs[2], r as f64 * xs[3]));
                }
            }
            Ok(Some((out, None)))
        }
        ("radial", 2) => {
            let n = xs[0].trunc();
            if n < 2.0 || !(xs[1] > 0.0) {
                return Err(Diag::error("resolve", "'radial' needs count ≥ 2 and radius > 0", span));
            }
            let r = xs[1];
            let mut out = Vec::new();
            for k in 0..n as usize {
                let a = (k as f64 * 360.0 / n).to_radians();
                out.push((r * a.sin(), -r * a.cos()));
            }
            Ok(Some((out, Some(r))))
        }
        _ => Err(bad()),
    }
}

// Run every pen, add drafting chrome, expand patterns. Returns whether the
// node tree grew (the cascade must then be recomputed).
pub fn expand(ctx: &mut Ctx) -> Result<bool, Diag> {
    let n0 = ctx.nodes.len();
    // units and density first
    check_frames(ctx)?;
    // the resolve phase, in document order: every draw value and pattern
    let mut cmds: HashMap<usize, Vec<sketch::Cmd>> = HashMap::new();
    for i in doc_order(ctx) {
        if ctx.nodes[i].prim == Prim::Sketch {
            if let Some(v) = ctx.nodes[i].props.get("draw").cloned() {
                let span = decl_span(ctx, i, "draw");
                cmds.insert(i, sketch::eval_draw(&ctx.sheet.env, &v, span)?);
            }
        }
        pattern_offsets(ctx, i)?;
    }
    // the layout phase, in document order
    let mut grew = false;
    for i in doc_order(ctx) {
        if let Some(v) = ctx.nodes[i].props.get("scale") {
            let xs = value_nums(&ctx.sheet.env, v);
            if xs.len() != 1 || !(xs[0] > 0.0) || single_term(v).is_none() {
                return Err(Diag::error("layout", "'scale' must be > 0", ctx.nodes[i].span));
            }
        }
        if frame_kind(ctx, i) == Some("drawing") && !has(ctx, i, "of") {
            let any = ctx.nodes[i].children.iter().any(|&c| ctx.comp[c].pin.is_none() && ctx.nodes[c].prim != Prim::Text && !is_plane(ctx, c));
            if !any {
                return Err(Diag::error("layout", "a drawing needs at least one geometry child", ctx.nodes[i].span));
            }
        }
        let drawing = in_drawing(ctx, i);
        if is_plane(ctx, i) {
            plane_facing(ctx, i)?;
        }
        if ctx.nodes[i].prim == Prim::Sketch {
            let c = match cmds.get(&i) {
                Some(c) => c,
                None => {
                    return Err(Diag::error("missing-required-property", "'|sketch|' requires 'draw'", ctx.nodes[i].span));
                }
            };
            let shape = sketch::run(c, ctx.nodes[i].span)?;
            ctx.sk.base.insert(i, shape);
            if has(ctx, i, "revolve") && has(ctx, i, "mirror") {
                return Err(Diag::error("layout", "a sketch takes 'revolve:' or 'mirror:', not both", ctx.nodes[i].span));
            }
            let rev = revolve_axis(ctx, i)?;
            let mirrors = mirror_steps(ctx, i)?;
            let brk = break_spec(ctx, i)?;
            if let Some((ax, a, b)) = brk {
                let mut shape = ctx.sk.base[&i].clone();
                if let Some(d) = rev {
                    shape = shape.mirror(d);
                } else {
                    for d in &mirrors {
                        shape = shape.mirror(*d);
                    }
                }
                for (v, upper) in [(a, false), (b, true)] {
                    if crossings(&shape, ax, v, upper).is_empty() {
                        return Err(Diag::error("layout", &format!("'break' at {} misses the profile", f4(v)), ctx.nodes[i].span));
                    }
                }
            }
            let thread = check_thread(ctx, i, rev)?;
            if !drawing {
                continue;
            }
            if let Some(d) = rev {
                add_chrome(ctx, i, &["centerline", "line"], Prim::Line, Chrome::Axis(d));
                add_chrome(ctx, i, &["shoulder", "line"], Prim::Line, Chrome::Edges);
                if thread.is_some() {
                    add_chrome(ctx, i, &["threadline", "line"], Prim::Line, Chrome::Thread);
                }
                if brk.is_some() {
                    add_chrome(ctx, i, &["breakline", "line"], Prim::Line, Chrome::Break(0));
                    add_chrome(ctx, i, &["breakline", "line"], Prim::Line, Chrome::Break(1));
                }
                grew = true;
            } else {
                let mut shape = ctx.sk.base[&i].clone();
                for d in mirrors {
                    if shape.has_open() {
                        add_chrome(ctx, i, &["centerline", "line"], Prim::Line, Chrome::Axis(d));
                        grew = true;
                    }
                    shape = shape.mirror(d);
                }
                if brk.is_some() {
                    add_chrome(ctx, i, &["breakline", "line"], Prim::Line, Chrome::Break(0));
                    add_chrome(ctx, i, &["breakline", "line"], Prim::Line, Chrome::Break(1));
                    grew = true;
                }
            }
        } else if is_hole(ctx, i) && drawing {
            if !has(ctx, i, "width") {
                let sp = ctx.nodes[i].span;
                return Err(Diag::error("missing-required-property", "'|hole|' requires 'width' — its diameter", sp));
            }
            let thread = if has(ctx, i, "thread") {
                match thread_spec(ctx, i) {
                    Some((None, p)) if p > 0.0 => Some(p),
                    _ => {
                        let sp = ctx.nodes[i].span;
                        return Err(Diag::error("layout", "'thread' takes a segment and its pitch — 'thread: m8 1.5'", sp));
                    }
                }
            } else {
                None
            };
            add_chrome(ctx, i, &["centerline", "line"], Prim::Line, Chrome::HoleX);
            add_chrome(ctx, i, &["centerline", "line"], Prim::Line, Chrome::HoleY);
            if let Some(p) = thread {
                add_chrome(ctx, i, &["threadline", "line"], Prim::Line, Chrome::ThreadArc(p));
            }
            grew = true;
        }
    }
    let _ = n0;
    // patterns: the node becomes a wrapper of its copies
    let mut i = 0;
    while i < ctx.nodes.len() {
        if ctx.sk.copies.contains(&i) || ctx.sk.chrome.contains_key(&i) || !has(ctx, i, "pattern") {
            i += 1;
            continue;
        }
        let (offs, ring) = match pattern_offsets(ctx, i)? {
            Some(x) => x,
            None => {
                i += 1;
                continue;
            }
        };
        let kids = std::mem::take(&mut ctx.nodes[i].children);
        if let (Some(r), true) = (ring, in_drawing(ctx, i)) {
            add_chrome(ctx, i, &["pitch-circle", "oval"], Prim::Oval, Chrome::Ring(r));
        }
        for _ in &offs {
            let mut n = ctx.nodes[i].clone();
            n.children = vec![];
            n.id = None;
            n.inline = id_decls(ctx, i).into_iter().chain(n.inline.into_iter()).collect();
            n.inline.retain(|d| d.name != "pattern" && d.name != "translate");
            n.props.remove("pattern");
            n.props.remove("translate");
            let c = add_node(ctx, n, i);
            ctx.comp[c] = ctx.comp[i].clone();
            ctx.comp[c].translate = (0.0, 0.0);
            if let Some(b) = ctx.sk.base.get(&i).cloned() {
                ctx.sk.base.insert(c, b);
            }
            ctx.sk.copies.insert(c);
            for &k in &kids {
                clone_tree(ctx, k, c);
            }
        }
        let sp = ctx.nodes[i].span;
        ctx.nodes[i].inline.push(mk_decl("fill", ident("none", sp), sp));
        ctx.nodes[i].inline.push(mk_decl("stroke", ident("none", sp), sp));
        ctx.nodes[i].inline.push(mk_decl("stroke-width", num(0.0, sp), sp));
        ctx.nodes[i].inline.push(mk_decl("opacity", num(1.0, sp), sp));
        ctx.sk.base.remove(&i);
        ctx.sk.wrappers.insert(i, Wrapper { offsets: offs, mirror: false });
        grew = true;
        i += 1;
    }
    // a mirrored sketch reflects its features: each off-axis child becomes a
    // wrapper of itself and its mirror image
    for i in 0..ctx.nodes.len() {
        if ctx.nodes[i].prim != Prim::Sketch || ctx.sk.wrappers.contains_key(&i) || !is_reachable(ctx, i) {
            continue;
        }
        if revolve_axis(ctx, i).ok().flatten().is_some() {
            continue;
        }
        let steps = mirror_steps(ctx, i).unwrap_or_default();
        if steps.is_empty() {
            continue;
        }
        for c in ctx.nodes[i].children.clone() {
            if ctx.sk.chrome.contains_key(&c) || ctx.nodes[c].prim == Prim::Text {
                continue;
            }
            if ctx.nodes[c].props.get("mirror").and_then(ident_of) == Some("none") {
                continue;
            }
            let t = ctx.nodes[c].props.get("translate").map(|v| value_nums(&ctx.sheet.env, v)).unwrap_or_default();
            let p = if t.len() == 2 { pt(t[0], t[1]) } else { pt(0.0, 0.0) };
            // every image: (position, reflections applied)
            let mut images: Vec<(P, Vec<P>)> = vec![(p, vec![])];
            for &d in &steps {
                let mut more = Vec::new();
                for (q, ds) in &images {
                    let r = reflect(*q, d);
                    if r.sub(*q).len() < 1e-9 {
                        continue;
                    }
                    let mut ds2 = ds.clone();
                    ds2.push(d);
                    more.push((r, ds2));
                }
                images.extend(more);
            }
            if images.len() > 1 {
                mirror_wrap(ctx, c, p, &images);
                grew = true;
            }
        }
    }
    Ok(grew)
}

fn is_reachable(ctx: &Ctx, i: usize) -> bool {
    let mut cur = i;
    loop {
        match ctx.nodes[cur].parent {
            Some(p) => {
                if !ctx.nodes[p].children.contains(&cur) {
                    return false;
                }
                cur = p;
            }
            None => return cur == 0,
        }
    }
}

// Reachable nodes in document (pre-) order.
fn doc_order(ctx: &Ctx) -> Vec<usize> {
    let mut out = Vec::new();
    let mut stack = vec![0usize];
    while let Some(i) = stack.pop() {
        out.push(i);
        for &c in ctx.nodes[i].children.iter().rev() {
            stack.push(c);
        }
    }
    out
}

// density / unit values.
fn check_frames(ctx: &Ctx) -> Result<(), Diag> {
    let env = &ctx.sheet.env;
    if let Some(v) = ctx.nodes[0].props.get("density") {
        let ok = crate::style::value_num(env, v).map(|x| x > 0.0).unwrap_or(false);
        if !ok {
            return Err(Diag::error("resolve", "'density' must be > 0", decl_span(ctx, 0, "density")));
        }
    }
    for i in doc_order(ctx) {
        if frame_kind(ctx, i).is_some() {
            if let Some(v) = ctx.nodes[i].props.get("unit") {
                if ident_of(v).and_then(unit_mm).is_none() {
                    return Err(Diag::error("resolve", "'unit' is px, mm, cm, m, or in", decl_span(ctx, i, "unit")));
                }
            }
        }
    }
    Ok(())
}

// Scale length properties by each node's px scale (after the final cascade).
pub fn prepare(ctx: &mut Ctx) {
    let n = ctx.nodes.len();
    let ps: Vec<f64> = (0..n).map(|i| ps_self(ctx, i)).collect();
    for i in 0..n {
        let own = ps[i];
        let mut par = ctx.nodes[i].parent.map(|p| ps[p]).unwrap_or(own);
        // a frame's pinned title sits in px, outside its geometry
        if let Some(p) = ctx.nodes[i].parent {
            if ctx.comp[i].pin.is_some() && frame_kind(ctx, p).is_some() {
                par = 1.0;
            }
        }
        let c = &mut ctx.comp[i];
        if own != 1.0 {
            c.width = c.width.map(|w| w * own);
            c.height = c.height.map(|h| h * own);
            c.max_width = c.max_width.map(|w| w * own);
        }
        if par != 1.0 {
            c.translate = (c.translate.0 * par, c.translate.1 * par);
        }
    }
    ctx.sk.ps = ps;
}

// Frames past 10000 px are almost always a missing ratio.
pub fn size_warnings(ctx: &mut Ctx) {
    let mut out = Vec::new();
    let mut stack = vec![0usize];
    while let Some(i) = stack.pop() {
        if frame_kind(ctx, i).is_some() {
            let n = &ctx.nodes[i];
            let (w, h) = (n.w, n.h);
            if w > 10000.0 || h > 10000.0 {
                let (v, dim) = if h > w { (h, "tall") } else { (w, "wide") };
                let msg = format!(
                    "the drawing renders {} px {} — 'scale:' is a ratio; a 5 m beam at 1:50 is 'scale: 0.02'",
                    v.round(),
                    dim
                );
                out.push(Diag::warning("layout", &msg, n.span));
            }
        }
        for &c in ctx.nodes[i].children.iter().rev() {
            stack.push(c);
        }
    }
    ctx.warnings.extend(out);
}

// ------------------------------------------------------------ measure

pub fn claims(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].prim == Prim::Sketch
        || ctx.sk.wrappers.contains_key(&i)
        || ctx.sk.chrome.contains_key(&i)
        || frame_kind(ctx, i).is_some()
        || (matches!(ctx.nodes[i].prim, Prim::Line | Prim::Poly) && ps(ctx, i) != 1.0)
}

pub fn measure(ctx: &mut Ctx, i: usize, _avail: Option<f64>) {
    if ctx.sk.chrome.contains_key(&i) {
        return;
    }
    match frame_kind(ctx, i) {
        Some("drawing") => return measure_frame(ctx, i, true),
        Some(_) => return measure_frame(ctx, i, false),
        None => {}
    }
    if ctx.sk.wrappers.contains_key(&i) {
        return measure_wrapper(ctx, i, false);
    }
    match ctx.nodes[i].prim {
        Prim::Sketch => measure_sketch(ctx, i, false),
        Prim::Line | Prim::Poly => measure_geo_scaled(ctx, i),
        _ => {}
    }
}

fn split_pinned(ctx: &Ctx, i: usize) -> (Vec<usize>, Vec<usize>) {
    let mut flow = Vec::new();
    let mut pinned = Vec::new();
    for &c in &ctx.nodes[i].children {
        if ctx.comp[c].pin.is_some() {
            pinned.push(c);
        } else {
            flow.push(c);
        }
    }
    (flow, pinned)
}

// Put a measured node's origin at (ox, oy) in its parent's frame.
fn place(ctx: &mut Ctx, i: usize, ox: f64, oy: f64) {
    let n = &mut ctx.nodes[i];
    n.x = ox - n.geo_off.0;
    n.y = oy - n.geo_off.1;
}

// A drawing or stack: every child on the one datum; the frame wraps them.
fn measure_frame(ctx: &mut Ctx, i: usize, drawing: bool) {
    let (flow, pinned) = split_pinned(ctx, i);
    let planes: Vec<usize> = if drawing { flow.iter().copied().filter(|&c| is_plane(ctx, c)).collect() } else { vec![] };
    for &ch in &flow {
        if planes.contains(&ch) {
            continue;
        }
        if drawing {
            measure_part(ctx, ch);
        } else {
            crate::layout::measure(ctx, ch, None);
        }
        place(ctx, ch, 0.0, 0.0);
    }
    let mut bb = BBox::empty();
    let ident = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
    for &ch in &flow {
        if !planes.contains(&ch) {
            deep_bbox(ctx, ch, &ident, &mut bb);
        }
    }
    // section planes cut across everything else
    if !planes.is_empty() {
        let (lo, hi) = if bb.is_empty() { (0.0, 0.0) } else { (bb.y0, bb.y1) };
        for &p in &planes {
            lay_plane(ctx, p, lo, hi);
            deep_bbox(ctx, p, &ident, &mut bb);
        }
    }
    if bb.is_empty() {
        bb.add(0.0, 0.0);
    }
    let c = ctx.comp[i].clone();
    let pad = c.padding;
    let mut w = bb.w() + pad[1] + pad[3];
    let mut h = bb.h() + pad[0] + pad[2];
    if let Some(fw) = c.width {
        w = w.max(fw);
    }
    if let Some(fh) = c.height {
        h = h.max(fh);
    }
    if i != 0 {
        let dx = -bb.cx() + (pad[3] - pad[1]) / 2.0;
        let dy = -bb.cy() + (pad[0] - pad[2]) / 2.0;
        for &ch in &flow {
            ctx.nodes[ch].x += dx;
            ctx.nodes[ch].y += dy;
        }
    }
    ctx.nodes[i].w = w;
    ctx.nodes[i].h = h;
    for &p in &pinned {
        crate::layout::measure(ctx, p, None);
        crate::layout::place_pinned(ctx, i, p);
    }
}

// The content box of a node and its descendants, in the frame of `m`.
fn deep_bbox(ctx: &Ctx, i: usize, m: &[f64; 6], bb: &mut BBox) {
    let n = &ctx.nodes[i];
    // the rendered group's frame: translate(position + geo offset) rotate(r)
    let mi = mul(m, &crate::render::group_matrix(ctx, i));
    let skip = match ctx.sk.chrome.get(&i) {
        Some(Chrome::Ring(_)) => false,
        Some(_) => ctx.sk.geoms.get(&i).map(|g| g.is_empty()).unwrap_or(true),
        None => skip_box(ctx, i),
    };
    if !skip {
        let (ow, oh) = crate::layout::outer(ctx, i);
        let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
        for (px, py) in [(-ow / 2.0, -oh / 2.0), (ow / 2.0, -oh / 2.0), (ow / 2.0, oh / 2.0), (-ow / 2.0, oh / 2.0)] {
            let (px, py) = (px + cx, py + cy);
            bb.add(mi[0] * px + mi[2] * py + mi[4], mi[1] * px + mi[3] * py + mi[5]);
        }
    }
    if n.prim == Prim::Text {
        return;
    }
    for &ch in &n.children {
        deep_bbox(ctx, ch, &mi, bb);
    }
}

fn mul(m: &[f64; 6], n: &[f64; 6]) -> [f64; 6] {
    [
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    ]
}

// A part inside a drawing: sized by its own width / height (or padding),
// its children on its origin.
fn measure_part(ctx: &mut Ctx, i: usize) {
    let prim = ctx.nodes[i].prim;
    if prim == Prim::Text {
        crate::layout::measure_text(ctx, i, None);
        return;
    }
    if ctx.sk.chrome.contains_key(&i) {
        return;
    }
    match frame_kind(ctx, i) {
        Some("drawing") => return measure_frame(ctx, i, true),
        Some(_) => return measure_frame(ctx, i, false),
        None => {}
    }
    if ctx.sk.wrappers.contains_key(&i) {
        return measure_wrapper(ctx, i, true);
    }
    // layout containers keep their own layout inside a drawing
    if is_layout_container(ctx, i) {
        return crate::layout::measure(ctx, i, None);
    }
    match prim {
        Prim::Sketch => measure_sketch(ctx, i, true),
        Prim::Line | Prim::Poly | Prim::Path => measure_geo_scaled(ctx, i),
        _ => {
            let c = ctx.comp[i].clone();
            let w = c.width.unwrap_or(c.padding[1] + c.padding[3]);
            let mut h = c.height.unwrap_or(c.padding[0] + c.padding[2]);
            let magnifier = ctx.nodes[i].is("magnifier");
            if is_hole(ctx, i) || magnifier {
                h = w;
            }
            ctx.nodes[i].w = w;
            ctx.nodes[i].h = h;
            hole_chrome(ctx, i);
            for ch in ctx.nodes[i].children.clone() {
                if ctx.sk.chrome.contains_key(&ch) {
                    continue;
                }
                if ctx.comp[ch].pin.is_some() {
                    crate::layout::measure(ctx, ch, None);
                } else {
                    measure_part(ctx, ch);
                }
                place(ctx, ch, 0.0, 0.0);
                // a detail circle's letter sits off its rim, up and right
                if magnifier && ctx.nodes[ch].prim == Prim::Text {
                    let d = (w / 2.0 + ctx.comp[i].stroke_width / 2.0 + 20.0) * std::f64::consts::FRAC_1_SQRT_2;
                    ctx.nodes[ch].x += d;
                    ctx.nodes[ch].y -= d;
                }
            }
        }
    }
}

// line / poly / path inside a drawing: points in px, drawn in the frame.
fn measure_geo_scaled(ctx: &mut Ctx, i: usize) {
    crate::layout::measure_geo(ctx, i);
    let k = ps(ctx, i);
    if k != 1.0 {
        if let Some(crate::scene::Geo::Points(pts)) = &ctx.nodes[i].geo {
            let pts: Vec<(f64, f64)> = pts.iter().map(|(x, y)| (x * k, y * k)).collect();
            let mut bb = BBox::empty();
            for &(x, y) in &pts {
                bb.add(x, y);
            }
            let n = &mut ctx.nodes[i];
            n.w = bb.w();
            n.h = bb.h();
            n.geo_off = (-bb.cx(), -bb.cy());
            n.geo = Some(crate::scene::Geo::Points(pts));
        }
    }
    for ch in ctx.nodes[i].children.clone() {
        measure_part(ctx, ch);
        place(ctx, ch, 0.0, 0.0);
    }
}

fn measure_wrapper(ctx: &mut Ctx, i: usize, drawing: bool) {
    let k = ps(ctx, i);
    let offs = ctx.sk.wrappers[&i].offsets.clone();
    let kids = ctx.nodes[i].children.clone();
    let mut copies = Vec::new();
    for &ch in &kids {
        if let Some(Chrome::Ring(r)) = ctx.sk.chrome.get(&ch).cloned() {
            let d = 2.0 * r * k;
            ctx.nodes[ch].w = d;
            ctx.nodes[ch].h = d;
            ctx.nodes[ch].x = 0.0;
            ctx.nodes[ch].y = 0.0;
            ctx.sk.geoms.insert(ch, vec![]);
        } else {
            copies.push(ch);
        }
    }
    let mut bb = BBox::empty();
    for (n, &ch) in copies.iter().enumerate() {
        if drawing {
            measure_part(ctx, ch);
        } else {
            crate::layout::measure(ctx, ch, None);
        }
        let (ox, oy) = offs.get(n).copied().unwrap_or((0.0, 0.0));
        let rf = reflected(ctx, i);
        let o = reflect_all(pt(ox, oy), &rf);
        place(ctx, ch, o.x * k, o.y * k);
        let (ow, oh) = crate::layout::outer(ctx, ch);
        let (cx, cy) = (ctx.nodes[ch].x, ctx.nodes[ch].y);
        bb.add(cx - ow / 2.0, cy - oh / 2.0);
        bb.add(cx + ow / 2.0, cy + oh / 2.0);
    }
    if bb.is_empty() {
        bb.add(0.0, 0.0);
    }
    let mirror = ctx.sk.wrappers[&i].mirror;
    let n = &mut ctx.nodes[i];
    n.w = bb.w();
    n.h = bb.h();
    n.geo_off = if mirror { (0.0, 0.0) } else { (-bb.cx(), -bb.cy()) };
}

// A wrapper's own box never counts toward bounds — its copies do.
pub fn skip_box(ctx: &Ctx, i: usize) -> bool {
    ctx.sk.wrappers.contains_key(&i)
}

fn hole_chrome(ctx: &mut Ctx, i: usize) {
    let r = ctx.nodes[i].w / 2.0;
    let k = ps(ctx, i);
    for ch in ctx.nodes[i].children.clone() {
        let kind = match ctx.sk.chrome.get(&ch) {
            Some(c) => c.clone(),
            None => continue,
        };
        let e = r + AXIS_OVERHANG;
        let rf = reflected(ctx, i);
        let m = |p: P| reflect_all(p, &rf);
        let g = match kind {
            Chrome::HoleX => vec![Geom::Line(m(pt(-e, 0.0)), m(pt(e, 0.0)))],
            Chrome::HoleY => vec![Geom::Line(m(pt(0.0, e)), m(pt(0.0, -e)))],
            Chrome::ThreadArc(p) => {
                let rr = r + THREAD_INTERNAL * p * k;
                let d = format!("M {} 0 A {} {} 0 1 1 0 {}", fmt3(rr), fmt3(rr), fmt3(rr), fmt3(-rr));
                vec![Geom::Path(d)]
            }
            _ => continue,
        };
        set_chrome(ctx, ch, g, pt(0.0, 0.0));
    }
}

// Record a chrome node's geometry and its box (in its owner's frame).
fn set_chrome(ctx: &mut Ctx, ch: usize, g: Vec<Geom>, home: P) {
    let g = if ctx.comp[ch].has_stroke { g } else { vec![] };
    let mut bb = BBox::empty();
    for it in &g {
        match it {
            Geom::Line(a, b) => {
                bb.add(a.x, a.y);
                bb.add(b.x, b.y);
            }
            Geom::Poly(ps) => {
                for p in ps {
                    bb.add(p.x, p.y);
                }
            }
            Geom::Path(d) => {
                let b = crate::geom::path_bbox(d);
                if !b.is_empty() {
                    bb.add(b.x0, b.y0);
                    bb.add(b.x1, b.y1);
                }
            }
        }
    }
    let n = &mut ctx.nodes[ch];
    if bb.is_empty() {
        n.w = 0.0;
        n.h = 0.0;
        n.geo_off = (-home.x, -home.y);
        n.x = home.x;
        n.y = home.y;
    } else {
        n.w = bb.w();
        n.h = bb.h();
        n.geo_off = (-bb.cx(), -bb.cy());
        n.x = bb.cx();
        n.y = bb.cy();
    }
    ctx.sk.geoms.insert(ch, g);
}

// ------------------------------------------------------------ sketches

fn measure_sketch(ctx: &mut Ctx, i: usize, drawing: bool) {
    let laid = lay_sketch(ctx, i);
    let bb = laid.bbox.unwrap_or_else(|| {
        let mut b = BBox::empty();
        b.add(0.0, 0.0);
        b
    });
    {
        let n = &mut ctx.nodes[i];
        n.w = bb.w();
        n.h = bb.h();
        n.geo_off = (-bb.cx(), -bb.cy());
    }
    let home = pt(bb.cx(), bb.cy());
    // chrome geometry
    for ch in ctx.nodes[i].children.clone() {
        let kind = match ctx.sk.chrome.get(&ch) {
            Some(c) => c.clone(),
            None => continue,
        };
        let g = match kind {
            Chrome::Axis(d) => {
                let mut lo = f64::INFINITY;
                let mut hi = f64::NEG_INFINITY;
                for (x, y) in [(bb.x0, bb.y0), (bb.x1, bb.y0), (bb.x1, bb.y1), (bb.x0, bb.y1)] {
                    let t = x * d.x + y * d.y;
                    lo = lo.min(t);
                    hi = hi.max(t);
                }
                // past the stroked outline; an unstroked one still counts its width
                let c = &ctx.comp[i];
                let over = if c.has_stroke { AXIS_OVERHANG } else { AXIS_OVERHANG - c.stroke_width / 2.0 };
                let a = d.mul(lo - over);
                let b = d.mul(hi + over);
                vec![Geom::Line(clean(a), clean(b))]
            }
            Chrome::Edges => laid
                .edges
                .iter()
                .map(|&(x, r)| if laid.along_x { Geom::Line(pt(x, -r), pt(x, r)) } else { Geom::Line(pt(-r, x), pt(r, x)) })
                .collect(),
            Chrome::Thread => laid.thread.iter().map(|&(a, b)| Geom::Line(a, b)).collect(),
            Chrome::Break(k) => laid.breaks.get(k).map(|p| vec![Geom::Poly(p.clone())]).unwrap_or_default(),
            _ => vec![],
        };
        set_chrome(ctx, ch, g, home);
    }
    let brk = laid.brk;
    ctx.sk.laid.insert(i, laid);
    let kids: Vec<usize> = ctx.nodes[i].children.iter().copied().filter(|c| !ctx.sk.chrome.contains_key(c)).collect();
    if drawing {
        // parts: every feature on the pen origin
        for &ch in &kids {
            measure_part(ctx, ch);
            place(ctx, ch, 0.0, 0.0);
        }
    } else {
        flow_on_origin(ctx, i, &kids);
    }
    // a feature beyond the break rides it with the far piece; one inside the
    // cut folds into the gap
    if let Some(b) = brk {
        break_map(ctx, i, 0.0, 0.0, b);
    }
}

// Outside a drawing a sketch lays its features out as a flow (no gap unless
// set) centred on its pen origin.
fn flow_on_origin(ctx: &mut Ctx, i: usize, kids: &[usize]) {
    let c = ctx.comp[i].clone();
    let gap = if has(ctx, i, "gap") { c.gap } else { (0.0, 0.0) };
    let row = c.direction == crate::compile::Dir::Row;
    let mut flow = Vec::new();
    for &k in kids {
        crate::layout::measure(ctx, k, None);
        if ctx.comp[k].pin.is_some() {
            crate::layout::place_pinned(ctx, i, k);
        } else {
            flow.push(k);
        }
    }
    // a mirrored feature takes its own (first image's) room in the flow
    let first = |ctx: &Ctx, k: usize| -> Option<usize> {
        match ctx.sk.wrappers.get(&k) {
            Some(w) if w.mirror => ctx.nodes[k].children.iter().copied().find(|c| !ctx.sk.chrome.contains_key(c)),
            _ => None,
        }
    };
    let sizes: Vec<(f64, f64)> =
        flow.iter().map(|&k| crate::layout::outer(ctx, first(ctx, k).unwrap_or(k))).collect();
    let g = if row { gap.1 } else { gap.0 };
    let main: f64 = sizes.iter().map(|s| if row { s.0 } else { s.1 }).sum::<f64>() + g * (flow.len().max(1) - 1) as f64;
    let mut cur = -main / 2.0;
    for (n, &k) in flow.iter().enumerate() {
        let (w, h) = sizes[n];
        let (sx, sy) = if row { (cur + w / 2.0, 0.0) } else { (0.0, cur + h / 2.0) };
        cur += if row { w + g } else { h + g };
        match first(ctx, k) {
            Some(c0) => {
                // reflect the feature where the flow put it
                let t = ctx.comp[k].translate;
                let p = pt(sx + ctx.nodes[c0].geo_off.0 + t.0, sy + ctx.nodes[c0].geo_off.1 + t.1);
                for c in ctx.nodes[k].children.clone() {
                    if ctx.sk.chrome.contains_key(&c) {
                        continue;
                    }
                    let ds = ctx.sk.reflect.get(&c).cloned().unwrap_or_default();
                    let q = reflect_all(p, &ds);
                    place(ctx, c, q.x - p.x, q.y - p.y);
                }
                ctx.nodes[k].geo_off = (0.0, 0.0);
                ctx.nodes[k].x = p.x - t.0;
                ctx.nodes[k].y = p.y - t.1;
                rebox_wrapper(ctx, k);
            }
            None => {
                ctx.nodes[k].x = sx;
                ctx.nodes[k].y = sy;
            }
        }
    }
}

fn break_station(v: f64, brk: (bool, f64, f64, f64)) -> f64 {
    let (_, a, b, shift) = brk;
    if v >= b {
        v - shift
    } else if v > a {
        a + (v - a) * BREAK_GAP / (b - a)
    } else {
        v
    }
}

// Move every feature origin below `i` through the break (abs: i's origin
// before, now: after, along the break axis).
fn break_map(ctx: &mut Ctx, i: usize, abs: f64, now: f64, brk: (bool, f64, f64, f64)) {
    let along_x = brk.0;
    for ch in ctx.nodes[i].children.clone() {
        if ctx.sk.chrome.contains_key(&ch) && abs == 0.0 && now == 0.0 && ctx.nodes[ch].parent == Some(i) && ctx.nodes[i].prim == Prim::Sketch {
            continue;
        }
        let n = &ctx.nodes[ch];
        let c = &ctx.comp[ch];
        let t = if along_x { n.x + c.translate.0 + n.geo_off.0 } else { n.y + c.translate.1 + n.geo_off.1 };
        let a2 = abs + t;
        let n2 = break_station(a2, brk);
        let d = (n2 - now) - t;
        if along_x {
            ctx.nodes[ch].x += d;
        } else {
            ctx.nodes[ch].y += d;
        }
        break_map(ctx, ch, a2, n2, brk);
    }
    if ctx.sk.wrappers.contains_key(&i) {
        rebox_wrapper(ctx, i);
    }
}

// Re-fit a pattern wrapper's box to its copies, keeping its origin.
fn rebox_wrapper(ctx: &mut Ctx, i: usize) {
    let mut bb = BBox::empty();
    for ch in ctx.nodes[i].children.clone() {
        if ctx.sk.chrome.contains_key(&ch) {
            continue;
        }
        let (ow, oh) = crate::layout::outer(ctx, ch);
        let (cx, cy) = (ctx.nodes[ch].x, ctx.nodes[ch].y);
        bb.add(cx - ow / 2.0, cy - oh / 2.0);
        bb.add(cx + ow / 2.0, cy + oh / 2.0);
    }
    if bb.is_empty() {
        return;
    }
    let mirror = ctx.sk.wrappers[&i].mirror;
    let n = &mut ctx.nodes[i];
    let (ox, oy) = (n.x + n.geo_off.0, n.y + n.geo_off.1);
    n.w = bb.w();
    n.h = bb.h();
    n.geo_off = if mirror { (0.0, 0.0) } else { (-bb.cx(), -bb.cy()) };
    n.x = ox - n.geo_off.0;
    n.y = oy - n.geo_off.1;
}

fn clean(p: P) -> P {
    pt(if p.x == 0.0 { 0.0 } else { p.x }, if p.y == 0.0 { 0.0 } else { p.y })
}

// The sketch's final geometry in px: scale, mirror / revolve, break.
fn lay_sketch(ctx: &Ctx, i: usize) -> Laid {
    let k = ps(ctx, i);
    let base = match ctx.sk.base.get(&i) {
        Some(b) => b.scaled(k),
        None => return Laid::default(),
    };
    let rev = revolve_axis(ctx, i).ok().flatten();
    let mut shape = base.clone();
    if let Some(d) = rev {
        shape = shape.mirror(d);
    } else {
        for d in mirror_steps(ctx, i).unwrap_or_default() {
            shape = shape.mirror(d);
        }
    }
    if ctx.nodes[i].is("wall") {
        shape = shape.thickened(wall_thickness(ctx, i) * k);
    }
    let mut laid = Laid::default();
    let brk = break_spec(ctx, i).ok().flatten().map(|(ax, a, b)| (ax, a * k, b * k));
    let mut shift = 0.0;
    if let Some((ax, a, b)) = brk {
        shift = (b - a) - BREAK_GAP;
        laid.breaks = vec![break_line(&shape, ax, a, a, false), break_line(&shape, ax, b, a + BREAK_GAP, true)];
        shape = break_shape(&shape, ax, a, b, shift);
        laid.brk = Some((ax, a, b, shift));
    }
    if let Some(d) = rev {
        let along_x = d.x != 0.0;
        laid.along_x = along_x;
        laid.edges = edges(&shape, along_x);
        if let Some((seg, p)) = thread_spec(ctx, i) {
            thread_lines(&mut laid, &base, &shape, seg.as_deref(), p * k, along_x, brk.map(|(_, a, b)| (a, b, shift)));
        }
    }
    laid.path = shape.path_data();
    let bb = sampled_bbox(&laid.path);
    laid.bbox = if bb.is_empty() { None } else { Some(bb) };
    laid.shape = shape;
    laid
}

// A wall's thickness in units: its own, else the floor plan's (walls), else
// 200 mm (walls) / 100 mm (partitions).
fn wall_thickness(ctx: &Ctx, i: usize) -> f64 {
    let env = &ctx.sheet.env;
    if let Some(t) = ctx.nodes[i].props.get("thickness").and_then(|v| crate::style::value_num(env, v)) {
        return t;
    }
    let partition = ctx.nodes[i].is("partition");
    if !partition {
        let mut cur = ctx.nodes[i].parent;
        while let Some(p) = cur {
            if frame_kind(ctx, p).is_some() {
                if let Some(t) = ctx.nodes[p].props.get("thickness").and_then(|v| crate::style::value_num(env, v)) {
                    return t;
                }
                break;
            }
            cur = ctx.nodes[p].parent;
        }
    }
    let mm = if partition { 100.0 } else { 200.0 };
    // the frame's unit, in mm
    let unit = enclosing_frame(ctx, i).map(|f| frame_ppu(ctx, f) / density(ctx)).unwrap_or(1.0);
    if unit > 0.0 {
        mm / unit
    } else {
        mm
    }
}

fn sampled_bbox(d: &str) -> BBox {
    crate::geom::path_bbox(d)
}

// Runs perpendicular to the axis: (station, low, high) of the other coordinate.
fn cross_runs(shape: &Shape, along_x: bool) -> Vec<(f64, f64, f64)> {
    let ax = |p: P| if along_x { p.x } else { p.y };
    let other = |p: P| if along_x { p.y } else { p.x };
    let mut out = Vec::new();
    for s in &shape.subs {
        let mut segs = s.segs.clone();
        if s.closed && !s.end().near(s.start) {
            segs.push(Seg::Line { a: s.end(), b: s.start });
        }
        for g in &segs {
            if let Seg::Line { a, b } = g {
                if (ax(*a) - ax(*b)).abs() < 1e-9 {
                    out.push((ax(*a), other(*a).min(other(*b)), other(*a).max(other(*b))));
                }
            }
        }
    }
    out
}

// Does the drawn outline already run the full diameter [-r, r] at station x?
fn diameter_drawn(runs: &[(f64, f64, f64)], x: f64, r: f64) -> bool {
    let mut iv: Vec<(f64, f64)> = runs.iter().filter(|q| (q.0 - x).abs() < 1e-9).map(|q| (q.1, q.2)).collect();
    iv.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut reach = -r;
    for (lo, hi) in iv {
        if lo > reach + 1e-9 {
            break;
        }
        reach = reach.max(hi);
    }
    reach >= r - 1e-9
}

// Edge lines of a turned part: every sharp corner of the drawn outline (after
// the revolve and any break) draws its diameter — unless the outline already
// runs that full diameter there (an end face).
fn edges(shape: &Shape, along_x: bool) -> Vec<(f64, f64)> {
    let ax = |p: P| if along_x { p.x } else { p.y };
    let rad = |p: P| if along_x { p.y.abs() } else { p.x.abs() };
    let runs = cross_runs(shape, along_x);
    let mut out: Vec<(f64, f64)> = Vec::new();
    for s in &shape.subs {
        if s.circle {
            continue;
        }
        let mut segs: Vec<Seg> = s.segs.clone();
        if s.closed && !s.end().near(s.start) {
            segs.push(Seg::Line { a: s.end(), b: s.start });
        }
        // a run a corner modifier used up has no direction of its own
        segs.retain(|g| g.dir_start().is_some() && g.length() > 1e-9);
        let n = segs.len();
        let joints = if s.closed { n } else { n.saturating_sub(1) };
        for k in 0..joints {
            let g1 = &segs[k];
            let g2 = &segs[(k + 1) % n];
            let (d1, d2) = match (g1.dir_end(), g2.dir_start()) {
                (Some(a), Some(b)) => (a, b),
                _ => continue,
            };
            let ang = d1.cross(d2).atan2(d1.dot(d2));
            if ang.abs() < 1e-6 {
                continue;
            }
            let v = g1.end();
            let r = rad(v);
            if r < 1e-9 {
                continue;
            }
            let x = ax(v);
            if diameter_drawn(&runs, x, r) {
                continue;
            }
            add_edge(&mut out, x, r, None);
        }
    }
    // edge lines draw in station order
    out.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    out
}

// Record an edge line at station x (radius r), across a break (a, b, shift):
// none inside the cut, the far piece's shifted.
fn add_edge(out: &mut Vec<(f64, f64)>, x: f64, r: f64, brk: Option<(f64, f64, f64)>) {
    let x = match brk {
        Some((a, b, s)) => {
            if x > a + 1e-9 && x < b - 1e-9 {
                return;
            }
            if x >= b - 1e-9 {
                x - s
            } else {
                x
            }
        }
        None => x,
    };
    if let Some(e) = out.iter_mut().find(|e| (e.0 - x).abs() < 1e-9) {
        e.1 = e.1.max(r);
    } else {
        out.push((x, r));
    }
}

fn thread_lines(laid: &mut Laid, base: &Shape, drawn: &Shape, seg: Option<&str>, pitch_px: f64, along_x: bool, brk: Option<(f64, f64, f64)>) {
    // the tagged run and its neighbours in the profile
    let mut found: Option<(Seg, Option<Seg>, Option<Seg>, bool)> = None;
    for s in &base.subs {
        for (k, t) in s.tags.iter().enumerate() {
            if t.as_deref() == seg && seg.is_some() {
                let prev = if k > 0 { Some(s.segs[k - 1].clone()) } else { None };
                let next = s.segs.get(k + 1).cloned();
                found = Some((s.segs[k].clone(), prev, next, s.closed));
                break;
            }
        }
        if found.is_some() {
            break;
        }
    }
    let (g, prev, next, _) = match found {
        Some(f) => f,
        None => return,
    };
    let (a, b) = (g.start(), g.end());
    let ax = |p: P| if along_x { p.x } else { p.y };
    let rad = |p: P| if along_x { p.y.abs() } else { p.x.abs() };
    let r = rad(a);
    // internal when the material lies beyond the surface (an inner subpath)
    let internal = is_internal(base, &g, along_x);
    let rr = if internal { r + THREAD_INTERNAL * pitch_px } else { r - THREAD_EXTERNAL * pitch_px };
    // ends on the drawn pieces: one inside the cut clips to the cut's edge
    // facing the other end
    let sh = |v: f64, other: f64| match brk {
        Some((ca, cb, s)) => {
            if other > v && v >= ca - 1e-9 && v < cb - 1e-9 {
                cb - s
            } else if other < v && v > ca + 1e-9 && v <= cb + 1e-9 {
                ca
            } else if v >= cb - 1e-9 {
                v - s
            } else {
                v
            }
        }
        None => v,
    };
    let inside = |v: f64| match brk {
        Some((ca, cb, _)) => v > ca + 1e-9 && v < cb - 1e-9,
        None => false,
    };
    let (x1, x2) = if inside(ax(a)) && inside(ax(b)) {
        let (ca, cb, s) = brk.unwrap();
        let fold = |v: f64| break_station(v, (along_x, ca, cb, s));
        (fold(ax(a)), fold(ax(b)))
    } else {
        (sh(ax(a), ax(b)), sh(ax(b), ax(a)))
    };
    let mk = |x: f64, y: f64| if along_x { pt(x, y) } else { pt(y, x) };
    laid.thread = vec![(mk(x1, -rr), mk(x2, -rr)), (mk(x1, rr), mk(x2, rr))];
    if internal {
        return;
    }
    // thread-end lines where the run carries on at the same diameter
    let d = g.dir_start();
    let straight = |o: &Option<Seg>, at_start: bool| -> bool {
        match (o, d) {
            (Some(n @ Seg::Line { .. }), Some(d)) => {
                let e = if at_start { n.dir_end() } else { n.dir_start() };
                match e {
                    Some(e) => e.cross(d).abs() < 1e-9 && e.dot(d) > 0.0,
                    None => false,
                }
            }
            _ => false,
        }
    };
    let runs = cross_runs(drawn, along_x);
    let mut ends = Vec::new();
    if straight(&prev, true) {
        ends.push(ax(a));
    }
    if straight(&next, false) {
        ends.push(ax(b));
    }
    for x in ends {
        let before = laid.edges.len();
        add_edge(&mut laid.edges, x, r, brk);
        // an end the outline already runs across draws no line of its own
        if laid.edges.len() > before {
            let (lx, lr) = *laid.edges.last().unwrap();
            if diameter_drawn(&runs, lx, lr) {
                laid.edges.pop();
            }
        }
    }
}

// Is a tagged run on an inner (bore) surface: does the material sit on its
// far side from the axis?
fn is_internal(base: &Shape, g: &Seg, along_x: bool) -> bool {
    let sub = match base.subs.iter().find(|s| s.segs.iter().any(|q| q.start().near(g.start()) && q.end().near(g.end()))) {
        Some(s) => s,
        None => return false,
    };
    if !sub.closed {
        return false;
    }
    let m = pt((g.start().x + g.end().x) / 2.0, (g.start().y + g.end().y) / 2.0);
    let probe = if along_x {
        pt(m.x, m.y - m.y.signum() * 1e-3)
    } else {
        pt(m.x - m.x.signum() * 1e-3, m.y)
    };
    !inside(sub, probe)
}

fn inside(s: &Sub, p: P) -> bool {
    let mut pts = vec![s.start];
    for g in &s.segs {
        match g {
            Seg::Arc { a, c, sweep, .. } => {
                for k in 1..=16 {
                    let t = *sweep * k as f64 / 16.0;
                    let v = a.sub(*c);
                    let (sn, cs) = t.sin_cos();
                    pts.push(pt(c.x + v.x * cs - v.y * sn, c.y + v.x * sn + v.y * cs));
                }
            }
            _ => pts.push(g.end()),
        }
    }
    let mut odd = false;
    let n = pts.len();
    for k in 0..n {
        let a = pts[k];
        let b = pts[(k + 1) % n];
        if (a.y > p.y) != (b.y > p.y) {
            let x = a.x + (p.y - a.y) / (b.y - a.y) * (b.x - a.x);
            if x > p.x {
                odd = !odd;
            }
        }
    }
    odd
}

// Every crossing of the shape with the line {axis = v}: the other coordinate.
// Every crossing of the shape with the line {axis = v}: the other
// coordinate. A run counts on [low end, high end) — a run lying on the line
// counts nowhere, a corner on it once.
fn crossings(shape: &Shape, along_x: bool, v: f64, upper: bool) -> Vec<f64> {
    // a cut's near side counts runs leaving it into the cut, its far side
    // the runs arriving from it
    let hit = |lo: f64, hi: f64| lo < hi && if upper { lo < v && v <= hi } else { lo <= v && v < hi };
    let ax = |p: P| if along_x { p.x } else { p.y };
    let other = |p: P| if along_x { p.y } else { p.x };
    let mut out = Vec::new();
    for s in &shape.subs {
        let mut segs = s.segs.clone();
        if s.closed && !s.end().near(s.start) {
            segs.push(Seg::Line { a: s.end(), b: s.start });
        }
        for g in &segs {
            match g {
                Seg::Line { a, b } => {
                    let (x0, x1) = (ax(*a), ax(*b));
                    let (lo, hi) = (x0.min(x1), x0.max(x1));
                    if hit(lo, hi) {
                        let t = (v - x0) / (x1 - x0);
                        out.push(other(*a) + t * (other(*b) - other(*a)));
                    }
                }
                Seg::Arc { .. } | Seg::Cubic { .. } => {
                    // bracket on a fine chord chain, then refine on the curve
                    let n = 256;
                    let at = |t: f64| sub_seg(g, t, t).start();
                    let mut p0 = at(0.0);
                    for k in 1..=n {
                        let t1 = k as f64 / n as f64;
                        let p1 = if k == n { g.end() } else { at(t1) };
                        let (x0, x1) = (ax(p0), ax(p1));
                        let (lo, hi) = (x0.min(x1), x0.max(x1));
                        if hit(lo, hi) {
                            let (mut a0, mut a1) = ((k - 1) as f64 / n as f64, t1);
                            let up = x1 > x0;
                            for _ in 0..60 {
                                let m = (a0 + a1) / 2.0;
                                if (ax(at(m)) < v) == up {
                                    a0 = m;
                                } else {
                                    a1 = m;
                                }
                            }
                            let q = if x0 == v { p0 } else if x1 == v { p1 } else { at((a0 + a1) / 2.0) };
                            out.push(other(q));
                        }
                        p0 = p1;
                    }
                }
            }
        }
    }
    out
}

// Parameter points (t in 0..1 along the segment, point) where an arc/cubic crosses {axis = v}.
fn seg_cuts(g: &Seg, along_x: bool, v: f64) -> Vec<(f64, P)> {
    let ax = |p: P| if along_x { p.x } else { p.y };
    let n = 256;
    let at = |t: f64| -> P {
        match g {
            Seg::Line { a, b } => a.add(b.sub(*a).mul(t)),
            Seg::Arc { a, c, sweep, .. } => {
                let vv = a.sub(*c);
                let (sn, cs) = (sweep * t).sin_cos();
                pt(c.x + vv.x * cs - vv.y * sn, c.y + vv.x * sn + vv.y * cs)
            }
            Seg::Cubic { a, c1, c2, b } => {
                let mt = 1.0 - t;
                a.mul(mt * mt * mt).add(c1.mul(3.0 * mt * mt * t)).add(c2.mul(3.0 * mt * t * t)).add(b.mul(t * t * t))
            }
        }
    };
    let mut out = Vec::new();
    let mut prev = ax(at(0.0)) - v;
    for k in 1..=n {
        let t1 = k as f64 / n as f64;
        let cur = ax(at(t1)) - v;
        if (prev < 0.0 && cur >= 0.0) || (prev > 0.0 && cur <= 0.0) {
            // bisect
            let (mut lo, mut hi) = ((k - 1) as f64 / n as f64, t1);
            for _ in 0..60 {
                let mid = (lo + hi) / 2.0;
                let mv = ax(at(mid)) - v;
                if (mv < 0.0) == (prev < 0.0) {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            let t = (lo + hi) / 2.0;
            out.push((t, at(t)));
        }
        prev = cur;
    }
    out
}

fn break_line(shape: &Shape, along_x: bool, cut: f64, at: f64, upper: bool) -> Vec<P> {
    let ys = crossings(shape, along_x, cut, upper);
    if ys.is_empty() {
        return vec![];
    }
    let lo = ys.iter().cloned().fold(f64::INFINITY, f64::min);
    let hi = ys.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let h = hi - lo;
    let c = (lo + hi) / 2.0;
    let zh = (0.28 * h).min(9.0);
    let xa = (0.2 * h).min(4.5);
    let pk = 0.15 * zh;
    let pts = [
        (at, lo - AXIS_OVERHANG),
        (at, c - zh),
        (at + xa, c - pk),
        (at - xa, c + pk),
        (at, c + zh),
        (at, hi + AXIS_OVERHANG),
    ];
    pts.iter().map(|&(a, o)| if along_x { pt(a, o) } else { pt(o, a) }).collect()
}

// Split a segment at the cut stations; returns pieces.
fn split_seg(g: &Seg, along_x: bool, cuts: &[f64]) -> Vec<Seg> {
    let mut ts: Vec<f64> = Vec::new();
    for &v in cuts {
        match g {
            Seg::Line { a, b } => {
                let ax = |p: P| if along_x { p.x } else { p.y };
                let (u, w) = (ax(*a) - v, ax(*b) - v);
                if (u < 0.0 && w > 0.0) || (u > 0.0 && w < 0.0) {
                    ts.push(u / (u - w));
                }
            }
            _ => {
                for (t, _) in seg_cuts(g, along_x, v) {
                    if t > 1e-6 && t < 1.0 - 1e-6 {
                        ts.push(t);
                    }
                }
            }
        }
    }
    ts.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut out = Vec::new();
    let mut t0 = 0.0;
    for &t in ts.iter().chain(std::iter::once(&1.0)) {
        out.push(sub_seg(g, t0, t));
        t0 = t;
    }
    out
}

fn sub_seg(g: &Seg, t0: f64, t1: f64) -> Seg {
    match g {
        Seg::Line { a, b } => {
            let d = b.sub(*a);
            Seg::Line { a: if t0 == 0.0 { *a } else { a.add(d.mul(t0)) }, b: if t1 == 1.0 { *b } else { a.add(d.mul(t1)) } }
        }
        Seg::Arc { a, b, c, r, sweep, .. } => {
            let v = a.sub(*c);
            let rotp = |t: f64| {
                let (sn, cs) = (sweep * t).sin_cos();
                pt(c.x + v.x * cs - v.y * sn, c.y + v.x * sn + v.y * cs)
            };
            let na = if t0 == 0.0 { *a } else { rotp(t0) };
            let nb = if t1 == 1.0 { *b } else { rotp(t1) };
            let ns = sweep * (t1 - t0);
            Seg::Arc { a: na, b: nb, c: *c, r: *r, sweep: ns, large: ns.abs() > std::f64::consts::PI }
        }
        Seg::Cubic { .. } => {
            // de Casteljau
            let (p0, p1, p2, p3) = match g {
                Seg::Cubic { a, c1, c2, b } => (*a, *c1, *c2, *b),
                _ => unreachable!(),
            };
            let split = |p0: P, p1: P, p2: P, p3: P, t: f64| -> ((P, P, P, P), (P, P, P, P)) {
                let l = |u: P, v: P| u.add(v.sub(u).mul(t));
                let a = l(p0, p1);
                let b = l(p1, p2);
                let c = l(p2, p3);
                let d = l(a, b);
                let e = l(b, c);
                let f = l(d, e);
                ((p0, a, d, f), (f, e, c, p3))
            };
            let (_, right) = split(p0, p1, p2, p3, t0);
            let tt = if t0 < 1.0 { (t1 - t0) / (1.0 - t0) } else { 1.0 };
            let (left, _) = split(right.0, right.1, right.2, right.3, tt);
            Seg::Cubic { a: left.0, c1: left.1, c2: left.2, b: left.3 }
        }
    }
}

fn mid_of(g: &Seg) -> P {
    sub_seg(g, 0.5, 0.5).start()
}

// Cut out the stretch a < axis < b and close the gap to BREAK_GAP.
fn break_shape(shape: &Shape, along_x: bool, a: f64, b: f64, shift: f64) -> Shape {
    let ax = |p: P| if along_x { p.x } else { p.y };
    let mv = |p: P| if ax(p) >= b - 1e-9 { if along_x { pt(p.x - shift, p.y) } else { pt(p.x, p.y - shift) } } else { p };
    let mut out = Vec::new();
    for s in &shape.subs {
        let mut segs: Vec<(Seg, Option<String>)> = s.segs.iter().cloned().zip(s.tags.iter().cloned()).collect();
        if s.closed && !s.end().near(s.start) {
            segs.push((Seg::Line { a: s.end(), b: s.start }, None));
        }
        let mut pieces: Vec<Vec<(Seg, Option<String>)>> = vec![vec![]];
        let mut cut_first = false;
        let mut removed = false;
        for (k, (g, tag)) in segs.iter().enumerate() {
            for part in split_seg(g, along_x, &[a, b]) {
                let m = ax(mid_of(&part));
                if m > a + 1e-9 && m < b - 1e-9 {
                    removed = true;
                    if k == 0 && pieces.len() == 1 && pieces[0].is_empty() {
                        cut_first = true;
                    }
                    if !pieces.last().unwrap().is_empty() {
                        pieces.push(vec![]);
                    }
                    continue;
                }
                pieces.last_mut().unwrap().push((part, tag.clone()));
            }
        }
        if !removed {
            out.push(s.map(&|p| mv(p), false));
            continue;
        }
        if pieces.last().map(|p| p.is_empty()).unwrap_or(false) {
            pieces.pop();
        }
        let mut order = Vec::new();
        if s.closed && !cut_first && pieces.len() >= 2 {
            let first = pieces.remove(0);
            let mut last = pieces.pop().unwrap();
            order.extend(pieces);
            last.extend(first);
            order.push(last);
        } else {
            order = pieces;
        }
        for p in order {
            if p.is_empty() {
                continue;
            }
            let start = mv(p[0].0.start());
            let mut sub = Sub { start, segs: vec![], tags: vec![], closed: false, circle: false };
            for (g, t) in p {
                sub.segs.push(g.map(&|q| mv(q), false));
                sub.tags.push(t);
            }
            out.push(sub);
        }
    }
    let points = shape.points.iter().map(|(n, p)| (n.clone(), mv(*p))).collect();
    Shape { subs: out, points }
}

// Tagged segments and point() stations of a laid-out sketch, in px in its
// pen frame (where its path and children draw), after mirror / revolve /
// break. A tag on a run split by a break names each of its pieces.
#[allow(dead_code)]
pub fn pattern_copy(ctx: &Ctx, wrapper: usize, k: usize) -> Option<usize> {
    if !ctx.sk.wrappers.contains_key(&wrapper) || k == 0 {
        return None;
    }
    ctx.nodes[wrapper].children.iter().copied().filter(|c| !ctx.sk.chrome.contains_key(c)).nth(k - 1)
}

#[allow(dead_code)]
pub fn sketch_tags(ctx: &Ctx, i: usize) -> Vec<sketch::Tag> {
    match ctx.sk.laid.get(&i) {
        Some(l) => l.shape.tags(),
        None => vec![],
    }
}

// ------------------------------------------------------------ render

// Shape elements that replace the primitive's default outline.
pub fn shape_override(ctx: &Ctx, i: usize) -> Option<Vec<String>> {
    if ctx.sk.wrappers.contains_key(&i) {
        let n = &ctx.nodes[i];
        return Some(match n.prim {
            Prim::Block => {
                if n.w == 0.0 || n.h == 0.0 {
                    vec![]
                } else {
                    // the rect sits on the copies' union
                    let mut bb = BBox::empty();
                    for &ch in &n.children {
                        if ctx.sk.chrome.contains_key(&ch) {
                            continue;
                        }
                        let (ow, oh) = crate::layout::outer(ctx, ch);
                        let (cx, cy) = (ctx.nodes[ch].x, ctx.nodes[ch].y);
                        bb.add(cx - ow / 2.0, cy - oh / 2.0);
                        bb.add(cx + ow / 2.0, cy + oh / 2.0);
                    }
                    let (x0, y0) = if bb.is_empty() { (-n.w / 2.0, -n.h / 2.0) } else { (bb.x0, bb.y0) };
                    let r = ctx.comp[i].radius;
                    vec![format!(
                        "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"{}\" ry=\"{}\"/>",
                        f4(x0),
                        f4(y0),
                        f4(n.w),
                        f4(n.h),
                        f4(r),
                        f4(r)
                    )]
                }
            }
            Prim::Oval => vec![format!("<ellipse cx=\"0\" cy=\"0\" rx=\"{}\" ry=\"{}\"/>", f4(n.w / 2.0), f4(n.h / 2.0))],
            _ => vec![],
        });
    }
    if ctx.nodes[i].prim == Prim::Sketch {
        return Some(match ctx.sk.laid.get(&i) {
            Some(l) => vec![format!("<path d=\"{}\" fill-rule=\"evenodd\"/>", l.path)],
            None => vec![],
        });
    }
    None
}

pub fn is_chrome(ctx: &Ctx, i: usize) -> bool {
    (ctx.sk.chrome.contains_key(&i) && !matches!(ctx.sk.chrome.get(&i), Some(Chrome::Ring(_))))
        || ctx.sk.planes.contains_key(&i)
}

// Chrome lines: one group per generated line.
pub fn render_chrome(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    if ctx.sk.planes.contains_key(&i) {
        return render_plane(ctx, i, ind_n, s, out);
    }
    let kind = ctx.sk.chrome.get(&i).cloned();
    let geoms = ctx.sk.geoms.get(&i).cloned().unwrap_or_default();
    let n = &ctx.nodes[i];
    let pad = " ".repeat(ind_n);
    let inner = " ".repeat(ind_n + 2);
    let tx = n.x + ctx.comp[i].translate.0 + n.geo_off.0;
    let ty = n.y + ctx.comp[i].translate.1 + n.geo_off.1;
    let arc = matches!(kind, Some(Chrome::ThreadArc(_)));
    let single = matches!(kind, Some(Chrome::Axis(_)) | Some(Chrome::HoleX) | Some(Chrome::HoleY) | Some(Chrome::ThreadArc(_)));
    if geoms.is_empty() && !single {
        return Ok(());
    }
    let cls = if arc {
        for t in ["threadline"] {
            if !out.used_types.iter().any(|u| u == t) {
                out.used_types.push(t.to_string());
            }
        }
        let user_path = ctx.nodes.iter().enumerate().any(|(k, m)| m.is("path") && !ctx.sk.chrome.contains_key(&k));
        if !user_path {
            let rule = (String::from("path"), ".lini-path { stroke-dasharray: none; }".to_string());
            if !out.extra_rules.contains(&rule) {
                out.extra_rules.push(rule);
            }
        }
        "lini-node lini-threadline lini-path".to_string()
    } else {
        crate::render::node_classes(ctx, i, out)
    };
    let head = format!("{}<g class=\"{}\" transform=\"translate({},{})\">\n", pad, cls, f4(tx), f4(ty));
    if geoms.is_empty() {
        s.push_str(&head);
        s.push_str(&format!("{}</g>\n", pad));
        return Ok(());
    }
    for g in &geoms {
        s.push_str(&head);
        match g {
            Geom::Line(a, b) => s.push_str(&format!(
                "{}<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>\n",
                inner,
                f4(a.x),
                f4(a.y),
                f4(b.x),
                f4(b.y)
            )),
            Geom::Poly(ps) => {
                let pts: Vec<String> = ps.iter().map(|p| format!("{},{}", f4(p.x), f4(p.y))).collect();
                s.push_str(&format!("{}<polyline points=\"{}\"/>\n", inner, pts.join(" ")));
            }
            Geom::Path(d) => s.push_str(&format!("{}<path d=\"{}\"/>\n", inner, d)),
        }
        s.push_str(&format!("{}</g>\n", pad));
    }
    Ok(())
}

// ------------------------------------------------------------ section planes

// Drafting constants for the cutting-plane symbol (px).
const PLANE_OVERHANG: f64 = 6.0;
const PLANE_END: f64 = 10.0;
const PLANE_SHAFT: f64 = 13.0;
const PLANE_ARROW: (f64, f64) = (12.0, 2.0);
const PLANE_LETTER_GAP: f64 = 7.0;
const PLANE_LETTER: f64 = 12.0;

#[derive(Clone, Debug, Default)]
pub struct PlaneGeo {
    pub line: (P, P),
    pub ends: Vec<(P, P)>,
    pub shafts: Vec<(P, P)>,
    pub arrows: Vec<[P; 3]>,
    pub letters: Vec<P>,
}

pub fn is_plane(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].prim == Prim::Line && ctx.nodes[i].is("plane")
}

fn plane_facing(ctx: &Ctx, i: usize) -> Result<P, Diag> {
    match ctx.nodes[i].props.get("facing") {
        None => Ok(pt(1.0, 0.0)),
        Some(v) => match ident_of(v) {
            Some("right") => Ok(pt(1.0, 0.0)),
            Some("left") => Ok(pt(-1.0, 0.0)),
            Some("up") => Ok(pt(0.0, -1.0)),
            Some("down") => Ok(pt(0.0, 1.0)),
            _ => Err(Diag::error("layout", "'facing' turns the arrows — left, right, up, or down", ctx.nodes[i].span)),
        },
    }
}

// A cutting plane: a centre line across everything else at its station,
// thick ends, and arrows (with the plane's letter) looking along `facing`.
fn lay_plane(ctx: &mut Ctx, i: usize, lo: f64, hi: f64) {
    let k = ps(ctx, i);
    let at = ctx.nodes[i].props.get("at").and_then(|v| crate::style::value_num(&ctx.sheet.env, v)).unwrap_or(0.0);
    let x = at * k;
    let d = plane_facing(ctx, i).unwrap_or(pt(1.0, 0.0));
    let y0 = lo - PLANE_OVERHANG - PLANE_END;
    let y1 = hi + PLANE_OVERHANG + PLANE_END;
    let mut g = PlaneGeo { line: (pt(x, y0), pt(x, y1)), ..Default::default() };
    g.ends = vec![(pt(x, y0), pt(x, y0 + PLANE_END)), (pt(x, y1), pt(x, y1 - PLANE_END))];
    let rn = pt(-d.y, d.x);
    for p in [pt(x, y0), pt(x, y1)] {
        let tip = p.add(d.mul(PLANE_SHAFT));
        g.shafts.push((p, tip));
        let back = tip.sub(d.mul(PLANE_ARROW.0));
        g.arrows.push([tip, back.add(rn.mul(PLANE_ARROW.1)), back.sub(rn.mul(PLANE_ARROW.1))]);
        g.letters.push(tip.add(d.mul(PLANE_LETTER_GAP)));
    }
    let mut bb = BBox::empty();
    for p in [g.line.0, g.line.1] {
        bb.add(p.x, p.y);
    }
    for (a, b) in &g.shafts {
        bb.add(a.x, a.y);
        bb.add(b.x, b.y);
    }
    for t in &g.arrows {
        for p in t {
            bb.add(p.x, p.y);
        }
    }
    if let Some(label) = ctx.nodes[i].text.clone() {
        let w = crate::font::text_width(ctx.comp[i].family, 400, PLANE_LETTER, &label);
        for p in &g.letters {
            bb.add(p.x - w / 2.0, p.y - PLANE_LETTER / 2.0);
            bb.add(p.x + w / 2.0, p.y + PLANE_LETTER / 2.0);
        }
    }
    // the symbol counts at its geometry, not its stroke
    let sw = if ctx.comp[i].has_stroke { ctx.comp[i].stroke_width } else { 0.0 };
    let n = &mut ctx.nodes[i];
    n.w = (bb.w() - sw).max(0.0);
    n.h = (bb.h() - sw).max(0.0);
    n.geo_off = (-bb.cx(), -bb.cy());
    n.x = bb.cx();
    n.y = bb.cy();
    ctx.sk.planes.insert(i, g);
}

fn push_rule(out: &mut Out, slot: &str, rule: &str) {
    let r = (slot.to_string(), rule.to_string());
    if !out.extra_rules.contains(&r) {
        out.extra_rules.push(r);
    }
}

fn render_plane(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let g = ctx.sk.planes[&i].clone();
    let n = &ctx.nodes[i];
    let pad = " ".repeat(ind_n);
    let inner = " ".repeat(ind_n + 2);
    let deep = " ".repeat(ind_n + 4);
    let cls = crate::render::node_classes(ctx, i, out);
    let style = crate::render::inline_style(ctx, i, out, false)?;
    let sty = if style.is_empty() { String::new() } else { format!(" style=\"{}\"", crate::util::xml_escape(&style)) };
    let id = match &n.id {
        Some(id) => format!(" data-id=\"{}\"", crate::util::xml_escape(id)),
        None => String::new(),
    };
    let tx = n.x + ctx.comp[i].translate.0 + n.geo_off.0;
    let ty = n.y + ctx.comp[i].translate.1 + n.geo_off.1;
    let sub = |part: &str| -> String {
        let mut v: Vec<&str> = cls.split(' ').collect();
        let last = v.pop().unwrap_or("");
        let cl = format!("lini-plane-{}", part);
        v.push(&cl);
        v.push(last);
        v.join(" ")
    };
    let line = |a: P, b: P| format!("<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>", f4(a.x), f4(a.y), f4(b.x), f4(b.y));
    // the arrows take the plane's own stroke colour as their fill
    let mut arrow_style = String::new();
    if let Some(d) = n.inline.iter().rev().find(|d| d.name == "stroke") {
        if let Some(t) = single_term(&d.value) {
            let mut tmp = Vec::new();
            if let Ok(c) = crate::style::color_css(t, &mut tmp, d.value.span) {
                for v in tmp {
                    crate::style::use_var(&mut out.vars, &v);
                }
                arrow_style = format!(" style=\"fill: {}\"", crate::util::xml_escape(&c));
            }
        }
    }
    s.push_str(&format!("{}<g class=\"{}\"{}{} transform=\"translate({},{})\">\n", pad, cls, id, sty, f4(tx), f4(ty)));
    s.push_str(&format!("{}{}\n", inner, line(g.line.0, g.line.1)));
    let end_cls = sub("end");
    for (a, b) in &g.ends {
        s.push_str(&format!("{}<g class=\"{}\"{}{} transform=\"translate(0,0)\">\n", inner, end_cls, id, sty));
        s.push_str(&format!("{}{}\n", deep, line(*a, *b)));
        s.push_str(&format!("{}</g>\n", inner));
    }
    let shaft_cls = sub("shaft");
    let label = n.text.clone();
    for k in 0..g.shafts.len() {
        let (a, b) = g.shafts[k];
        s.push_str(&format!("{}<g class=\"{}\"{}{} transform=\"translate(0,0)\">\n", inner, shaft_cls, id, sty));
        s.push_str(&format!("{}{}\n", deep, line(a, b)));
        s.push_str(&format!("{}</g>\n", inner));
        let t = g.arrows[k];
        s.push_str(&format!(
            "{}<g class=\"lini-node lini-marker lini-marker-dim lini-plane-arrow lini-poly\"{} transform=\"translate(0,0)\">\n",
            inner, arrow_style
        ));
        let pts: Vec<String> = t.iter().map(|p| format!("{},{}", f4(p.x), f4(p.y))).collect();
        s.push_str(&format!("{}<polygon points=\"{}\"/>\n", deep, pts.join(" ")));
        s.push_str(&format!("{}</g>\n", inner));
        if let Some(l) = &label {
            let p = g.letters[k];
            crate::outline::note(p.x);
            crate::outline::note(p.y);
            s.push_str(&format!(
                "{}<text class=\"lini-text lini-dim-text\" x=\"{}\" y=\"{}\" dy=\"0.358em\">{}</text>\n",
                inner,
                f4(p.x),
                f4(p.y),
                crate::util::xml_escape(l)
            ));
        }
    }
    s.push_str(&format!("{}</g>\n", pad));
    if label.is_some() {
        out.any_text = true;
        push_rule(out, "dim-text", ".lini-dim-text { font-size: 12px; font-weight: var(--lini-link-font-weight); }");
        crate::style::use_var(&mut out.vars, "link-font-weight");
    }
    out.markers = true;
    push_rule(out, "marker-dim", ".lini-marker-dim { fill: var(--lini-stroke-dark); }");
    crate::style::use_var(&mut out.vars, "stroke-dark");
    push_rule(out, "plane-end", ".lini-plane-end { stroke-width: 2; stroke-dasharray: none; }");
    push_rule(out, "plane-shaft", ".lini-plane-shaft { stroke-dasharray: none; }");
    push_rule(out, "plane-arrow", ".lini-plane-arrow { fill: var(--lini-stroke-light); }");
    crate::style::use_var(&mut out.vars, "stroke-light");
    let user_poly = ctx.nodes.iter().enumerate().any(|(k, m)| m.is("poly") && !ctx.sk.chrome.contains_key(&k));
    if !user_poly {
        push_rule(out, "poly", ".lini-poly { stroke-dasharray: none; }");
    }
    Ok(())
}
