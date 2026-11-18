// The sketch pen [SPEC 15.3]: `draw:` calls → subpaths of lines, arcs and
// cubics, with corner modifiers (chamfer / fillet), segment tags, the
// mirror / revolve / break transforms, and the path data they print as.
//
// Coordinates are y-down (screen). Bearings are in radians, 0 = up,
// clockwise positive. An arc's `sweep` is signed: positive = clockwise on
// screen (SVG sweep-flag 1).

use crate::ast::{Expr, Term, Value};
use crate::diag::{Diag, Span};
use crate::eval::Env;
use std::collections::HashMap;

// Path numbers print rounded to three decimals.
pub fn fmt3(v: f64) -> String {
    let r = (v * 1000.0).round() / 1000.0;
    if r == 0.0 {
        return "0".to_string();
    }
    format!("{}", r)
}

#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct P {
    pub x: f64,
    pub y: f64,
}

pub fn pt(x: f64, y: f64) -> P {
    P { x, y }
}

impl P {
    pub fn add(self, o: P) -> P {
        pt(self.x + o.x, self.y + o.y)
    }
    pub fn sub(self, o: P) -> P {
        pt(self.x - o.x, self.y - o.y)
    }
    pub fn mul(self, k: f64) -> P {
        pt(self.x * k, self.y * k)
    }
    pub fn dot(self, o: P) -> f64 {
        self.x * o.x + self.y * o.y
    }
    pub fn cross(self, o: P) -> f64 {
        self.x * o.y - self.y * o.x
    }
    pub fn len(self) -> f64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }
    pub fn unit(self) -> P {
        let l = self.len();
        if l == 0.0 {
            self
        } else {
            pt(self.x / l, self.y / l)
        }
    }
    // rotated 90° clockwise on screen: the right-hand normal of a heading
    pub fn right(self) -> P {
        pt(-self.y, self.x)
    }
    pub fn left(self) -> P {
        pt(self.y, -self.x)
    }
    pub fn near(self, o: P) -> bool {
        (self.x - o.x).abs() < 1e-9 && (self.y - o.y).abs() < 1e-9
    }
}

// Rotate v by `a` radians, clockwise on screen.
fn rot(v: P, a: f64) -> P {
    let (s, c) = a.sin_cos();
    pt(v.x * c - v.y * s, v.x * s + v.y * c)
}

pub fn bearing_dir(b: f64) -> P {
    pt(b.sin(), -b.cos())
}

pub fn dir_bearing(d: P) -> f64 {
    d.x.atan2(-d.y)
}

#[derive(Clone, Debug)]
pub enum Seg {
    Line { a: P, b: P },
    Arc { a: P, b: P, c: P, r: f64, sweep: f64, large: bool },
    Cubic { a: P, c1: P, c2: P, b: P },
}

impl Seg {
    pub fn start(&self) -> P {
        match self {
            Seg::Line { a, .. } | Seg::Arc { a, .. } | Seg::Cubic { a, .. } => *a,
        }
    }
    pub fn end(&self) -> P {
        match self {
            Seg::Line { b, .. } | Seg::Arc { b, .. } | Seg::Cubic { b, .. } => *b,
        }
    }
    fn set_start(&mut self, p: P) {
        match self {
            Seg::Line { a, .. } | Seg::Arc { a, .. } | Seg::Cubic { a, .. } => *a = p,
        }
    }
    // Unit tangent leaving the start / arriving at the end.
    pub fn dir_start(&self) -> Option<P> {
        match self {
            Seg::Line { a, b } => {
                let d = b.sub(*a);
                if d.len() == 0.0 {
                    None
                } else {
                    Some(d.unit())
                }
            }
            Seg::Arc { a, c, sweep, .. } => Some(arc_tangent(*a, *c, *sweep)),
            Seg::Cubic { a, c1, c2, b } => {
                for q in [c1, c2, b] {
                    let d = q.sub(*a);
                    if d.len() > 0.0 {
                        return Some(d.unit());
                    }
                }
                None
            }
        }
    }
    pub fn dir_end(&self) -> Option<P> {
        match self {
            Seg::Line { a, b } => {
                let d = b.sub(*a);
                if d.len() == 0.0 {
                    None
                } else {
                    Some(d.unit())
                }
            }
            Seg::Arc { b, c, sweep, .. } => Some(arc_tangent(*b, *c, *sweep)),
            Seg::Cubic { a, c1, c2, b } => {
                for q in [c2, c1, a] {
                    let d = b.sub(*q);
                    if d.len() > 0.0 {
                        return Some(d.unit());
                    }
                }
                None
            }
        }
    }
    pub fn map(&self, f: &dyn Fn(P) -> P, flip: bool) -> Seg {
        match self {
            Seg::Line { a, b } => Seg::Line { a: f(*a), b: f(*b) },
            Seg::Arc { a, b, c, r, sweep, large } => Seg::Arc {
                a: f(*a),
                b: f(*b),
                c: f(*c),
                r: *r,
                sweep: if flip { -*sweep } else { *sweep },
                large: *large,
            },
            Seg::Cubic { a, c1, c2, b } => Seg::Cubic { a: f(*a), c1: f(*c1), c2: f(*c2), b: f(*b) },
        }
    }
    pub fn reversed(&self) -> Seg {
        match self {
            Seg::Line { a, b } => Seg::Line { a: *b, b: *a },
            Seg::Arc { a, b, c, r, sweep, large } => Seg::Arc { a: *b, b: *a, c: *c, r: *r, sweep: -*sweep, large: *large },
            Seg::Cubic { a, c1, c2, b } => Seg::Cubic { a: *b, c1: *c2, c2: *c1, b: *a },
        }
    }
    pub fn scaled(&self, k: f64) -> Seg {
        match self {
            Seg::Arc { a, b, c, r, sweep, large } => Seg::Arc {
                a: a.mul(k),
                b: b.mul(k),
                c: c.mul(k),
                r: r * k,
                sweep: *sweep,
                large: *large,
            },
            _ => self.map(&|p| p.mul(k), false),
        }
    }
    pub fn length(&self) -> f64 {
        match self {
            Seg::Line { a, b } => b.sub(*a).len(),
            Seg::Arc { r, sweep, .. } => r * sweep.abs(),
            Seg::Cubic { a, b, .. } => b.sub(*a).len(),
        }
    }
    pub fn is_line(&self) -> bool {
        matches!(self, Seg::Line { .. })
    }
}

