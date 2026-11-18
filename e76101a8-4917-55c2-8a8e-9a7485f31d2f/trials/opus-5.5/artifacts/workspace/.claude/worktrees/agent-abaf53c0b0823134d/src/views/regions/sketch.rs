//! A sketch's lines as a command takes them (`filled_region`'s `sketch`), and what they close
//! into: loops joined end to end within 1 mm, outlines and their holes, or every problem with
//! them (as ARCH's `sketch` command solves one; this is the stand-in the regions use).

use super::curve::{self, Shape, P, REACH};
use crate::json::{Map, Value};

pub type R<T> = Result<T, String>;

/// How far apart two ends may be and still meet.
pub const JOIN: f64 = 1.0;
/// The most chords a sketch is solved with.
pub const MAX_PIECES: usize = 200_000;
/// The most problems a message lists.
const MAX_LISTED: usize = 5;

pub const LIST_FORM: &str = "`sketch` is a list of lines, each [[x,y],[x,y]], an arc [[x,y],[x,y],[x,y]] (its ends, then a point it passes through) or an object: `id?` and a curve's fields, `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

pub const A_LINE_IS: &str = "a line is `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

/// A line of a sketch as given: its id (an existing line's), its own line style's name, and its
/// curve.
#[derive(Clone, Debug)]
pub struct Line {
    pub id: Option<u64>,
    pub style: Option<String>,
    pub shape: Shape,
}

// ---------------------------------------------------------------- reading, as serde does

const NO_MATCH: &str = "data did not match any variant of untagged enum Given";

