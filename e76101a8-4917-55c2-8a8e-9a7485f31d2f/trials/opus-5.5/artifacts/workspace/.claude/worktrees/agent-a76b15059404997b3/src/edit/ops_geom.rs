//! What corner, split and fillet share: plane geometry, walls (their lines, thickness, the doors
//! and windows they host, the walls joined to them) and reading their parameters as the original
//! reads them.

use super::common::r3;
use crate::json::Value;
use crate::project::Project;

pub type P = [f64; 2];

pub fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
}
pub fn mul(a: P, k: f64) -> P {
    [a[0] * k, a[1] * k]
}
pub fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
pub fn cross(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
pub fn norm(a: P) -> f64 {
    a[0].hypot(a[1])
}
pub fn dist(a: P, b: P) -> f64 {
    norm(sub(a, b))
}
pub fn unit(a: P) -> P {
    let l = norm(a);
    [a[0] / l, a[1] / l]
}
/// A direction as the original normalizes one: times the reciprocal of its length.
pub fn dir(a: P) -> P {
    let k = 1.0 / norm(a);
    [a[0] * k, a[1] * k]
}
pub fn r3p(p: P) -> P {
    [r3(p[0]), r3(p[1])]
}

/// Where the lines through a, b and through c, d cross: the parameter along a-b (0 at a, 1 at
/// b); None when they're parallel.
pub fn line_cross_t(a: P, b: P, c: P, d: P) -> Option<f64> {
    let r = sub(b, a);
    let s = sub(d, c);
    let den = cross(r, s);
    let scale = norm(r) * norm(s);
    if !(den.abs() > 1e-12 * scale) {
        return None;
    }
    Some(cross(sub(c, a), s) / den)
}

/// Where the lines through a, b and through c, d cross.
pub fn line_cross(a: P, b: P, c: P, d: P) -> Option<P> {
    let t = line_cross_t(a, b, c, d)?;
    Some(add(a, mul(sub(b, a), t)))
}

/// How far p is from the segment a-b.
pub fn seg_dist(p: P, a: P, b: P) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    dist(p, add(a, mul(d, t)))
}

/// A number as the original's messages show one (Rust's Display).
pub fn num(x: f64) -> String {
    format!("{}", x)
}

/// A point as the original's messages show one: `[x, y]`.
pub fn pt_text(p: P) -> String {
    format!("[{}, {}]", p[0], p[1])
}

// ---------------------------------------------------------------- parameters

/// A GUID as the original matches one in parameters: 8-4-4-4-12 hex digits, any case, braces or
/// not, blanks round it; lowercased.
pub fn guid_of_text(s: &str) -> Option<String> {
    super::common::strict_guid(s)
}

/// The parameters with every text that is a library entry's GUID replaced by the entry's name,
/// as the original reads a command's parameters (so its messages show the name).
pub fn lib_names(pr: &Project, v: &Value) -> Value {
    match v {
        Value::Str(s) => {
            if let Some(g) = guid_of_text(s) {
                if pr.find_guid(&g).is_none() {
                    if let Some(n) = pr.lib_name(&g) {
                        return Value::Str(n);
                    }
                }
            }
            v.clone()
        }
        Value::Arr(a) => Value::Arr(a.iter().map(|x| lib_names(pr, x)).collect()),
        Value::Obj(m) => {
            let mut out = m.clone();
            for (_, x) in out.items.iter_mut() {
                *x = lib_names(pr, x);
            }
            Value::Obj(out)
        }
        _ => v.clone(),
    }
}

// ---------------------------------------------------------------- walls

pub fn pt_of(v: Option<&Value>) -> P {
    super::common::pt(v).unwrap_or([0.0, 0.0])
}

/// A wall's location line: its start, its end and its arc (degrees, 0 for a straight one).
pub fn wall_line(e: &Value) -> (P, P, f64) {
    let a = pt_of(e.get("start"));
    let b = pt_of(e.get("end"));
    let arc = e.get("arc").and_then(|x| x.as_f64()).unwrap_or(0.0);
    (a, b, arc)
}

pub fn set_pt(e: &mut Value, k: &str, p: P) {
    e.set(k, Value::Arr(vec![Value::f(p[0]), Value::f(p[1])]));
}

/// The fields of a wall, in the order the original writes them.
pub const WALL_ORDER: &[&str] = &[
    "guid",
    "category",
    "type",
    "level",
    "start",
    "end",
    "top_level",
    "height",
    "base_offset",
    "top_offset",
    "arc",
    "location",
    "attach_top",
    "attach_base",
    "room_bounding",
    "params",
];

/// Sets a field of an element where the struct's order puts it (`order`), keeping it in place if
/// it is there.
pub fn set_ordered(e: &mut Value, order: &[&str], k: &str, v: Value) {
    let Value::Obj(m) = e else { return };
    if m.contains(k) {
        m.insert(k, v);
        return;
    }
    let rank = |key: &str| order.iter().position(|o| *o == key);
    let r = rank(k).unwrap_or(usize::MAX);
    let pos = m
        .items
        .iter()
        .position(|(kk, _)| rank(kk).map(|x| x > r).unwrap_or(false))
        .unwrap_or(m.items.len());
    m.items.insert(pos, (k.to_string(), v));
}