// Tangent of an arc at a point on it (center c, signed sweep).
fn arc_tangent(q: P, c: P, sweep: f64) -> P {
    let v = q.sub(c).unit();
    if sweep >= 0.0 {
        v.right()
    } else {
        v.left()
    }
}

// Signed turn from heading d1 to d2, clockwise positive, in (-π, π].
fn turn(d1: P, d2: P) -> f64 {
    d1.cross(d2).atan2(d1.dot(d2))
}

// Angle travelled from u to v around a circle in the direction of `sweep`, in [0, 2π).
fn travel(u: P, v: P, sweep: f64) -> f64 {
    let mut a = u.cross(v).atan2(u.dot(v));
    if sweep < 0.0 {
        a = -a;
    }
    if a < 0.0 {
        a += 2.0 * std::f64::consts::PI;
    }
    a
}

#[derive(Clone, Debug)]
pub struct Sub {
    pub start: P,
    pub segs: Vec<Seg>,
    pub tags: Vec<Option<String>>,
    pub closed: bool,
    pub circle: bool,
}

impl Sub {
    fn new(start: P) -> Sub {
        Sub { start, segs: vec![], tags: vec![], closed: false, circle: false }
    }
    pub fn end(&self) -> P {
        self.segs.last().map(|s| s.end()).unwrap_or(self.start)
    }
    fn push(&mut self, s: Seg, tag: Option<String>) {
        self.segs.push(s);
        self.tags.push(tag);
    }
    pub fn map(&self, f: &dyn Fn(P) -> P, flip: bool) -> Sub {
        Sub {
            start: f(self.start),
            segs: self.segs.iter().map(|s| s.map(f, flip)).collect(),
            tags: self.tags.clone(),
            closed: self.closed,
            circle: self.circle,
        }
    }
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub enum TagKind {
    Seg(Seg),
    Point(P),
}

#[derive(Clone, Debug)]
pub struct Tag {
    pub name: String,
    // a tagged fillet() is an Arc: its radius is the fillet's
    pub kind: TagKind,
}

#[derive(Clone, Debug, Default)]
pub struct Shape {
    pub subs: Vec<Sub>,
    pub points: Vec<(String, P)>,
}

// ------------------------------------------------------------ commands

#[derive(Clone, Debug)]
pub struct Cmd {
    pub name: String,
    pub args: Vec<f64>,
    pub tag: Option<String>,
}

pub const BUILTIN_ANCHORS: &[&str] =
    &["center", "top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"];

// Evaluate a `draw:` value into pen calls (the resolve phase).
pub fn eval_draw(env: &Env, v: &Value, decl_span: Span) -> Result<Vec<Cmd>, Diag> {
    if v.groups.len() > 1 {
        return Err(Diag::error("resolve", "'draw' is one run of pen calls — commas belong inside call arguments", decl_span));
    }
    let bad = || Diag::error("resolve", "'draw' holds pen calls and ':segment' points — see SPEC 15.3", decl_span);
    let mut out = Vec::new();
    for t in v.groups.iter().flatten() {
        let (call, tag) = match t {
            Term::Tagged(inner, tag, _) => (&**inner, Some(tag.clone())),
            _ => (t, None),
        };
        match call {
            Term::Call(name, args, _) => {
                let mut xs = Vec::new();
                for a in args {
                    xs.push(eval_num(env, a, decl_span)?);
                }
                out.push(Cmd { name: name.clone(), args: xs, tag });
            }
            _ => return Err(bad()),
        }
    }
    Ok(out)
}

fn eval_num(env: &Env, e: &Expr, span: Span) -> Result<f64, Diag> {
    match env.eval(e, &HashMap::new()) {
        Ok(v) => match v.num() {
            Some(x) => Ok(x),
            None => Err(Diag::error("resolve", "expected a number", span)),
        },
        Err(d) => Err(Diag { span, ..d }),
    }
}

// ------------------------------------------------------------ the pen

enum Corner {
    Chamfer(f64),
    Fillet(f64),
}

struct Pen {
    span: Span,
    pos: P,
    heading: Option<f64>,
    cur: Option<Sub>,
    after_close: bool,
    subs: Vec<Sub>,
    pending: Option<(Corner, Option<String>, &'static str)>,
    points: Vec<(String, P)>,
}

fn lerr(msg: &str, span: Span) -> Diag {
    Diag::error("layout", msg, span)
}

pub fn run(cmds: &[Cmd], span: Span) -> Result<Shape, Diag> {
    let mut pen = Pen {
        span,
        pos: P::default(),
        heading: None,
        cur: None,
        after_close: false,
        subs: vec![],
        pending: None,
        points: vec![],
    };
    let mut names: Vec<String> = Vec::new();
    for (k, c) in cmds.iter().enumerate() {
        if k == 0 && c.name != "move" {
            return Err(lerr("the pen starts with move(x, y)", span));
        }
        if let Some(t) = &c.tag {
            if c.name == "move" {
                return Err(lerr("'move' takes no segment — name its landing with point():name", span));
            }
            if BUILTIN_ANCHORS.contains(&t.as_str()) {
                return Err(lerr(&format!("':{}' is a built-in anchor — pick another name", t), span));
            }
            if names.contains(t) {
                return Err(lerr(&format!("':{}' is already named in this 'draw:'", t), span));
            }
            names.push(t.clone());
        }
        pen.step(c)?;
    }
    if let Some((_, _, what)) = &pen.pending {
        return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
    }
    pen.finish_sub();
    if pen.subs.is_empty() {
        return Err(lerr("'draw' draws nothing — add a pen run", span));
    }
    Ok(Shape { subs: pen.subs, points: pen.points })
}

impl Pen {
    fn finish_sub(&mut self) {
        if let Some(s) = self.cur.take() {
            if !s.segs.is_empty() {
                self.subs.push(s);
            }
        }
    }