fn p2(v: &Value) -> Option<P> {
    let a = v.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

fn opt<T>(v: Option<&Value>, f: impl Fn(&Value) -> Option<T>) -> Result<Option<T>, ()> {
    match v {
        None | Some(Value::Null) => Ok(None),
        Some(x) => f(x).map(Some).ok_or(()),
    }
}

fn p2s(v: &Value) -> Option<Vec<P>> {
    v.as_arr()?.iter().map(p2).collect()
}

fn f64s(v: &Value) -> Option<Vec<f64>> {
    v.as_arr()?.iter().map(|x| x.as_f64()).collect()
}

/// A GUID as the uuid crate reads one (hyphenated, plain, braced or a urn).
fn is_uuid(s: &str) -> bool {
    let t = s.strip_prefix("urn:uuid:").unwrap_or(s);
    let t = if t.starts_with('{') && t.ends_with('}') && t.len() >= 2 { &t[1..t.len() - 1] } else { t };
    let hex = |c: char| c.is_ascii_hexdigit();
    if t.len() == 32 {
        return t.chars().all(hex);
    }
    if t.len() == 36 {
        let b = t.as_bytes();
        return [8, 13, 18, 23].iter().all(|i| b[*i] == b'-')
            && t.chars().enumerate().all(|(i, c)| [8, 13, 18, 23].contains(&i) || hex(c));
    }
    false
}

/// The object form's fields, as given.
#[derive(Default)]
struct Given {
    id: Option<u64>,
    style: Option<String>,
    start: Option<P>,
    end: Option<P>,
    through: Option<P>,
    arc: Option<f64>,
    points: Option<Vec<P>>,
    arcs: Option<Vec<f64>>,
    closed: Option<bool>,
    centre: Option<P>,
    radius: Option<f64>,
    radii: Option<P>,
    angle: Option<f64>,
    span: Option<P>,
    control: Option<Vec<P>>,
    knots: Option<Vec<f64>>,
    fit: Option<Vec<P>>,
    start_tangent: Option<P>,
    end_tangent: Option<P>,
}

const FIELDS: &[&str] = &[
    "start", "end", "through", "arc", "points", "arcs", "closed", "centre", "radius", "radii", "angle", "span", "control",
    "knots", "fit", "start_tangent", "end_tangent",
];

fn given_of(m: &Map) -> Result<Given, ()> {
    let mut g = Given::default();
    for (k, v) in &m.items {
        match k.as_str() {
            "id" => {
                g.id = Some(match v {
                    Value::Num(crate::json::Num::U(u)) => *u,
                    _ => return Err(()),
                })
            }
            "guid" => match v {
                Value::Str(s) if is_uuid(s) => {}
                _ => return Err(()),
            },
            "style" => g.style = opt(Some(v), |x| x.as_str().map(|s| s.to_string()))?,
            "start" => g.start = opt(Some(v), p2)?,
            "end" => g.end = opt(Some(v), p2)?,
            "through" => g.through = opt(Some(v), p2)?,
            "arc" => g.arc = opt(Some(v), |x| x.as_f64())?,
            "points" => g.points = opt(Some(v), p2s)?,
            "arcs" => g.arcs = opt(Some(v), f64s)?,
            "closed" => {
                g.closed = Some(match v {
                    Value::Bool(b) => *b,
                    _ => return Err(()),
                })
            }
            "centre" => g.centre = opt(Some(v), p2)?,
            "radius" => g.radius = opt(Some(v), |x| x.as_f64())?,
            "radii" => g.radii = opt(Some(v), p2)?,
            "angle" => g.angle = opt(Some(v), |x| x.as_f64())?,
            "span" => g.span = opt(Some(v), p2)?,
            "control" => g.control = opt(Some(v), p2s)?,
            "knots" => g.knots = opt(Some(v), f64s)?,
            "fit" => g.fit = opt(Some(v), p2s)?,
            "start_tangent" => g.start_tangent = opt(Some(v), p2)?,
            "end_tangent" => g.end_tangent = opt(Some(v), p2)?,
            _ => return Err(()),
        }
    }
    Ok(g)
}

impl Given {
    fn has(&self, k: &str) -> bool {
        match k {
            "start" => self.start.is_some(),
            "end" => self.end.is_some(),
            "through" => self.through.is_some(),
            "arc" => self.arc.is_some(),
            "points" => self.points.is_some(),
            "arcs" => self.arcs.is_some(),
            "closed" => self.closed.is_some(),
            "centre" => self.centre.is_some(),
            "radius" => self.radius.is_some(),
            "radii" => self.radii.is_some(),
            "angle" => self.angle.is_some(),
            "span" => self.span.is_some(),
            "control" => self.control.is_some(),
            "knots" => self.knots.is_some(),
            "fit" => self.fit.is_some(),
            "start_tangent" => self.start_tangent.is_some(),
            "end_tangent" => self.end_tangent.is_some(),
            _ => false,
        }
    }

    /// The curve the fields make, or why they make none.
    fn shape(&self) -> R<Shape> {
        let groups: &[(&[&str], bool)] = &[
            (&["start", "end", "through", "arc"], self.start.is_some() && self.end.is_some()),
            (&["points", "arcs", "closed"], self.points.is_some()),
            (&["centre", "radius"], self.centre.is_some() && self.radius.is_some()),
            (&["centre", "radii", "angle", "span"], self.centre.is_some() && self.radii.is_some()),
            (&["control", "knots"], self.control.is_some()),
            (&["fit", "start_tangent", "end_tangent"], self.fit.is_some()),
        ];
        let Some((i, (group, _))) = groups.iter().enumerate().find(|(_, (_, ok))| *ok) else {
            return Err(A_LINE_IS.to_string());
        };
        for f in FIELDS {
            if self.has(f) && !group.contains(f) {
                return Err(format!("`{}` doesn't go with the {} given: {}", f, group.join(", "), A_LINE_IS));
            }
        }
        Ok(match i {
            0 => {
                let a = self.start.unwrap();
                let b = self.end.unwrap();
                if self.through.is_some() && self.arc.is_some() {
                    return Err("give an arc's `through` point or its `arc` turn, not both".to_string());
                }
                if let Some(m) = self.through {
                    match curve::turn_through(a, b, m) {
                        Some(t) => Shape::Arc(a, b, t),
                        None => Shape::Line(a, b),
                    }
                } else {
                    match self.arc {
                        Some(t) if t != 0.0 => Shape::Arc(a, b, t),
                        _ => Shape::Line(a, b),
                    }
                }
            }
            1 => Shape::Poly(self.points.clone().unwrap(), self.arcs.clone().unwrap_or_default(), self.closed.unwrap_or(false)),
            2 => Shape::Circle(self.centre.unwrap(), self.radius.unwrap()),
            3 => Shape::Ellipse(self.centre.unwrap(), self.radii.unwrap(), self.angle.unwrap_or(0.0), self.span),
            4 => Shape::Spline(self.control.clone().unwrap(), self.knots.clone()),
            _ => Shape::Fit(self.fit.clone().unwrap(), self.start_tangent, self.end_tangent),
        })
    }
}

/// The kind of value serde names in an "invalid type" error.
fn kind(v: &Value) -> String {
    v.kind_name()
}

/// A sketch's lines from a command's parameter, with the original's errors (`cmd: …`); `ids`
/// are the lines' ids the sketch already has (none for a new one).
pub fn parse(cmd: &str, key: &str, v: Option<&Value>, ids: &[u64]) -> R<Vec<Line>> {
    let form = LIST_FORM.replacen("`sketch`", &format!("`{}`", key), 1);
    let a = match v {
        None | Some(Value::Null) => return Err(format!("{}: `{}`, its outlines' lines, is required", cmd, key)),
        Some(Value::Arr(a)) => a,
        Some(x) => return Err(format!("{}: {}: invalid type: {}, expected a sequence", cmd, form, kind(x))),
    };
    // first as serde reads the list: each a line of two points, an arc of three or an object
    let mut given: Vec<Result<Given, (P, P, Option<P>)>> = Vec::new();
    for x in a {
        match x {
            Value::Arr(ps) => {
                let q: Option<Vec<P>> = ps.iter().map(p2).collect();
                match q {
                    Some(q) if q.len() == 2 => given.push(Err((q[0], q[1], None))),
                    Some(q) if q.len() == 3 => given.push(Err((q[0], q[1], Some(q[2])))),
                    _ => {
                        // the object's form as serde reads a struct from a sequence: its id,
                        // its GUID and its style, and no curve
                        let uint = |v: &Value| matches!(v, Value::Num(crate::json::Num::U(_)));
                        let ok = ps.len() <= 3
                            && ps.first().map_or(true, uint)
                            && ps.get(1).map_or(true, |v| uint(v) || matches!(v, Value::Str(s) if is_uuid(s)))
                            && ps.get(2).map_or(true, |v| matches!(v, Value::Null | Value::Str(_)));
                        if !ok {
                            return Err(format!("{}: {}: {}", cmd, form, NO_MATCH));
                        }
                        let g = Given { id: ps.first().and_then(|v| v.as_u64()), ..Default::default() };
                        given.push(Ok(g));
                    }
                }
            }
            Value::Obj(m) => match given_of(m) {
                Ok(g) => given.push(Ok(g)),
                Err(()) => return Err(format!("{}: {}: {}", cmd, form, NO_MATCH)),
            },
            _ => return Err(format!("{}: {}: {}", cmd, form, NO_MATCH)),
        }
    }
    let mut out = Vec::new();
    for (i, g) in given.into_iter().enumerate() {
        match g {
            Err((a, b, None)) => out.push(Line { id: None, style: None, shape: Shape::Line(a, b) }),
            Err((a, b, Some(m))) => {
                let shape = match curve::turn_through(a, b, m) {
                    Some(t) => Shape::Arc(a, b, t),
                    None => Shape::Line(a, b),
                };
                out.push(Line { id: None, style: None, shape })
            }
            Ok(g) => {
                let shape = g.shape().map_err(|e| format!("{}: `{}` line {}: {}", cmd, key, i, e))?;
                if let Some(id) = g.id {
                    if !ids.contains(&id) {
                        return Err(format!(
                            "{}: `{}` line {}: {} isn't a line of this sketch; leave `id` out for a new one",
                            cmd, key, i, id
                        ));
                    }
                }
                out.push(Line { id: g.id, style: g.style.clone(), shape });
            }
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------- the saved form

fn pv(p: P) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

/// A curve's fields as a file holds them (a turn of 0, no arcs, open, an angle of 0 left out).
pub fn shape_fields(s: &Shape, m: &mut Map) {
    match s {
        Shape::Line(a, b) => {
            m.insert("start", pv(*a));
            m.insert("end", pv(*b));
        }
        Shape::Arc(a, b, t) => {
            m.insert("start", pv(*a));
            m.insert("end", pv(*b));
            m.insert("arc", Value::f(*t));
        }
        Shape::Poly(p, arcs, closed) => {
            m.insert("points", Value::Arr(p.iter().map(|q| pv(*q)).collect()));
            if arcs.iter().any(|x| *x != 0.0) {
                m.insert("arcs", Value::Arr(arcs.iter().map(|x| Value::f(*x)).collect()));
            }
            if *closed {
                m.insert("closed", Value::Bool(true));
            }
        }
        Shape::Circle(c, r) => {
            m.insert("centre", pv(*c));
            m.insert("radius", Value::f(*r));
        }
        Shape::Ellipse(c, r, angle, span) => {
            m.insert("centre", pv(*c));
            m.insert("radii", pv(*r));
            if *angle != 0.0 {
                m.insert("angle", Value::f(*angle));
            }
            if let Some(sp) = span {
                m.insert("span", pv(*sp));
            }
        }
        Shape::Spline(c, k) => {
            m.insert("control", Value::Arr(c.iter().map(|q| pv(*q)).collect()));
            if let Some(k) = k {
                m.insert("knots", Value::Arr(k.iter().map(|x| Value::f(*x)).collect()));
            }
        }
        Shape::Fit(f, t0, t1) => {
            m.insert("fit", Value::Arr(f.iter().map(|q| pv(*q)).collect()));
            if let Some(t) = t0 {
                m.insert("start_tangent", pv(*t));
            }
            if let Some(t) = t1 {
                m.insert("end_tangent", pv(*t));
            }
        }
    }
}

// ---------------------------------------------------------------- what can be drawn

fn disp(x: f64) -> String {
    format!("{}", x)
}

/// A point as messages give it, to the nearest mm ([0, 2], [500, -0]).
pub fn at(p: P) -> String {
    format!("[{}, {}]", disp(p[0].round()), disp(p[1].round()))
}

fn same(a: P, b: P) -> bool {
    a[0] == b[0] && a[1] == b[1]
}

fn dist(a: P, b: P) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2)).sqrt()
}

fn within(p: P) -> bool {
    p[0].is_finite() && p[1].is_finite() && p[0].abs() <= REACH && p[1].abs() <= REACH
}

/// Whether every point that makes the curve, and how far it reaches, lies within the model.
fn reaches_within(s: &Shape) -> bool {
    match s {
        Shape::Line(a, b) => within(*a) && within(*b),
        Shape::Arc(a, b, t) => {
            if !(within(*a) && within(*b)) {
                return false;
            }
            match curve::arc_centre(*a, *b, *t) {
                Some((c, r)) => r.is_finite() && within([c[0].abs() + r, c[1].abs() + r]),
                None => true,
            }
        }
        Shape::Poly(p, arcs, closed) => {
            if !p.iter().all(|q| within(*q)) {
                return false;
            }
            let n = p.len();
            let segs = if *closed { n } else { n.saturating_sub(1) };
            for i in 0..segs {
                let t = arcs.get(i).copied().unwrap_or(0.0);
                if t != 0.0 {
                    if let Some((c, r)) = curve::arc_centre(p[i], p[(i + 1) % n], t) {
                        if !(r.is_finite() && within([c[0].abs() + r, c[1].abs() + r])) {
                            return false;
                        }
                    }
                }
            }
            true
        }
        Shape::Circle(c, r) => within(*c) && r.is_finite() && within([c[0].abs() + r.abs(), c[1].abs() + r.abs()]),
        Shape::Ellipse(c, radii, _, _) => {
            let m = radii[0].abs().max(radii[1].abs());
            within(*c) && m.is_finite() && within([c[0].abs() + m, c[1].abs() + m])
        }
        Shape::Spline(c, _) => c.iter().all(|q| within(*q)),
        Shape::Fit(f, _, _) => f.iter().all(|q| within(*q)),
    }
}

fn radius_ok(r: f64) -> bool {
    r.abs() > 1.0 && r.abs() <= REACH
}

/// Why a curve can't be drawn (as `detail_line` says it), if it can't.
pub fn undrawable(s: &Shape) -> Option<String> {
    let arc_bad = |t: f64| t.abs() >= 360.0 || !t.is_finite();
    let arc_msg = |t: f64| format!("an arc turns {}°; it turns less than a whole circle, either way", disp(t));
    match s {
        Shape::Line(a, b) => {
            if same(*a, *b) {
                return Some("two points one after another are the same; a line runs between points apart".into());
            }
        }
        Shape::Arc(a, b, t) => {
            if same(*a, *b) {
                return Some("two points one after another are the same; a line runs between points apart".into());
            }
            if arc_bad(*t) {
                return Some(arc_msg(*t));
            }
        }
        Shape::Poly(p, arcs, closed) => {
            if p.len() < 2 {
                return Some(format!("a line needs two points or more, not {}", p.len()));
            }
            let n = p.len();
            for i in 0..n - 1 {
                if same(p[i], p[i + 1]) {
                    return Some("two points one after another are the same; a line runs between points apart".into());
                }
            }
            if *closed && same(p[n - 1], p[0]) {
                return Some("two points one after another are the same; a line runs between points apart".into());
            }
            let segs = if *closed { n } else { n - 1 };
            if arcs.iter().any(|t| *t != 0.0) && arcs.len() != segs {
                return Some(format!("`arcs` gives one turn for each of its {} segments, not {}", segs, arcs.len()));
            }
            for t in arcs {
                if arc_bad(*t) {
                    return Some(arc_msg(*t));
                }
            }
        }
        Shape::Circle(_, r) => {
            if !(*r > 1.0 && *r <= REACH) {
                return Some(format!("its radius is {} mm; it's more than 1 mm and at most 1000000000", disp(*r)));
            }
        }
        Shape::Ellipse(_, radii, _, span) => {
            if !radius_ok(radii[0]) {
                return Some(format!("its first radius is {} mm; it's more than 1 mm and at most 1000000000", disp(radii[0])));
            }
            if !radius_ok(radii[1]) {
                return Some(format!("its second radius is {} mm; it's more than 1 mm and at most 1000000000", disp(radii[1])));
            }
            if let Some(sp) = span {
                if sp[0] == sp[1] {
                    return Some(format!("its span from {}° to {}° is nothing; give two angles apart", disp(sp[0]), disp(sp[1])));
                }
            }
        }
        Shape::Spline(c, k) => {
            let n = c.len();
            if n < 2 {
                return Some(format!("a spline needs two control points or more, not {}", n));
            }
            if let Some(k) = k {
                let ok = (1..=5usize).any(|p| p < n && k.len() == n + p + 1);
                if !ok {
                    return Some(format!(
                        "a spline of {} control points has {} plus its degree plus one knots (degree 1 to 5, below {}), not {}",
                        n,
                        n,
                        n,
                        k.len()
                    ));
                }
                if k.windows(2).any(|w| w[1] < w[0]) || k.iter().any(|x| !x.is_finite()) {
                    return Some("its knots are numbers, each no less than the one before".into());
                }
            }
        }
        Shape::Fit(f, t0, t1) => {
            if f.len() < 2 {
                return Some(format!("a spline needs two points or more to pass through, not {}", f.len()));
            }
            for w in f.windows(2) {
                if same(w[0], w[1]) {
                    return Some("two points one after another are the same; a spline passes through points apart".into());
                }
            }
            for t in [t0, t1].into_iter().flatten() {
                if t[0] == 0.0 && t[1] == 0.0 {
                    return Some("a tangent is a direction [x, y], not nothing".into());
                }
            }
        }
    }
    None
}

/// A line's drawn points as the sketch takes them: each more than 1 mm on from the last kept,
/// its end kept in place of a last point within 1 mm of it.
pub fn thinned(pts: &[P]) -> Vec<P> {
    let n = pts.len();
    if n <= 2 {
        return pts.to_vec();
    }
    let mut out: Vec<P> = vec![pts[0]];
    for p in &pts[1..n - 1] {
        if dist(*p, *out.last().unwrap()) > JOIN {
            out.push(*p);
        }
    }
    let end = pts[n - 1];
    if out.len() > 1 && dist(end, *out.last().unwrap()) <= JOIN {
        out.pop();
    }
    out.push(end);
    out
}

/// A polyline's two points one after another less than 1 mm apart, if it has any.
fn close_points(s: &Shape) -> Option<String> {
    let Shape::Poly(p, _, closed) = s else { return None };
    let n = p.len();
    let segs = if *closed { n } else { n.saturating_sub(1) };
    for i in 0..segs {
        if dist(p[i], p[(i + 1) % n]) < JOIN {
            return Some(format!("it has two points less than 1 mm apart, at {}: draw them as one", at(p[i])));
        }
    }
    None
}

fn length(pts: &[P]) -> f64 {
    pts.windows(2).map(|w| dist(w[0], w[1])).sum()
}

// ---------------------------------------------------------------- solving

/// A region the sketch closes into: its outline (counter-clockwise) and holes (clockwise).
#[derive(Clone, Debug)]
pub struct Region {
    pub outline: Vec<P>,
    pub holes: Vec<Vec<P>>,
}

impl Region {
    /// Its area in mm², the holes taken out.
    pub fn area(&self) -> f64 {
        area(&self.outline).abs() - self.holes.iter().map(|h| area(h).abs()).sum::<f64>()
    }
}

pub fn area(p: &[P]) -> f64 {
    let n = p.len();
    if n < 3 {
        return 0.0;
    }
    let mut s = 0.0;
    for i in 0..n {
        let a = p[i];
        let b = p[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

/// The area of regions in m², to the hundredth, as replies give it.
pub fn area_m2(regions: &[Region]) -> f64 {
    let a: f64 = regions.iter().map(|r| r.area()).sum();
    let m = (a / 1e6 * 100.0).round() / 100.0;
    if m == 0.0 {
        0.0
    } else {
        m
    }
}

fn list_lines(ls: &[usize]) -> String {
    let names: Vec<String> = ls.iter().map(|i| format!("line {}", i)).collect();
    match names.len() {
        0 => String::new(),
        1 => names[0].clone(),
        n => format!("{} and {}", names[..n - 1].join(", "), names[n - 1]),
    }
}

/// The problems joined as a message gives them: the first five, and how many more.
fn joined(problems: &[String]) -> String {
    let mut s = problems.iter().take(MAX_LISTED).cloned().collect::<Vec<_>>().join("; ");
    if problems.len() > MAX_LISTED {
        s.push_str(&format!("; and {} more", problems.len() - MAX_LISTED));
    }
    s
}

#[derive(Clone, Copy)]
struct Seg {
    line: usize,
    /// Index of the chord within its line.
    k: usize,
    a: P,
    b: P,
    /// The nodes its ends are at.
    na: usize,
    nb: usize,
}

fn orient(a: P, b: P, c: P) -> f64 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}


/// How far a point lies from a chord.
fn seg_dist(p: P, q: &Seg) -> f64 {
    let d = [q.b[0] - q.a[0], q.b[1] - q.a[1]];
    let l2 = d[0] * d[0] + d[1] * d[1];
    if l2 == 0.0 {
        return dist(p, q.a);
    }
    let t = (((p[0] - q.a[0]) * d[0] + (p[1] - q.a[1]) * d[1]) / l2).clamp(0.0, 1.0);
    dist(p, [q.a[0] + d[0] * t, q.a[1] + d[1] * t])
}

fn near(p: P, q: &Seg) -> bool {
    seg_dist(p, q) <= JOIN + 1e-9
}

/// Whether two chords run along each other, within 1 mm: sharing an end, the other end of one
/// lies within 1 mm of the other; else both ends of one do.
fn overlap(s: &Seg, t: &Seg) -> bool {
    if !parallel(s, t) {
        return false;
    }
    let shared_a = s.na == t.na || s.na == t.nb;
    let shared_b = s.nb == t.na || s.nb == t.nb;
    if shared_a && shared_b {
        // the same two nodes: one chord back over the other
        return true;
    }
    if shared_a || shared_b {
        let sf = if shared_a { s.b } else { s.a };
        let tn = if s.na == t.na || s.nb == t.na { t.b } else { t.a };
        return near(sf, t) || near(tn, s);
    }
    (near(s.a, t) && near(s.b, t)) || (near(t.a, s) && near(t.b, s)) || collinear(s, t)
}

/// Whether two chords run within 5° of one direction.
fn parallel(s: &Seg, t: &Seg) -> bool {
    let u = [s.b[0] - s.a[0], s.b[1] - s.a[1]];
    let v = [t.b[0] - t.a[0], t.b[1] - t.a[1]];
    let cross = (u[0] * v[1] - u[1] * v[0]).abs();
    let dot = (u[0] * v[0] + u[1] * v[1]).abs();
    cross.atan2(dot).to_degrees() <= 5.0
}

/// Whether two chords lie on one line and share a length.
fn collinear(s: &Seg, t: &Seg) -> bool {
    let d = [s.b[0] - s.a[0], s.b[1] - s.a[1]];
    let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
    if l == 0.0 {
        return false;
    }
    let off = |p: P| orient(s.a, s.b, p).abs() / l;
    let tol = 1e-6 * (1.0 + l);
    if off(t.a) > tol || off(t.b) > tol {
        return false;
    }
    let u = [d[0] / l, d[1] / l];
    let proj = |p: P| (p[0] - s.a[0]) * u[0] + (p[1] - s.a[1]) * u[1];
    let (x, y) = (proj(t.a), proj(t.b));
    x.max(y).min(l) - x.min(y).max(0.0) > 1e-6
}

/// Where two chords cross or touch, if they do: an end of one within 1 mm of the other (the
/// later chord's first), else where they cross.
fn crossing(s: &Seg, t: &Seg) -> Option<P> {
    for p in [t.a, t.b] {
        if near(p, s) {
            return Some(p);
        }
    }
    for p in [s.a, s.b] {
        if near(p, t) {
            return Some(p);
        }
    }
    let d1 = orient(t.a, t.b, s.a);
    let d2 = orient(t.a, t.b, s.b);
    let d3 = orient(s.a, s.b, t.a);
    let d4 = orient(s.a, s.b, t.b);
    if (d1 > 0.0) != (d2 > 0.0) && (d3 > 0.0) != (d4 > 0.0) && d1 != d2 {
        let tt = d1 / (d1 - d2);
        return Some([s.a[0] + (s.b[0] - s.a[0]) * tt, s.a[1] + (s.b[1] - s.a[1]) * tt]);
    }
    None
}

/// Solves a sketch: the regions its lines close into, or the problems with them (the message
/// after "the sketch doesn't close into loops: ").
pub fn solve(lines: &[Line]) -> Result<Vec<Region>, String> {
    if lines.is_empty() {
        return Err("there are no lines: draw the outline".to_string());
    }
    // what can't be drawn at all
    let mut problems: Vec<String> = Vec::new();
    let mut drawn: Vec<Vec<P>> = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if !reaches_within(&l.shape) {
            problems.push(format!("line {} has a point that isn't a number within 1000000000 mm, or a curve reaching further", i));
            drawn.push(Vec::new());
            continue;
        }
        if let Some(why) = undrawable(&l.shape) {
            problems.push(format!("line {} isn't a line it can draw: {}", i, why));
            drawn.push(Vec::new());
            continue;
        }
        let d = thinned(&l.shape.drawn());
        if !d.iter().all(|p| within(*p)) {
            problems.push(format!("line {} has a point that isn't a number within 1000000000 mm, or a curve reaching further", i));
            drawn.push(Vec::new());
            continue;
        }
        if length(&d) <= 1.0 {
            problems.push(format!("line {} is 1 mm long or less", i));
            drawn.push(Vec::new());
            continue;
        }
        drawn.push(d);
    }
    if !problems.is_empty() {
        return Err(joined(&problems));
    }
    // then what draws but has points one after another less than 1 mm apart
    for (i, l) in lines.iter().enumerate() {
        if let Some(why) = close_points(&l.shape) {
            problems.push(format!("line {} isn't a line it can draw: {}", i, why));
        }
    }
    if !problems.is_empty() {
        return Err(joined(&problems));
    }
    let pieces: usize = drawn.iter().map(|d| d.len().saturating_sub(1)).sum();
    if pieces > MAX_PIECES {
        return Err(format!(
            "its lines are drawn as {} straight pieces (arcs, circles and curves are cut into chords), more than {}: draw fewer, or smaller",
            pieces, MAX_PIECES
        ));
    }
    // the nodes: each line's points, joined where they lie within 1 mm of one already met
    let mut nodes: Vec<P> = Vec::new();
    let mut grid: std::collections::HashMap<(i64, i64), Vec<usize>> = std::collections::HashMap::new();
    let cell = |p: P| ((p[0] / JOIN).floor() as i64, (p[1] / JOIN).floor() as i64);
    let mut node_of = |p: P, nodes: &mut Vec<P>| -> usize {
        let (cx, cy) = cell(p);
        let mut best: Option<usize> = None;
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(v) = grid.get(&(cx + dx, cy + dy)) {
                    for &n in v {
                        if dist(nodes[n], p) <= JOIN && best.map_or(true, |b| n < b) {
                            best = Some(n);
                        }
                    }
                }
            }
        }
        if let Some(b) = best {
            return b;
        }
        nodes.push(p);
        let id = nodes.len() - 1;
        grid.entry((cx, cy)).or_default().push(id);
        id
    };
    let mut segs: Vec<Seg> = Vec::new();
    // per line, the node of each drawn point
    let mut line_nodes: Vec<Vec<usize>> = Vec::new();
    for (i, d) in drawn.iter().enumerate() {
        let closed = lines[i].shape.is_closed();
        let mut ns: Vec<usize> = Vec::new();
        let m = if closed { d.len() - 1 } else { d.len() };
        for p in &d[..m] {
            ns.push(node_of(*p, &mut nodes));
        }
        if closed {
            ns.push(ns[0]);
        }
        for k in 0..ns.len().saturating_sub(1) {
            segs.push(Seg { line: i, k, a: nodes[ns[k]], b: nodes[ns[k + 1]], na: ns[k], nb: ns[k + 1] });
        }
        line_nodes.push(ns);
    }
    // how many line ends and passes meet at each node, and by which lines
    let mut degree: Vec<usize> = vec![0; nodes.len()];
    let mut at_node: Vec<Vec<usize>> = vec![Vec::new(); nodes.len()];
    for s in &segs {
        if s.na == s.nb {
            continue;
        }
        degree[s.na] += 1;
        degree[s.nb] += 1;
        for n in [s.na, s.nb] {
            if !at_node[n].contains(&s.line) {
                at_node[n].push(s.line);
            }
        }
    }
    // crossings and overlaps, by pairs of chords near each other (sorted by x)
    let mut order: Vec<usize> = (0..segs.len()).collect();
    let minx = |s: &Seg| s.a[0].min(s.b[0]) - JOIN;
    let maxx = |s: &Seg| s.a[0].max(s.b[0]) + JOIN;
    order.sort_by(|a, b| minx(&segs[*a]).partial_cmp(&minx(&segs[*b])).unwrap_or(std::cmp::Ordering::Equal));
    let mut crossings: Vec<((usize, usize), P, (usize, usize))> = Vec::new();
    let mut overlaps: Vec<(usize, usize)> = Vec::new();
    let mut active: Vec<usize> = Vec::new();
    for &i in &order {
        let s = segs[i];
        let x0 = minx(&s);
        active.retain(|&j| maxx(&segs[j]) >= x0 - 1e-9);
        let (sy0, sy1) = (s.a[1].min(s.b[1]) - JOIN, s.a[1].max(s.b[1]) + JOIN);
        for &j in &active {
            let t = segs[j];
            let (ty0, ty1) = (t.a[1].min(t.b[1]) - JOIN, t.a[1].max(t.b[1]) + JOIN);
            if ty1 < sy0 - 1e-9 || ty0 > sy1 + 1e-9 {
                continue;
            }
            let (p, q) = if (s.line, s.k) < (t.line, t.k) { (s, t) } else { (t, s) };
            // neighbours along one line share an end, and only that
            let neighbours = p.line == q.line && {
                let n = line_nodes[p.line].len() - 1;
                q.k == p.k + 1 || (lines[p.line].shape.is_closed() && p.k == 0 && q.k + 1 == n)
            };
            let key = (p.line, q.line);
            if overlap(&p, &q) {
                if !overlaps.contains(&key) {
                    overlaps.push(key);
                }
                continue;
            }
            // a curve isn't tried against itself for crossings; a polyline is
            if neighbours || (p.line == q.line && !matches!(lines[p.line].shape, Shape::Poly(..))) {
                continue;
            }
            // chords that share a node meet there (and cross nowhere else unless they overlap)
            let shared = [p.na, p.nb].iter().any(|n| *n == q.na || *n == q.nb);
            if shared {
                continue;
            }
            if let Some(x) = crossing(&p, &q) {
                {
                    let ks = (p.k, q.k);
                    match crossings.iter_mut().find(|(k, _, _)| *k == key) {
                        Some(c) => {
                            if ks < c.2 {
                                c.1 = x;
                                c.2 = ks;
                            }
                        }
                        None => crossings.push((key, x, ks)),
                    }
                }
            }
        }
        active.push(i);
    }
    crossings.sort_by(|a, b| a.0.cmp(&b.0));
    overlaps.sort();
    for ((a, b), x, _) in &crossings {
        if a == b {
            problems.push(format!("line {} crosses itself at {}", a, at(*x)));
        } else {
            problems.push(format!("line {} and line {} intersect at {}", a, b, at(*x)));
        }
    }
    for (a, b) in &overlaps {
        if a == b {
            problems.push(format!("line {} lies along itself", a));
        } else {
            problems.push(format!("line {} and line {} overlap", a, b));
        }
    }
    for (n, p) in nodes.iter().enumerate() {
        if degree[n] > 2 {
            let mut ls = at_node[n].clone();
            ls.sort();
            if ls.len() == 1 {
                problems.push(format!("line {} passes {} more than once: a loop passes a point once", ls[0], at(*p)));
            } else {
                problems.push(format!("{} meet at {}: a loop passes a point once", list_lines(&ls), at(*p)));
            }
        }
    }
    for (i, ns) in line_nodes.iter().enumerate() {
        if lines[i].shape.is_closed() || ns.is_empty() {
            continue;
        }
        for n in [ns[0], *ns.last().unwrap()] {
            if degree[n] == 1 {
                problems.push(format!("line {} ends at {} without meeting another: the loop is open", i, at(nodes[n])));
            }
        }
    }
    if !problems.is_empty() {
        return Err(joined(&problems));
    }
    // the loops: walk from chord to chord through the nodes
    let mut by_node: Vec<Vec<usize>> = vec![Vec::new(); nodes.len()];
    for (i, s) in segs.iter().enumerate() {
        by_node[s.na].push(i);
        by_node[s.nb].push(i);
    }
    let mut used = vec![false; segs.len()];
    let mut loops: Vec<(Vec<P>, Vec<usize>)> = Vec::new();
    for start in 0..segs.len() {
        if used[start] {
            continue;
        }
        let mut ring: Vec<P> = Vec::new();
        let mut ls: Vec<usize> = Vec::new();
        let mut cur = start;
        let first = segs[start].na;
        let mut node = first;
        loop {
            used[cur] = true;
            let s = segs[cur];
            if !ls.contains(&s.line) {
                ls.push(s.line);
            }
            ring.push(nodes[node]);
            let next_node = if s.na == node { s.nb } else { s.na };
            node = next_node;
            if node == first {
                break;
            }
            match by_node[node].iter().find(|&&j| !used[j]) {
                Some(&j) => cur = j,
                None => break,
            }
        }
        loops.push((ring, ls));
    }
    let mut problems = Vec::new();
    for (ring, ls) in &loops {
        if area(ring).abs() < JOIN * JOIN {
            let mut l = ls.clone();
            l.sort();
            problems.push(format!("the loop of {} encloses no area", list_lines(&l)));
        }
    }
    if !problems.is_empty() {
        return Err(joined(&problems));
    }
    // outlines and holes: how many loops each lies inside
    let rings: Vec<Vec<P>> = loops.into_iter().map(|(r, _)| r).collect();
    let inside = |p: P, ring: &[P]| -> bool {
        let mut c = false;
        let n = ring.len();
        for i in 0..n {
            let a = ring[i];
            let b = ring[(i + 1) % n];
            if (a[1] > p[1]) != (b[1] > p[1]) {
                let x = a[0] + (p[1] - a[1]) / (b[1] - a[1]) * (b[0] - a[0]);
                if p[0] < x {
                    c = !c;
                }
            }
        }
        c
    };
    // a point inside each ring, near its first edge
    let probe = |ring: &[P]| -> P {
        let a = ring[0];
        let b = ring[1 % ring.len()];
        let m = [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0];
        m
    };
    let n = rings.len();
    let mut parent: Vec<Option<usize>> = vec![None; n];
    let mut depth = vec![0usize; n];
    for i in 0..n {
        let p = probe(&rings[i]);
        let mut best: Option<usize> = None;
        for j in 0..n {
            if i == j {
                continue;
            }
            if inside(p, &rings[j]) {
                depth[i] += 1;
                if best.map_or(true, |b| area(&rings[j]).abs() < area(&rings[b]).abs()) {
                    best = Some(j);
                }
            }
        }
        parent[i] = best;
    }
    let mut regions: Vec<Region> = Vec::new();
    let mut index: Vec<Option<usize>> = vec![None; n];
    for i in 0..n {
        if depth[i] % 2 == 0 {
            let mut r = rings[i].clone();
            if area(&r) < 0.0 {
                r.reverse();
            }
            index[i] = Some(regions.len());
            regions.push(Region { outline: r, holes: Vec::new() });
        }
    }
    for i in 0..n {
        if depth[i] % 2 == 1 {
            if let Some(p) = parent[i] {
                if let Some(ri) = index[p] {
                    let mut h = rings[i].clone();
                    if area(&h) > 0.0 {
                        h.reverse();
                    }
                    regions[ri].holes.push(h);
                }
            }
        }
    }
    Ok(regions)
}