/// The name of the library entry a field names (by GUID), or the text itself.
pub fn lib_ref_name(pr: &Project, e: &Value, k: &str) -> Option<String> {
    let g = e.get(k)?.as_str()?;
    Some(pr.lib_name(g).unwrap_or_else(|| g.to_string()))
}

/// A type's entry in the project's `types` section.
pub fn type_entry<'a>(pr: &'a Project, kind: &str, name: &str) -> Option<&'a Value> {
    pr.section("types")?.get(kind)?.get(name)
}

/// A wall's thickness, from its type.
pub fn wall_thickness(pr: &Project, e: &Value) -> f64 {
    let Some(name) = lib_ref_name(pr, e, "type") else { return 200.0 };
    let Some(t) = type_entry(pr, "wall", &name) else { return 200.0 };
    if let Some(x) = t.get("thickness").and_then(|x| x.as_f64()) {
        return x;
    }
    if let Some(ls) = t.get("layers").and_then(|x| x.as_arr()) {
        return ls.iter().filter_map(|l| l.get("thickness").and_then(|x| x.as_f64())).sum();
    }
    200.0
}

/// How far a wall's centre line is from its location line, to the left of its start to its end
/// (its exterior side): nothing for a wall on its centre line; for one on a face or on its core,
/// as its type's layers (from the exterior in; the core its structure layers) put that line.
pub fn centre_offset(pr: &Project, e: &Value) -> f64 {
    let t = wall_thickness(pr, e);
    let loc = e.get("location").and_then(|l| l.as_str()).unwrap_or("centre");
    // the core, from the exterior face
    let (mut c0, mut c1) = (0.0, t);
    if let Some(name) = lib_ref_name(pr, e, "type") {
        if let Some(ls) = type_entry(pr, "wall", &name).and_then(|ty| ty.get("layers")).and_then(|x| x.as_arr()) {
            let mut at = 0.0;
            let mut first: Option<f64> = None;
            let mut last = 0.0;
            for l in ls {
                let th = l.get("thickness").and_then(|x| x.as_f64()).unwrap_or(0.0);
                if l.get("function").and_then(|f| f.as_str()) == Some("structure") {
                    if first.is_none() {
                        first = Some(at);
                    }
                    last = at + th;
                }
                at += th;
            }
            if let Some(f) = first {
                c0 = f;
                c1 = last;
            }
        }
    }
    // where the location line is, from the exterior face
    let line = match loc {
        "exterior-finish" => 0.0,
        "interior-finish" => t,
        "core-centre" => (c0 + c1) / 2.0,
        "exterior-core" => c0,
        "interior-core" => c1,
        _ => t / 2.0,
    };
    line - t / 2.0
}

/// A family parameter's value for a type of it: the type's own, else the family's.
fn family_value(pr: &Project, family: &str, typ: &str, param: &str) -> Option<f64> {
    let f = pr.section("families")?.get(family)?;
    if let Some(v) = f.get("types").and_then(|t| t.get(typ)).and_then(|t| t.get(param)).and_then(|x| x.as_f64()) {
        return Some(v);
    }
    let ps = f.get("parameters")?.as_arr()?;
    for p in ps {
        if p.get("name").and_then(|n| n.as_str()) == Some(param) {
            return p.get("value").and_then(|x| x.as_f64());
        }
    }
    None
}

/// A door's or a window's width: its family type's `Width`, or its type's.
pub fn opening_width(pr: &Project, e: &Value) -> f64 {
    let kind = super::common::cat_of(e).to_string();
    if let Some(fam) = lib_ref_name(pr, e, "family") {
        let typ = lib_ref_name(pr, e, "type").unwrap_or_default();
        let tname = typ.strip_prefix(&format!("{}: ", fam)).unwrap_or(&typ).to_string();
        if let Some(w) = family_value(pr, &fam, &tname, "Width") {
            return w;
        }
    }
    if let Some(name) = lib_ref_name(pr, e, "type") {
        if let Some(w) = type_entry(pr, &kind, &name).and_then(|t| t.get("width")).and_then(|x| x.as_f64()) {
            return w;
        }
    }
    900.0
}

/// The doors and windows a wall hosts, by id.
pub fn openings(pr: &Project, wall: u64) -> Vec<u64> {
    let Some(g) = pr.guid_of(wall) else { return Vec::new() };
    pr.elements
        .iter()
        .filter(|(_, e)| {
            matches!(super::common::cat_of(e), "door" | "window") && e.get("host").and_then(|h| h.as_str()) == Some(g.as_str())
        })
        .map(|(id, _)| *id)
        .collect()
}

pub fn offset_of(e: &Value) -> f64 {
    e.get("offset").and_then(|x| x.as_f64()).unwrap_or(0.0)
}