    fn step(&mut self, c: &Cmd) -> Result<(), Diag> {
        let span = self.span;
        let a = &c.args;
        match c.name.as_str() {
            "move" => {
                if a.len() != 2 {
                    return Err(lerr("'move' takes (x, y)", span));
                }
                if let Some((_, _, what)) = &self.pending {
                    return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
                }
                self.finish_sub();
                self.pos = pt(a[0], a[1]);
                self.cur = Some(Sub::new(self.pos));
                self.after_close = false;
            }
            "up" | "down" | "left" | "right" => {
                if a.len() != 1 {
                    return Err(lerr("an orthogonal run takes a length", span));
                }
                let n = a[0];
                let (d, h) = match c.name.as_str() {
                    "up" => (pt(0.0, -1.0), 0.0),
                    "down" => (pt(0.0, 1.0), 180.0),
                    "left" => (pt(-1.0, 0.0), 270.0),
                    _ => (pt(1.0, 0.0), 90.0),
                };
                let b = self.pos.add(d.mul(n));
                let s = Seg::Line { a: self.pos, b };
                self.add(s, c.tag.clone(), Some((h as f64).to_radians()))?;
            }
            "line" => {
                if a.len() != 2 {
                    return Err(lerr("'line' takes (dx, dy)", span));
                }
                let b = pt(self.pos.x + a[0], self.pos.y + a[1]);
                let h = a[0].atan2(-a[1]);
                self.add(Seg::Line { a: self.pos, b }, c.tag.clone(), Some(h))?;
            }
            "angle" => {
                if a.len() != 2 {
                    return Err(lerr("'angle' takes (deg, n)", span));
                }
                let br = a[0].to_radians();
                let d = bearing_dir(br);
                let b = self.pos.add(d.mul(a[1]));
                self.add(Seg::Line { a: self.pos, b }, c.tag.clone(), Some(br))?;
            }
            "arc" => {
                if a.len() == 2 {
                    let (r, deg) = (a[0], a[1]);
                    let h = match self.heading {
                        Some(h) => h,
                        None => return Err(lerr("'arc(r, deg)' continues a heading — draw a run first", span)),
                    };
                    if r <= 0.0 {
                        return Err(lerr("'arc(r, deg)' takes a radius > 0", span));
                    }
                    if deg == 0.0 || deg <= -360.0 || deg >= 360.0 {
                        return Err(lerr("'arc(r, deg)' sweeps within (-360, 360), not 0", span));
                    }
                    let hd = bearing_dir(h);
                    let cw = deg > 0.0;
                    let center = if cw { self.pos.add(hd.right().mul(r)) } else { self.pos.add(hd.left().mul(r)) };
                    let sw = deg.to_radians();
                    let b = center.add(rot(self.pos.sub(center), sw));
                    let s = Seg::Arc { a: self.pos, b, c: center, r, sweep: sw, large: deg.abs() > 180.0 };
                    self.add(s, c.tag.clone(), Some(h + sw))?;
                } else if a.len() == 3 {
                    let (dx, dy, r) = (a[0], a[1], a[2]);
                    let b = pt(self.pos.x + dx, self.pos.y + dy);
                    let chord = pt(dx, dy);
                    if chord.len() == 0.0 {
                        return Err(lerr("'arc' needs a non-zero chord — a full turn is 'circle(r)'", span));
                    }
                    let half = chord.len() / 2.0;
                    let ra = r.abs();
                    if ra < half {
                        return Err(lerr(&format!("arc radius {} is smaller than half the chord", fmt3(ra)), span));
                    }
                    let u = chord.unit();
                    let d = (ra * ra - half * half).max(0.0).sqrt();
                    let mid = pt(self.pos.x + dx / 2.0, self.pos.y + dy / 2.0);
                    let cw = r > 0.0;
                    let center = if cw { mid.add(u.right().mul(d)) } else { mid.add(u.left().mul(d)) };
                    let ang = if ra > 0.0 { 2.0 * (half / ra).min(1.0).asin() } else { 0.0 };
                    let sw = if cw { ang } else { -ang };
                    let s = Seg::Arc { a: self.pos, b, c: center, r: ra, sweep: sw, large: false };
                    let h = dir_bearing(arc_tangent(b, center, sw));
                    self.add(s, c.tag.clone(), Some(h))?;
                } else {
                    return Err(lerr("'arc' takes (dx, dy, r) or (r, deg)", span));
                }
            }
            "curve" => {
                if a.len() != 6 {
                    return Err(lerr("'curve' takes (dx1, dy1, dx2, dy2, dx, dy)", span));
                }
                let p0 = self.pos;
                let c1 = pt(p0.x + a[0], p0.y + a[1]);
                let c2 = pt(p0.x + a[2], p0.y + a[3]);
                let b = pt(p0.x + a[4], p0.y + a[5]);
                let d = b.sub(c2);
                let h = if d.len() == 0.0 { None } else { Some(dir_bearing(d)) };
                self.add(Seg::Cubic { a: p0, c1, c2, b }, c.tag.clone(), h)?;
            }
            "circle" => {
                if a.len() != 1 {
                    return Err(lerr("'circle' takes a radius", span));
                }
                let r = a[0];
                if r <= 0.0 {
                    return Err(lerr("'circle' takes a radius > 0", span));
                }
                let cc = self.pos;
                let w = pt(cc.x - r, cc.y);
                let e = pt(cc.x + r, cc.y);
                let mut s = Sub::new(w);
                s.push(Seg::Arc { a: w, b: e, c: cc, r, sweep: std::f64::consts::PI, large: false }, c.tag.clone());
                s.push(Seg::Arc { a: e, b: w, c: cc, r, sweep: std::f64::consts::PI, large: false }, None);
                s.closed = true;
                s.circle = true;
                self.subs.push(s);
            }
            "chamfer" | "fillet" => {
                let what: &'static str = if c.name == "chamfer" { "chamfer" } else { "fillet" };
                if a.len() != 1 || self.pending.is_some() {
                    return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
                }
                let k = if what == "chamfer" { Corner::Chamfer(a[0]) } else { Corner::Fillet(a[0]) };
                if self.after_close {
                    // the corner at the closed subpath's start
                    let sub = match self.subs.iter_mut().rev().find(|s| !s.circle) {
                        Some(s) => s,
                        None => return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span)),
                    };
                    if sub.segs.len() < 2 {
                        return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
                    }
                    let last = sub.segs.len() - 1;
                    let prev = sub.segs[last].clone();
                    let next = sub.segs[0].clone();
                    let (p2, mid, n2) = corner(&prev, &next, &k, what, span)?;
                    sub.segs[last] = p2;
                    sub.segs[0] = n2.clone();
                    sub.start = n2.start();
                    sub.segs.push(mid);
                    sub.tags.push(c.tag.clone());
                    self.pos = sub.start;
                    return Ok(());
                }
                let has_prev = self.cur.as_ref().map(|s| !s.segs.is_empty()).unwrap_or(false);
                if !has_prev {
                    return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
                }
                self.pending = Some((k, c.tag.clone(), what));
            }
            "point" => {
                if !a.is_empty() {
                    return Err(lerr("'point()' takes no arguments", span));
                }
                match &c.tag {
                    Some(t) => self.points.push((t.clone(), self.pos)),
                    None => return Err(lerr("'point()' names the pen's position — attach a ':segment'", span)),
                }
            }
            "close" => {
                if self.after_close {
                    return Err(lerr("after close(), start the next subpath with move()", span));
                }
                let has = self.cur.as_ref().map(|s| !s.segs.is_empty()).unwrap_or(false);
                if !has {
                    return Err(lerr("close() needs a drawn subpath", span));
                }
                let start = self.cur.as_ref().unwrap().start;
                if !self.pos.near(start) {
                    let s = Seg::Line { a: self.pos, b: start };
                    let d = start.sub(self.pos);
                    self.add(s, c.tag.clone(), Some(dir_bearing(d)))?;
                } else if let Some((_, _, what)) = &self.pending {
                    return Err(lerr(&format!("'{}' modifies the corner between two segments", what), span));
                }
                let mut s = self.cur.take().unwrap();
                s.closed = true;
                self.pos = s.start;
                self.subs.push(s);
                self.after_close = true;
            }
            other => return Err(lerr(&format!("unknown draw call '{}'", other), span)),
        }
        Ok(())
    }

