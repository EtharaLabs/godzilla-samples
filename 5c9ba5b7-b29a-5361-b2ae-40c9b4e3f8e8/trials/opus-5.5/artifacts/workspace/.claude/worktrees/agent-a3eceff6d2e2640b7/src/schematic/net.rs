// The wiring of a schematic scope: every wire's two ends as terms — a pin's
// stub tip, a part's pin station, a label's connection point — each with
// the device (the scope's child) it belongs to, its offset from that
// device's origin and the way a wire leaves it.

use super::place::{has, is_component, is_label, is_part};
use crate::compile::Ctx;
use crate::diag::Span;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Dir {
    L,
    R,
    U,
    D,
}

impl Dir {
    pub fn opposite(self) -> Dir {
        match self {
            Dir::L => Dir::R,
            Dir::R => Dir::L,
            Dir::U => Dir::D,
            Dir::D => Dir::U,
        }
    }
    pub fn horizontal(self) -> bool {
        matches!(self, Dir::L | Dir::R)
    }
    pub fn vec(self) -> (f64, f64) {
        match self {
            Dir::L => (-1.0, 0.0),
            Dir::R => (1.0, 0.0),
            Dir::U => (0.0, -1.0),
            Dir::D => (0.0, 1.0),
        }
    }
    pub fn of_vec(dx: f64, dy: f64) -> Dir {
        if dx.abs() >= dy.abs() {
            if dx < 0.0 {
                Dir::L
            } else {
                Dir::R
            }
        } else if dy < 0.0 {
            Dir::U
        } else {
            Dir::D
        }
    }
    pub fn of_side(s: &str) -> Option<Dir> {
        Some(match s {
            "left" => Dir::L,
            "right" => Dir::R,
            "top" => Dir::U,
            "bottom" => Dir::D,
            _ => return None,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    // a component's pin (its stub tip)
    Pin,
    // a part's pin station
    Station,
    // a symbol label (ground, supply, …)
    Symbol,
    // a net-name run: the wire travels its length
    Run,
    // a drawn tag
    Flag,
    // anything else (a device named whole)
    Other,
}

#[derive(Clone, Debug)]
pub struct Term {
    pub node: usize,
    pub dev: usize,
    pub kind: Kind,
    // the connection point from the device's origin
    pub off: (f64, f64),
    // the way a wire leaves the point
    pub dir: Dir,
    // a run's other end (the wire enters there and travels its length)
    pub through: Option<(f64, f64)>,
}

#[derive(Clone, Debug)]
pub struct Wire {
    pub li: usize,
    pub a: Term,
    pub b: Term,
    pub span: Span,
}

// a node's group origin from an ancestor's origin
pub fn origin_in(ctx: &Ctx, node: usize, anc: usize) -> (f64, f64) {
    let mut x = 0.0;
    let mut y = 0.0;
    let mut cur = node;
    while cur != anc {
        let n = &ctx.nodes[cur];
        let c = &ctx.comp[cur];
        x += n.x + c.translate.0 + n.geo_off.0;
        y += n.y + c.translate.1 + n.geo_off.1;
        match n.parent {
            Some(p) => cur = p,
            None => break,
        }
    }
    (x, y)
}

// the scope's child that holds a node
pub fn device_of(ctx: &Ctx, scope: usize, node: usize) -> Option<usize> {
    let mut cur = node;
    loop {
        let p = ctx.nodes[cur].parent?;
        if p == scope {
            return Some(cur);
        }
        cur = p;
    }
}

pub fn pose_of(ctx: &Ctx, i: usize) -> (u32, Option<char>) {
    let mut rot = 0;
    let mut mirror = None;
    for c in &ctx.nodes[i].chain {
        if let Some(r) = c.strip_prefix("pose-") {
            rot = r.parse().unwrap_or(0);
        }
        if let Some(m) = c.strip_prefix("mirror-") {
            mirror = m.chars().next();
        }
    }
    (rot, mirror)
}

// a vector under a pose: mirror first, then the clockwise turn
pub fn map_vec(dx: f64, dy: f64, rot: u32, mirror: Option<char>) -> (f64, f64) {
    let (mut dx, mut dy) = (dx, dy);
    match mirror {
        Some('x') => dy = -dy,
        Some('y') => dx = -dx,
        _ => {}
    }
    match rot {
        90 => (-dy, dx),
        180 => (-dx, -dy),
        270 => (dy, -dx),
        _ => (dx, dy),
    }
}

// a point of a w x h frame under a pose
pub fn map_pt(x: f64, y: f64, w: f64, h: f64, rot: u32, mirror: Option<char>) -> (f64, f64) {
    let (mut x, mut y) = (x, y);
    match mirror {
        Some('x') => y = h - y,
        Some('y') => x = w - x,
        _ => {}
    }
    match rot {
        90 => (h - y, x),
        180 => (w - x, h - y),
        270 => (y, w - x),
        _ => (x, y),
    }
}

fn symbol_attach(sym: &str) -> Option<(f64, f64, f64, f64)> {
    // (w, h, x, y) of the drawing at pose 0
    Some(match sym {
        "gnd" => (16.0, 15.0, 8.0, 0.0),
        "earth" => (16.0, 14.0, 8.0, 0.0),
        "chassis" => (16.0, 12.0, 8.0, 0.0),
        "power" => (16.0, 20.0, 8.0, 20.0),
        "antenna" => (20.0, 20.0, 10.0, 20.0),
        "nc" => (12.0, 10.0, 0.0, 5.0),
        _ => return None,
    })
}

fn prop_ident(ctx: &Ctx, i: usize, k: &str) -> Option<String> {
    crate::render::prop_str(ctx, i, k)
}

// a label's connection point (label-local) and the way its wire leaves
fn label_term(ctx: &Ctx, l: usize) -> Option<(Kind, (f64, f64), Dir, Option<(f64, f64)>)> {
    let (rot, mirror) = pose_of(ctx, l);
    let n = &ctx.nodes[l];
    let w = n.w;
    if has(ctx, l, "net-run") || has(ctx, l, "net-run-turned") {
        // pose 0: the wire comes in from the right and runs to the left end
        let (fx, fy) = map_vec(-1.0, 0.0, rot, mirror);
        let len = if has(ctx, l, "net-run-turned") { n.h } else { w };
        let far = (fx * len / 2.0, fy * len / 2.0);
        let near = (-far.0, -far.1);
        let dir = Dir::of_vec(-fx, -fy);
        return Some((Kind::Run, far, dir, Some(near)));
    }
    // a tag attaches by whichever end faces its wire (resolved when seated
    // and routed): its two ends here
    if has(ctx, l, "tag-flag-right") || has(ctx, l, "tag-flag-left") || has(ctx, l, "tag-flag-both") || has(ctx, l, "tag-outline") {
        let hw = tag_half(ctx, l).0;
        return Some((Kind::Flag, (-hw, 0.0), Dir::L, Some((hw, 0.0))));
    }
    let sym = prop_ident(ctx, l, "symbol")?;
    let (fw, fh, ax, ay) = symbol_attach(&sym)?;
    // the drawing node
    let path = n.children.iter().cloned().find(|&c| has(ctx, c, "sch-tag-line"))?;
    let (pw, ph) = if rot == 90 || rot == 270 { (fh, fw) } else { (fw, fh) };
    let (px, py) = map_pt(ax, ay, fw, fh, rot, mirror);
    let o = origin_in(ctx, path, l);
    // the drawing's frame sits at its group origin
    let _ = (pw, ph);
    let pt = (o.0 + px, o.1 + py);
    if std::env::var("LINI_SCH_DBG").is_ok() {
        eprintln!("label {} w {:?} path.x {:?} geo {:?} o {:?} pt {:?}", l, w, ctx.nodes[path].x, ctx.nodes[path].geo_off, o, pt);
    }
    // the wire leaves away from the drawing
    let (cx, cy) = (o.0 + pw / 2.0, o.1 + ph / 2.0);
    let dir = Dir::of_vec(pt.0 - cx, pt.1 - cy);
    Some((Kind::Symbol, pt, dir, None))
}

// a tag's half extents out to its outline's outer edge (a round tag's
// outline is its stroked box; a flag's is inset by half its line)
pub fn tag_half(ctx: &Ctx, l: usize) -> (f64, f64) {
    let n = &ctx.nodes[l];
    let c = &ctx.comp[l];
    let sw = if has(ctx, l, "tag-outline") && c.has_stroke { c.stroke_width } else { 0.0 };
    (n.w / 2.0 + sw / 2.0, n.h / 2.0 + sw / 2.0)
}

// a tag's end (or edge, above or below) facing the way `toward`, and the
// way the wire leaves it
pub fn flag_end(ctx: &Ctx, t: &Term, toward: Dir) -> Term {
    let mut t = t.clone();
    if t.kind == Kind::Flag {
        let (l, r) = (t.off, t.through.unwrap_or(t.off));
        match toward {
            Dir::R => t.off = r,
            Dir::L => t.off = l,
            Dir::U => t.off = (0.0, -tag_half(ctx, t.dev).1),
            Dir::D => t.off = (0.0, tag_half(ctx, t.dev).1),
        }
        t.dir = toward;
        t.through = None;
    }
    t
}

// a link end as a term
pub fn term(ctx: &Ctx, scope: usize, node: usize) -> Option<Term> {
    let dev = device_of(ctx, scope, node)?;
    if has(ctx, node, "pin") {
        // the stub's far end
        let stub = ctx.nodes[node].children.iter().cloned().find(|&c| has(ctx, c, "pin-stub"))?;
        let side = ctx.comp[stub].pin.clone().unwrap_or_default();
        let dir = Dir::of_side(side.split_whitespace().next().unwrap_or("left")).unwrap_or(Dir::L);
        let o = origin_in(ctx, stub, dev);
        let pts = match &ctx.nodes[stub].geo {
            Some(crate::scene::Geo::Points(p)) => p.clone(),
            _ => vec![(0.0, 0.0), (20.0, 0.0)],
        };
        let mut best = (o.0 + pts[0].0, o.1 + pts[0].1);
        let score = |p: (f64, f64)| -> f64 {
            let v = dir.vec();
            p.0 * v.0 + p.1 * v.1
        };
        for p in &pts {
            let q = (o.0 + p.0, o.1 + p.1);
            if score(q) > score(best) {
                best = q;
            }
        }
        return Some(Term { node, dev, kind: Kind::Pin, off: best, dir, through: None });
    }
    if node != dev && is_part(ctx, dev) && ctx.nodes[node].id.is_some() {
        let o = origin_in(ctx, node, dev);
        let dir = Dir::of_vec(o.0, o.1);
        return Some(Term { node, dev, kind: Kind::Station, off: o, dir, through: None });
    }
    if node == dev && is_label(ctx, node) {
        let (kind, off, dir, through) = label_term(ctx, node)?;
        return Some(Term { node, dev, kind, off, dir, through });
    }
    let _ = is_component;
    Some(Term { node, dev, kind: Kind::Other, off: (0.0, 0.0), dir: Dir::R, through: None })
}

// the wires of a scope, in statement order
pub fn wires(ctx: &Ctx, scope: usize) -> Vec<Wire> {
    let mut out = Vec::new();
    for (li, l) in ctx.links.iter().enumerate() {
        if l.container != scope {
            continue;
        }
        let (a, b) = match (term(ctx, scope, l.from), term(ctx, scope, l.to)) {
            (Some(a), Some(b)) => (a, b),
            _ => continue,
        };
        out.push(Wire { li, a, b, span: l.span });
    }
    out
}