// ---------------------------------------------------------------- arcs

/// An arc from its ends and its turn in degrees (counter-clockwise positive): its centre, its
/// radius, the angle of its start from the centre and its sweep, in radians.
#[derive(Clone, Copy, Debug)]
pub struct Arc {
    pub c: P,
    pub r: f64,
    pub a0: f64,
    pub sweep: f64,
}

pub fn arc_of(a: P, b: P, deg: f64) -> Arc {
    let t = deg.to_radians();
    let ch = sub(b, a);
    let l = norm(ch);
    let r = l / 2.0 / (t / 2.0).sin().abs();
    let m = mul(add(a, b), 0.5);
    // the centre lies to the left of the chord for a counter-clockwise arc
    let k = 1.0 / l;
    let n = [-ch[1] * k, ch[0] * k];
    let d = l / 2.0 / (t / 2.0).tan();
    let c = add(m, mul(n, d));
    let a0 = (a[1] - c[1]).atan2(a[0] - c[0]);
    Arc { c, r, a0, sweep: t }
}

impl Arc {
    pub fn at(&self, ang: f64) -> P {
        [self.c[0] + self.r * ang.cos(), self.c[1] + self.r * ang.sin()]
    }
    pub fn len(&self) -> f64 {
        self.r * self.sweep.abs()
    }
}

/// A point on a wall's line `s` mm along it from its start (along its arc, for a curved one).
pub fn along(line: (P, P, f64), s: f64) -> P {
    let (a, b, deg) = line;
    if deg == 0.0 {
        return add(a, mul(dir(sub(b, a)), s));
    }
    let arc = arc_of(a, b, deg);
    let ang = arc.a0 + arc.sweep.signum() * s / arc.r;
    arc.at(ang)
}

/// How far along a wall's line (from its start) the point nearest p is.
pub fn station(line: (P, P, f64), p: P) -> f64 {
    let (a, b, deg) = line;
    if deg == 0.0 {
        return dot(sub(p, a), dir(sub(b, a)));
    }
    let arc = arc_of(a, b, deg);
    let ang = (p[1] - arc.c[1]).atan2(p[0] - arc.c[0]);
    let mut da = (ang - arc.a0) * arc.sweep.signum();
    let two = std::f64::consts::PI * 2.0;
    while da < -std::f64::consts::PI {
        da += two;
    }
    while da > std::f64::consts::PI * 1.5 {
        da -= two;
    }
    da * arc.r
}

/// Doors and windows of a wall whose line changed from `old` to `new`, given offsets that keep
/// them where they stand in plan.
pub fn reoffset_openings(pr: &mut Project, wall: u64, old: (P, P, f64), new: (P, P, f64)) {
    if old == new {
        return;
    }
    for id in openings(pr, wall) {
        let off = offset_of(pr.el(id).unwrap());
        let at = along(old, off);
        let no = station(new, at);
        if no != off {
            pr.el_mut(id).unwrap().set("offset", Value::f(no));
        }
    }
}

// ---------------------------------------------------------------- joined walls

/// Walls joined to a wall whose ends moved (`old` to `new`, a straight wall that keeps its line)
/// follow it: an end within 1 mm of one of its ends goes to where that end is now; an end within
/// 1 mm of its line goes to where its own line crosses the wall's (or, running along it, moves as
/// the wall's end did). Walls of its level only; their doors and windows stay where they stand.
pub fn follow_joins(pr: &mut Project, wall: u64, old: (P, P), new: (P, P)) {
    let level = pr.el(wall).and_then(|e| e.get("level")).cloned();
    let ids: Vec<u64> = pr
        .elements
        .iter()
        .filter(|(id, e)| **id != wall && super::common::cat_of(e) == "wall" && e.get("level").cloned() == level)
        .map(|(id, _)| *id)
        .collect();
    let moved = if new.1 != old.1 { sub(new.1, old.1) } else { sub(new.0, old.0) };
    for id in ids {
        let e = pr.el(id).unwrap();
        let before = wall_line(e);
        let mut line = before;
        for k in 0..2 {
            let p = if k == 0 { line.0 } else { line.1 };
            let q = if k == 0 { line.1 } else { line.0 };
            let np = if dist(p, old.0) <= 1.0 {
                new.0
            } else if dist(p, old.1) <= 1.0 {
                new.1
            } else if seg_dist(p, old.0, old.1) <= 1.0 {
                if line.2 == 0.0 {
                    match line_cross(q, p, new.0, new.1) {
                        Some(x) => r3p(x),
                        None => r3p(add(p, moved)),
                    }
                } else {
                    continue;
                }
            } else {
                continue;
            };
            if k == 0 {
                line.0 = np;
            } else {
                line.1 = np;
            }
        }
        if line != before {
            let e = pr.el_mut(id).unwrap();
            if line.0 != before.0 {
                set_pt(e, "start", line.0);
            }
            if line.1 != before.1 {
                set_pt(e, "end", line.1);
            }
            reoffset_openings(pr, id, before, line);
        }
    }
}