    // Append a drawn segment, resolving a pending corner modifier first.
    fn add(&mut self, s: Seg, tag: Option<String>, heading: Option<f64>) -> Result<(), Diag> {
        let span = self.span;
        if self.after_close {
            return Err(lerr("after close(), start the next subpath with move()", span));
        }
        let cur = match self.cur.as_mut() {
            Some(c) => c,
            None => return Err(lerr("the pen starts with move(x, y)", span)),
        };
        let mut s = s;
        if let Some((k, ktag, what)) = self.pending.take() {
            let prev = cur.segs.last().unwrap().clone();
            let (p2, mid, n2) = corner(&prev, &s, &k, what, span)?;
            let li = cur.segs.len() - 1;
            cur.segs[li] = p2;
            cur.push(mid, ktag);
            s = n2;
        }
        self.pos = s.end();
        cur.push(s, tag);
        self.heading = heading;
        Ok(())
    }
}

// Cut a segment's end back by length n (lines: distance; arcs: arc length).
fn trim_end(s: &Seg, n: f64) -> (Seg, P) {
    match s {
        Seg::Line { a, b } => {
            let d = b.sub(*a).unit();
            let q = b.sub(d.mul(n));
            (Seg::Line { a: *a, b: q }, q)
        }
        Seg::Arc { a, b, c, r, sweep, .. } => {
            let da = n / r * sweep.signum();
            let q = c.add(rot(b.sub(*c), -da));
            let ns = sweep - da;
            (Seg::Arc { a: *a, b: q, c: *c, r: *r, sweep: ns, large: ns.abs() > std::f64::consts::PI }, q)
        }
        Seg::Cubic { .. } => (s.clone(), s.end()),
    }
}

fn trim_start(s: &Seg, n: f64) -> (Seg, P) {
    match s {
        Seg::Line { a, b } => {
            let d = b.sub(*a).unit();
            let q = a.add(d.mul(n));
            (Seg::Line { a: q, b: *b }, q)
        }
        Seg::Arc { a, b, c, r, sweep, .. } => {
            let da = n / r * sweep.signum();
            let q = c.add(rot(a.sub(*c), da));
            let ns = sweep - da;
            (Seg::Arc { a: q, b: *b, c: *c, r: *r, sweep: ns, large: ns.abs() > std::f64::consts::PI }, q)
        }
        Seg::Cubic { .. } => (s.clone(), s.start()),
    }
}

// The offset of a segment toward `side` (+1 right, -1 left) by r:
// lines → (point on the offset line, direction); arcs → (center, radius).
enum Off {
    Line,
    Circle(P, f64),
}

fn offset(s: &Seg, side: f64, r: f64, at: P) -> Off {
    match s {
        Seg::Arc { c, r: ra, sweep, .. } => {
            // the center lies right of travel when clockwise
            let center_side = if *sweep >= 0.0 { 1.0 } else { -1.0 };
            if center_side == side {
                Off::Circle(*c, ra - r)
            } else {
                Off::Circle(*c, ra + r)
            }
        }
        _ => {
            let _ = (at, r);
            Off::Line
        }
    }
}

// Apply a corner modifier between `prev` and `next` (which meet at a point).
// Returns (prev trimmed, the inserted segment, next trimmed).
fn corner(prev: &Seg, next: &Seg, k: &Corner, what: &str, span: Span) -> Result<(Seg, Seg, Seg), Diag> {
    let nofit = || lerr(&format!("'{}' does not fit its corner", what), span);
    if matches!(prev, Seg::Cubic { .. }) || matches!(next, Seg::Cubic { .. }) {
        return Err(lerr(&format!("'{}' joins lines and arcs, not a curve()", what), span));
    }
    let d1 = prev.dir_end().unwrap_or(pt(0.0, 0.0));
    let d2 = next.dir_start().unwrap_or(pt(0.0, 0.0));
    let delta = turn(d1, d2);
    if d1.cross(d2).abs() < 1e-9 || d1.len() == 0.0 || d2.len() == 0.0 {
        return Err(lerr(&format!("'{}' needs a turn between its two runs", what), span));
    }
    let cpt = prev.end();
    match k {
        Corner::Chamfer(n) => {
            let n = *n;
            if !(n > 0.0) {
                return Err(nofit());
            }
            if prev.length() - n < 1e-9 || next.length() - n < 1e-9 {
                // (reported without a span)
                return Err(lerr(&format!("'{}' does not fit its corner", what), Span::default()));
            }
            let (p2, q1) = trim_end(prev, n);
            let (n2, q2) = trim_start(next, n);
            Ok((p2, Seg::Line { a: q1, b: q2 }, n2))
        }
        Corner::Fillet(r) => {
            let r = *r;
            if !(r > 0.0) {
                return Err(nofit());
            }
            let side = if delta > 0.0 { 1.0 } else { -1.0 };
            let (t1, t2, f);
            match (prev, next) {
                (Seg::Line { .. }, Seg::Line { .. }) => {
                    let t = r / ((std::f64::consts::PI - delta.abs()) / 2.0).tan();
                    if t > prev.length() + 1e-6 || t > next.length() + 1e-6 {
                        return Err(nofit());
                    }
                    t1 = cpt.sub(d1.mul(t));
                    t2 = cpt.add(d2.mul(t));
                    let n1 = if side > 0.0 { d1.right() } else { d1.left() };
                    f = t1.add(n1.mul(r));
                }
                (Seg::Line { .. }, _) => {
                    // offset line through the corner, searched backwards from it
                    let (oc, orad) = match offset(next, side, r, cpt) {
                        Off::Circle(c, rr) => (c, rr),
                        _ => unreachable!(),
                    };
                    let n1 = if side > 0.0 { d1.right() } else { d1.left() };
                    let q = cpt.add(n1.mul(r)).sub(oc);
                    let b = q.dot(d1);
                    let disc = b * b - q.dot(q) + orad * orad;
                    if disc < 0.0 || orad <= 0.0 {
                        return Err(nofit());
                    }
                    let s = b + disc.sqrt();
                    if s < -1e-9 || s > prev.length() + 1e-6 {
                        return Err(nofit());
                    }
                    t1 = cpt.sub(d1.mul(s));
                    f = t1.add(n1.mul(r));
                    let (c, ra) = arc_cr(next);
                    t2 = c.add(f.sub(c).unit().mul(ra));
                    if !on_arc_from_start(next, t2) {
                        return Err(nofit());
                    }
                }
                (_, Seg::Line { .. }) => {
                    let (oc, orad) = match offset(prev, side, r, cpt) {
                        Off::Circle(c, rr) => (c, rr),
                        _ => unreachable!(),
                    };
                    let n2 = if side > 0.0 { d2.right() } else { d2.left() };
                    let q = cpt.add(n2.mul(r)).sub(oc);
                    let b = q.dot(d2);
                    let disc = b * b - q.dot(q) + orad * orad;
                    if disc < 0.0 || orad <= 0.0 {
                        return Err(nofit());
                    }
                    let s = -b + disc.sqrt();
                    if s < -1e-9 || s > next.length() + 1e-6 {
                        return Err(nofit());
                    }
                    t2 = cpt.add(d2.mul(s));
                    f = t2.add(n2.mul(r));
                    let (c, ra) = arc_cr(prev);
                    t1 = c.add(f.sub(c).unit().mul(ra));
                    if !on_arc_to_end(prev, t1) {
                        return Err(nofit());
                    }
                }
                _ => {
                    let (c1, r1) = match offset(prev, side, r, cpt) {
                        Off::Circle(c, rr) => (c, rr),
                        _ => unreachable!(),
                    };
                    let (c2, r2) = match offset(next, side, r, cpt) {
                        Off::Circle(c, rr) => (c, rr),
                        _ => unreachable!(),
                    };
                    let dv = c2.sub(c1);
                    let d = dv.len();
                    if d == 0.0 || r1 <= 0.0 || r2 <= 0.0 {
                        return Err(nofit());
                    }
                    let aa = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
                    let hh = r1 * r1 - aa * aa;
                    if hh < 0.0 {
                        return Err(nofit());
                    }
                    let h = hh.sqrt();
                    let u = dv.unit();
                    let base = c1.add(u.mul(aa));
                    let ca = base.add(u.right().mul(h));
                    let cb = base.sub(u.right().mul(h));
                    f = if ca.sub(cpt).len() <= cb.sub(cpt).len() { ca } else { cb };
                    let (ac1, ar1) = arc_cr(prev);
                    let (ac2, ar2) = arc_cr(next);
                    t1 = ac1.add(f.sub(ac1).unit().mul(ar1));
                    t2 = ac2.add(f.sub(ac2).unit().mul(ar2));
                    if !on_arc_to_end(prev, t1) || !on_arc_from_start(next, t2) {
                        return Err(nofit());
                    }
                }
            }
            let p2 = cut_end_at(prev, t1);
            let n2 = cut_start_at(next, t2);
            let u = t1.sub(f);
            let v = t2.sub(f);
            let mut sw = u.cross(v).atan2(u.dot(v));
            if sw * side < 0.0 {
                sw += side * 2.0 * std::f64::consts::PI;
            }
            // a fillet never turns more than its corner: always the minor arc
            let arc = Seg::Arc { a: t1, b: t2, c: f, r, sweep: sw, large: false };
            Ok((p2, arc, n2))
        }
    }
}

fn arc_cr(s: &Seg) -> (P, f64) {
    match s {
        Seg::Arc { c, r, .. } => (*c, *r),
        _ => (P::default(), 0.0),
    }
}

fn on_arc_from_start(s: &Seg, q: P) -> bool {
    if let Seg::Arc { a, c, sweep, .. } = s {
        let t = travel(a.sub(*c), q.sub(*c), *sweep);
        t <= sweep.abs() + 1e-9 || t > 2.0 * std::f64::consts::PI - 1e-9
    } else {
        true
    }
}

fn on_arc_to_end(s: &Seg, q: P) -> bool {
    if let Seg::Arc { b, c, sweep, .. } = s {
        let t = travel(q.sub(*c), b.sub(*c), *sweep);
        t <= sweep.abs() + 1e-9 || t > 2.0 * std::f64::consts::PI - 1e-9
    } else {
        true
    }
}

fn cut_end_at(s: &Seg, q: P) -> Seg {
    match s {
        Seg::Line { a, .. } => Seg::Line { a: *a, b: q },
        Seg::Arc { a, c, r, sweep, .. } => {
            let t = travel(a.sub(*c), q.sub(*c), *sweep);
            let t = if t > 2.0 * std::f64::consts::PI - 1e-9 { 0.0 } else { t };
            let ns = t * sweep.signum();
            Seg::Arc { a: *a, b: q, c: *c, r: *r, sweep: ns, large: ns.abs() > std::f64::consts::PI }
        }
        Seg::Cubic { .. } => s.clone(),
    }
}

fn cut_start_at(s: &Seg, q: P) -> Seg {
    match s {
        Seg::Line { b, .. } => Seg::Line { a: q, b: *b },
        Seg::Arc { b, c, r, sweep, .. } => {
            let t = travel(q.sub(*c), b.sub(*c), *sweep);
            let t = if t > 2.0 * std::f64::consts::PI - 1e-9 { 0.0 } else { t };
            let ns = t * sweep.signum();
            Seg::Arc { a: q, b: *b, c: *c, r: *r, sweep: ns, large: ns.abs() > std::f64::consts::PI }
        }
        Seg::Cubic { .. } => s.clone(),
    }
}

// ------------------------------------------------------------ transforms

impl Shape {
    pub fn scaled(&self, k: f64) -> Shape {
        Shape {
            subs: self
                .subs
                .iter()
                .map(|s| Sub {
                    start: s.start.mul(k),
                    segs: s.segs.iter().map(|g| g.scaled(k)).collect(),
                    tags: s.tags.clone(),
                    closed: s.closed,
                    circle: s.circle,
                })
                .collect(),
            points: self.points.iter().map(|(n, p)| (n.clone(), p.mul(k))).collect(),
        }
    }

    pub fn has_open(&self) -> bool {
        self.subs.iter().any(|s| !s.closed)
    }

    // Reflect across a line through the origin with unit direction `d`:
    // an open subpath fuses with its reflection, a closed one is twinned.
    pub fn mirror(&self, d: P) -> Shape {
        let refl = move |p: P| {
            let k = 2.0 * p.dot(d);
            pt(d.x * k - p.x, d.y * k - p.y)
        };
        let n = d.right();
        let on_axis = |p: P| p.dot(n).abs() < 1e-9;
        let mut out = Vec::new();
        for s in &self.subs {
            if s.closed {
                out.push(s.clone());
                let mut twin = s.map(&refl, true);
                twin.tags = vec![None; twin.segs.len()];
                out.push(twin);
                continue;
            }
            let mut f = s.clone();
            let end = s.end();
            if !on_axis(end) {
                f.push(Seg::Line { a: end, b: refl(end) }, None);
            }
            for g in s.segs.iter().rev() {
                f.push(g.map(&refl, true).reversed(), None);
            }
            let ms = refl(s.start);
            if !on_axis(s.start) {
                f.push(Seg::Line { a: ms, b: s.start }, None);
            }
            f.closed = true;
            out.push(f);
        }
        Shape { subs: out, points: self.points.clone() }
    }

    pub fn path_data(&self) -> String {
        let mut parts: Vec<String> = Vec::new();
        for s in &self.subs {
            let mut o = format!("M {} {}", fmt3(s.start.x), fmt3(s.start.y));
            let n = s.segs.len();
            for (k, g) in s.segs.iter().enumerate() {
                if s.closed && k + 1 == n && g.is_line() {
                    break;
                }
                match g {
                    Seg::Line { b, .. } => o.push_str(&format!(" L {} {}", fmt3(b.x), fmt3(b.y))),
                    Seg::Arc { b, r, sweep, large, .. } => o.push_str(&format!(
                        " A {} {} 0 {} {} {} {}",
                        fmt3(*r),
                        fmt3(*r),
                        if *large { 1 } else { 0 },
                        if *sweep > 0.0 { 1 } else { 0 },
                        fmt3(b.x),
                        fmt3(b.y)
                    )),
                    Seg::Cubic { c1, c2, b, .. } => o.push_str(&format!(
                        " C {} {} {} {} {} {}",
                        fmt3(c1.x),
                        fmt3(c1.y),
                        fmt3(c2.x),
                        fmt3(c2.y),
                        fmt3(b.x),
                        fmt3(b.y)
                    )),
                }
            }
            if s.closed {
                o.push_str(" Z");
            }
            parts.push(o);
        }
        parts.join(" ")
    }

    // Every tagged segment / point, in drawing order.
    pub fn tags(&self) -> Vec<Tag> {
        let mut out = Vec::new();
        for s in &self.subs {
            for (k, t) in s.tags.iter().enumerate() {
                if let Some(name) = t {
                    let seg = s.segs[k].clone();
                    out.push(Tag { name: name.clone(), kind: TagKind::Seg(seg) });
                }
            }
        }
        for (n, p) in &self.points {
            out.push(Tag { name: n.clone(), kind: TagKind::Point(*p) });
        }
        out
    }
}

// ------------------------------------------------------------ walls

fn line_x(a1: P, d1: P, a2: P, d2: P) -> Option<P> {
    let den = d1.cross(d2);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = a2.sub(a1).cross(d2) / den;
    Some(a1.add(d1.mul(t)))
}

// One side of a drawn run offset by `h` (side +1 = the pen's left).
fn offset_seg(g: &Seg, side: f64, h: f64) -> Seg {
    match g {
        Seg::Line { a, b } => {
            let n = b.sub(*a).unit().left().mul(side * h);
            Seg::Line { a: a.add(n), b: b.add(n) }
        }
        Seg::Arc { a, b, c, r, sweep, large } => {
            let rr = r + side * h * if *sweep > 0.0 { 1.0 } else { -1.0 };
            Seg::Arc {
                a: c.add(a.sub(*c).unit().mul(rr)),
                b: c.add(b.sub(*c).unit().mul(rr)),
                c: *c,
                r: rr.abs(),
                sweep: *sweep,
                large: *large,
            }
        }
        Seg::Cubic { a, c1, c2, b } => {
            let n0 = c1.sub(*a).unit().left().mul(side * h);
            let n1 = b.sub(*c2).unit().left().mul(side * h);
            Seg::Cubic { a: a.add(n0), c1: c1.add(n0), c2: c2.add(n1), b: b.add(n1) }
        }
    }
}

fn set_end(g: &mut Seg, p: P) {
    match g {
        Seg::Line { b, .. } | Seg::Arc { b, .. } | Seg::Cubic { b, .. } => *b = p,
    }
}

// Join offset runs: lines meet at their mitre, tangent runs already touch,
// anything else is bridged.
fn join_offsets(segs: &[Seg], closed: bool) -> Vec<Seg> {
    let mut out: Vec<Seg> = segs.to_vec();
    let n = out.len();
    let joints = if closed { n } else { n.saturating_sub(1) };
    let mut bridges: Vec<(usize, Seg)> = Vec::new();
    for k in 0..joints {
        let j = (k + 1) % n;
        let e = out[k].end();
        let s = out[j].start();
        if e.near(s) {
            continue;
        }
        let mitre = match (&out[k], &out[j]) {
            (Seg::Line { a: a1, b: b1 }, Seg::Line { a: a2, b: b2 }) => line_x(*a1, b1.sub(*a1), *a2, b2.sub(*a2)),
            _ => None,
        };
        match mitre {
            Some(x) => {
                set_end(&mut out[k], x);
                out[j].set_start(x);
            }
            None => bridges.push((k, Seg::Line { a: e, b: s })),
        }
    }
    for (k, br) in bridges.into_iter().rev() {
        out.insert(k + 1, br);
    }
    out
}

impl Shape {
    // A wall: its drawn centreline thickened to `t`, as a closed outline.
    pub fn thickened(&self, t: f64) -> Shape {
        let h = t / 2.0;
        let mut subs = Vec::new();
        for s in &self.subs {
            let mut segs = s.segs.clone();
            if s.closed && !s.end().near(s.start) {
                segs.push(Seg::Line { a: s.end(), b: s.start });
            }
            if segs.is_empty() {
                continue;
            }
            let left: Vec<Seg> = segs.iter().map(|g| offset_seg(g, 1.0, h)).collect();
            let right: Vec<Seg> = segs.iter().map(|g| offset_seg(g, -1.0, h)).collect();
            let left = join_offsets(&left, s.closed);
            let right = join_offsets(&right, s.closed);
            if s.closed {
                let mut l = Sub::new(left[0].start());
                for g in &left {
                    l.push(g.clone(), None);
                }
                l.closed = true;
                subs.push(l);
                let mut r = Sub::new(right.last().unwrap().end());
                for g in right.iter().rev() {
                    r.push(g.reversed(), None);
                }
                r.closed = true;
                subs.push(r);
            } else {
                let mut o = Sub::new(left[0].start());
                for g in &left {
                    o.push(g.clone(), None);
                }
                let le = left.last().unwrap().end();
                let re = right.last().unwrap().end();
                o.push(Seg::Line { a: le, b: re }, None);
                for g in right.iter().rev() {
                    o.push(g.reversed(), None);
                }
                o.push(Seg::Line { a: right[0].start(), b: left[0].start() }, None);
                o.closed = true;
                subs.push(o);
            }
        }
        Shape { subs, points: self.points.clone() }
    }
}
