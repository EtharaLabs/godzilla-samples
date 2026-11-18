//! Sketches: lines (straight, arcs, polylines, circles, ellipses, splines) drawn in any order and
//! either way round, solved into closed loops (outlines counter-clockwise, holes clockwise), or
//! every problem with the lines it's about, ranked. Also the problems of a ring's edges, which is
//! how an outline given as points is judged simple.

use super::curves::Curve;
use super::P2;
use crate::json::{Map, Value};

/// A sketch line: its curve, the part id it was sent back with, and the points it is drawn with.
#[derive(Clone, Debug)]
pub struct Line {
    pub id: Option<u64>,
    pub curve: Curve,
    /// The curve's fields as an element keeps them (start, end, arc…).
    pub fields: Map,
    /// Its points along it, ends included.
    pub pts: Vec<P2>,
}

#[derive(Clone, Debug)]
pub enum Problem {
    /// rank 0: a line 1 mm long or less
    Short(usize),
    /// rank 0: an edge whose two points are the same
    Same(usize),
    /// rank 0: a line it can't draw, and why ("" for a point out of reach)
    Undrawable(usize, String),
    /// rank 1: two lines crossing, or one ending part way along another
    Cross(usize, usize, P2),
    /// rank 1: a line crossing itself
    SelfCross(usize, P2),
    /// rank 2: two lines along each other
    Overlap(usize, usize),
    /// rank 3: three or more lines' ends at a point
    Meet(Vec<usize>, P2),
    /// rank 4: an end no other line meets
    Open(usize, P2),
    /// rank 5: a loop with no area
    NoArea(Vec<usize>),
}

impl Problem {
    pub fn rank(&self) -> u8 {
        match self {
            Problem::Short(_) | Problem::Same(_) | Problem::Undrawable(..) => 0,
            Problem::Cross(..) | Problem::SelfCross(..) => 1,
            Problem::Overlap(..) => 2,
            Problem::Meet(..) => 3,
            Problem::Open(..) => 4,
            Problem::NoArea(..) => 5,
        }
    }
}

fn pt0(p: P2) -> String {
    format!("[{:.0}, {:.0}]", p[0], p[1])
}

fn list(word: &str, ls: &[usize]) -> String {
    let names: Vec<String> = ls.iter().map(|l| format!("{} {}", word, l)).collect();
    if names.len() > 1 {
        format!("{} and {}", names[..names.len() - 1].join(", "), names[names.len() - 1])
    } else {
        names.join("")
    }
}

/// The problems said as the messages say them: "line 0 and line 2 intersect at [500, 500]; …".
pub fn describe(probs: &[Problem], word: &str) -> String {
    let mut out = Vec::new();
    for p in probs {
        out.push(match p {
            Problem::Short(i) => format!("{} {} is 1 mm long or less", word, i),
            Problem::Same(i) => format!(
                "{} {} isn't a line it can draw: two points one after another are the same; a line runs between points apart",
                word, i
            ),
            Problem::Undrawable(i, why) => {
                if why.is_empty() {
                    format!("{} {} has a point that isn't a number within 1000000000 mm, or a curve reaching further", word, i)
                } else {
                    format!("{} {} isn't a line it can draw: {}", word, i, why)
                }
            }
            Problem::Cross(i, j, q) => format!("{} {} and {} {} intersect at {}", word, i, word, j, pt0(*q)),
            Problem::SelfCross(i, q) => format!("{} {} crosses itself at {}", word, i, pt0(*q)),
            Problem::Overlap(i, j) => format!("{} {} and {} {} overlap", word, i, word, j),
            Problem::Meet(ls, q) => format!("{} meet at {}: a loop passes a point once", list(word, ls), pt0(*q)),
            Problem::Open(i, q) => format!("{} {} ends at {} without meeting another: the loop is open", word, i, pt0(*q)),
            Problem::NoArea(ls) => format!("{} make a loop with no area", list(word, ls)),
        });
    }
    out.join("; ")
}

pub const TOL: f64 = 1.0;

/// Where two segments meet at one point (ends included): the point along a.
fn meet(a0: P2, a1: P2, b0: P2, b1: P2) -> Option<P2> {
    let d = super::sub(a1, a0);
    let e = super::sub(b1, b0);
    let den = super::cross(d, e);
    if den == 0.0 {
        return None;
    }
    let w = super::sub(b0, a0);
    let t = super::cross(w, e) / den;
    let u = super::cross(w, d) / den;
    let ta = TOL / super::len(d).max(1e-300);
    let tb = TOL / super::len(e).max(1e-300);
    if t >= -ta && t <= 1.0 + ta && u >= -tb && u <= 1.0 + tb {
        Some(super::lerp(a0, a1, t.clamp(0.0, 1.0)))
    } else {
        None
    }
}

/// Whether two segments lie along each other for more than a hair.
fn overlap(a0: P2, a1: P2, b0: P2, b1: P2) -> bool {
    let d = super::sub(a1, a0);
    let l = super::len(d);
    if l <= 0.0 {
        return false;
    }
    let n = [-d[1] / l, d[0] / l];
    let db0 = super::dot(super::sub(b0, a0), n);
    let db1 = super::dot(super::sub(b1, a0), n);
    if db0.abs() > 1e-6 || db1.abs() > 1e-6 {
        return false;
    }
    let u = [d[0] / l, d[1] / l];
    let s0 = super::dot(super::sub(b0, a0), u);
    let s1 = super::dot(super::sub(b1, a0), u);
    let lo = s0.min(s1).max(0.0);
    let hi = s0.max(s1).min(l);
    hi - lo > 1e-6
}

/// The problems of a ring of points taken as the sketch of its edges (edge i from point i to the
/// next).
pub fn ring_problems(ring: &[P2]) -> Vec<Problem> {
    let n = ring.len();
    let lines: Vec<Vec<P2>> = (0..n).map(|i| vec![ring[i], ring[(i + 1) % n]]).collect();
    let mut probs = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if l[0] == l[1] {
            probs.push(Problem::Same(i));
        } else if super::dist(l[0], l[1]) <= TOL {
            probs.push(Problem::Short(i));
        }
    }
    if !probs.is_empty() {
        return probs;
    }
    problems(&lines, &vec![false; n])
}

/// The problems among lines (each a polyline of points; `closed` for one that closes on itself),
/// past those of a line it can't draw: crossings, overlaps, junctions, open ends.
pub fn problems(lines: &[Vec<P2>], closed: &[bool]) -> Vec<Problem> {
    let mut probs: Vec<Problem> = Vec::new();
    // ends, welded within the tolerance
    let mut nodes: Vec<P2> = Vec::new();
    let mut ends: Vec<Vec<(usize, bool)>> = Vec::new();
    let node_of = |p: P2, nodes: &mut Vec<P2>, ends: &mut Vec<Vec<(usize, bool)>>| -> usize {
        for (k, q) in nodes.iter().enumerate() {
            if super::dist(*q, p) <= TOL {
                return k;
            }
        }
        nodes.push(p);
        ends.push(Vec::new());
        nodes.len() - 1
    };
    let mut line_nodes = vec![(usize::MAX, usize::MAX); lines.len()];
    for (i, l) in lines.iter().enumerate() {
        if closed[i] {
            continue;
        }
        let a = node_of(l[0], &mut nodes, &mut ends);
        ends[a].push((i, false));
        let b = node_of(*l.last().unwrap(), &mut nodes, &mut ends);
        ends[b].push((i, true));
        line_nodes[i] = (a, b);
    }
    let is_end = |i: usize, q: P2| -> bool {
        !closed[i] && (super::dist(q, lines[i][0]) <= TOL || super::dist(q, *lines[i].last().unwrap()) <= TOL)
    };
    // a line crossing itself
    let mut crosses: Vec<Problem> = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        let m = l.len().saturating_sub(1);
        let mut found = None;
        'outer: for a in 0..m {
            for b in a + 2..m {
                if closed[i] && a == 0 && b == m - 1 {
                    continue;
                }
                if let Some(q) = meet(l[a], l[a + 1], l[b], l[b + 1]) {
                    // the line's own two ends meeting close it
                    if a == 0 && b == m - 1 && super::dist(l[0], l[m]) <= TOL {
                        continue;
                    }
                    found = Some(q);
                    break 'outer;
                }
            }
        }
        if let Some(q) = found {
            crosses.push(Problem::SelfCross(i, q));
        }
    }
    let mut overlaps: Vec<Problem> = Vec::new();
    for i in 0..lines.len() {
        for j in i + 1..lines.len() {
            let mut ov = false;
            let mut cross_at: Option<P2> = None;
            for wa in lines[i].windows(2) {
                for wb in lines[j].windows(2) {
                    if overlap(wa[0], wa[1], wb[0], wb[1]) {
                        ov = true;
                    } else if cross_at.is_none() {
                        if let Some(q) = meet(wa[0], wa[1], wb[0], wb[1]) {
                            // a meeting at ends welded together is a join, not a crossing
                            if !(is_end(i, q) && is_end(j, q)) {
                                cross_at = Some(q);
                            }
                        }
                    }
                }
            }
            if ov {
                overlaps.push(Problem::Overlap(i, j));
            } else if let Some(q) = cross_at {
                crosses.push(Problem::Cross(i, j, q));
            }
        }
    }
    probs.extend(crosses);
    probs.extend(overlaps);
    for (k, e) in ends.iter().enumerate() {
        if e.len() >= 3 {
            let mut ls: Vec<usize> = e.iter().map(|x| x.0).collect();
            ls.sort();
            ls.dedup();
            probs.push(Problem::Meet(ls, nodes[k]));
        }
    }
    for (i, l) in lines.iter().enumerate() {
        if closed[i] {
            continue;
        }
        let (a, b) = line_nodes[i];
        // a line whose two ends weld together closes on itself
        if a == b {
            continue;
        }
        if ends[a].len() == 1 {
            probs.push(Problem::Open(i, l[0]));
        }
        if ends[b].len() == 1 {
            probs.push(Problem::Open(i, *l.last().unwrap()));
        }
    }
    probs.sort_by_key(|p| p.rank());
    probs
}

// ---------------------------------------------------------------- reading lines

/// Why a sketch parameter couldn't be read: serde's message (after the help), or one line's.
#[derive(Debug, Clone)]
pub enum ParseErr {
    Serde(String),
    Line(usize, String),
}

const UNTAGGED: &str = "data did not match any variant of untagged enum Given";
const FIELDS: &[&str] = &[
    "id", "start", "end", "arc", "through", "points", "arcs", "closed", "centre", "radius", "radii", "angle", "span", "control",
    "knots", "fit", "start_tangent", "end_tangent", "slope",
];

fn p2(v: &Value) -> Option<P2> {
    let a = v.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

fn p2s(v: &Value) -> Option<Vec<P2>> {
    v.as_arr()?.iter().map(p2).collect()
}

fn f64s(v: &Value) -> Option<Vec<f64>> {
    v.as_arr()?.iter().map(|x| x.as_f64()).collect()
}

fn pv(p: P2) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

fn ring_v(r: &[P2]) -> Value {
    Value::Arr(r.iter().map(|p| pv(*p)).collect())
}

/// One line as given: a curve and the fields an element keeps of it.
fn parse_line(v: &Value) -> Result<Result<(Option<u64>, Curve, Map), String>, ()> {
    match v {
        Value::Arr(a) => {
            let pts: Vec<P2> = match a.iter().map(p2).collect::<Option<Vec<P2>>>() {
                Some(p) => p,
                None => return Err(()),
            };
            match pts.len() {
                2 => {
                    let mut m = Map::new();
                    m.insert("start", pv(pts[0]));
                    m.insert("end", pv(pts[1]));
                    Ok(Ok((None, Curve::Line(pts[0], pts[1]), m)))
                }
                3 => {
                    let mut m = Map::new();
                    m.insert("start", pv(pts[0]));
                    m.insert("end", pv(pts[1]));
                    match super::curves::turn_through(pts[0], pts[1], pts[2]) {
                        Some(deg) => {
                            m.insert("arc", Value::f(deg));
                            Ok(Ok((None, Curve::Arc(pts[0], pts[1], deg), m)))
                        }
                        None => Ok(Ok((None, Curve::Line(pts[0], pts[1]), m))),
                    }
                }
                _ => Err(()),
            }
        }
        Value::Obj(o) => {
            for (k, _) in &o.items {
                if !FIELDS.contains(&k.as_str()) {
                    return Err(());
                }
            }
            let g = |k: &str| o.get(k).filter(|x| !x.is_null());
            let id = match g("id") {
                None => None,
                Some(x) => match x.as_u64() {
                    Some(u) => Some(u),
                    None => return Err(()),
                },
            };
            let pt = |k: &str| -> Result<Option<P2>, ()> {
                match g(k) {
                    None => Ok(None),
                    Some(x) => p2(x).map(Some).ok_or(()),
                }
            };
            let num = |k: &str| -> Result<Option<f64>, ()> {
                match g(k) {
                    None => Ok(None),
                    Some(x) => x.as_f64().map(Some).ok_or(()),
                }
            };
            let start = pt("start")?;
            let end = pt("end")?;
            let arc = num("arc")?;
            let through = pt("through")?;
            let points = match g("points") {
                None => None,
                Some(x) => Some(p2s(x).ok_or(())?),
            };
            let arcs = match g("arcs") {
                None => None,
                Some(x) => Some(f64s(x).ok_or(())?),
            };
            let closed = match g("closed") {
                None => None,
                Some(x) => Some(x.as_bool().ok_or(())?),
            };
            let centre = pt("centre")?;
            let radius = num("radius")?;
            let radii = match g("radii") {
                None => None,
                Some(x) => Some(p2(x).ok_or(())?),
            };
            let angle = num("angle")?;
            let span = match g("span") {
                None => None,
                Some(x) => Some(p2(x).ok_or(())?),
            };
            let control = match g("control") {
                None => None,
                Some(x) => Some(p2s(x).ok_or(())?),
            };
            let knots = match g("knots") {
                None => None,
                Some(x) => Some(f64s(x).ok_or(())?),
            };
            let fit = match g("fit") {
                None => None,
                Some(x) => Some(p2s(x).ok_or(())?),
            };
            let t0 = pt("start_tangent")?;
            let t1 = pt("end_tangent")?;
            let slope = num("slope")?;
            let r = object_line(id, start, end, arc, through, points, arcs, closed, centre, radius, radii, angle, span, control, knots, fit, t0, t1);
            return Ok(r.map(|(id, c, mut m)| {
                if let Some(sl) = slope {
                    m.insert("slope", Value::f(sl));
                }
                (id, c, m)
            }));
        }
        _ => Err(()),
    }
}

#[allow(clippy::too_many_arguments)]
fn object_line(
    id: Option<u64>,
    start: Option<P2>,
    end: Option<P2>,
    arc: Option<f64>,
    through: Option<P2>,
    points: Option<Vec<P2>>,
    arcs: Option<Vec<f64>>,
    closed: Option<bool>,
    centre: Option<P2>,
    radius: Option<f64>,
    radii: Option<P2>,
    angle: Option<f64>,
    span: Option<P2>,
    control: Option<Vec<P2>>,
    knots: Option<Vec<f64>>,
    fit: Option<Vec<P2>>,
    t0: Option<P2>,
    t1: Option<P2>,
) -> Result<(Option<u64>, Curve, Map), String> {
    {
        {
            let mut m = Map::new();
            if let (Some(a), Some(b)) = (start, end) {
                m.insert("start", pv(a));
                m.insert("end", pv(b));
                if arc.is_some() && through.is_some() {
                    return Err("give an arc's `through` point or its `arc` turn, not both".into());
                }
                let deg = match (arc, through) {
                    (Some(d), _) => Some(d),
                    (None, Some(t)) => super::curves::turn_through(a, b, t),
                    _ => None,
                };
                return Ok(match deg {
                    Some(d) if d != 0.0 => {
                        m.insert("arc", Value::f(d));
                        (id, Curve::Arc(a, b, d), m)
                    }
                    _ => (id, Curve::Line(a, b), m),
                });
            }
            if let Some(pts) = points {
                m.insert("points", ring_v(&pts));
                if let Some(a) = &arcs {
                    m.insert("arcs", Value::Arr(a.iter().map(|x| Value::f(*x)).collect()));
                }
                if let Some(c) = closed {
                    m.insert("closed", Value::Bool(c));
                }
                // a polyline whose last point is its first closes
                let mut pts = pts;
                let mut cl = closed.unwrap_or(false);
                if !cl && pts.len() > 2 && super::dist(pts[0], *pts.last().unwrap()) <= TOL {
                    pts.pop();
                    cl = true;
                }
                return Ok((id, Curve::Poly { pts, arcs: arcs.unwrap_or_default(), closed: cl }, m));
            }
            if let (Some(c), Some(r)) = (centre, radius) {
                m.insert("centre", pv(c));
                m.insert("radius", Value::f(r));
                return Ok((id, Curve::Circle { c, r }, m));
            }
            if let (Some(c), Some(rr)) = (centre, radii) {
                m.insert("centre", pv(c));
                m.insert("radii", pv(rr));
                if let Some(a) = angle {
                    m.insert("angle", Value::f(a));
                }
                if let Some(s) = span {
                    m.insert("span", pv(s));
                }
                return Ok((id, Curve::Ellipse { c, rx: rr[0], ry: rr[1], angle: angle.unwrap_or(0.0), span: span.map(|s| (s[0], s[1])) }, m));
            }
            if let Some(ctrl) = control {
                m.insert("control", ring_v(&ctrl));
                if let Some(k) = &knots {
                    m.insert("knots", Value::Arr(k.iter().map(|x| Value::f(*x)).collect()));
                }
                return Ok((id, Curve::Spline { control: ctrl, knots }, m));
            }
            if let Some(f) = fit {
                m.insert("fit", ring_v(&f));
                if let Some(t) = t0 {
                    m.insert("start_tangent", pv(t));
                }
                if let Some(t) = t1 {
                    m.insert("end_tangent", pv(t));
                }
                return Ok((id, Curve::Fit { pts: f, t0, t1 }, m));
            }
            Err("a line is `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)".into())
        }
    }
}

/// A sketch parameter read into lines; `ids` are the part ids it may send back.
pub fn parse_with(v: &Value, ids: &[u64]) -> Result<Vec<Line>, ParseErr> {
    let Value::Arr(a) = v else {
        return Err(ParseErr::Serde(format!("invalid type: {}, expected a sequence", v.kind_name())));
    };
    let mut parsed = Vec::with_capacity(a.len());
    for x in a {
        match parse_line(x) {
            Err(()) => return Err(ParseErr::Serde(UNTAGGED.to_string())),
            Ok(r) => parsed.push(r),
        }
    }
    let mut out = Vec::with_capacity(parsed.len());
    for (i, r) in parsed.into_iter().enumerate() {
        match r {
            Err(msg) => return Err(ParseErr::Line(i, msg)),
            Ok((id, curve, fields)) => {
                if let Some(id) = id {
                    if !ids.contains(&id) {
                        return Err(ParseErr::Line(i, format!("{} isn't a line of this sketch; leave `id` out for a new one", id)));
                    }
                }
                out.push(Line { id, curve, fields, pts: Vec::new() });
            }
        }
    }
    Ok(out)
}

pub fn parse(v: &Value) -> Result<Vec<Line>, ParseErr> {
    parse_with(v, &[])
}

/// What the original says before a sketch parameter's serde error.
pub const HELP: &str = "is a list of lines, each [[x,y],[x,y]], an arc [[x,y],[x,y],[x,y]] (its ends, then a point it passes through) or an object: `id?` and a curve's fields, `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

/// A parse error as a command says it: `{cmd}: `{key}` …`.
pub fn parse_message(cmd: &str, key: &str, e: &ParseErr) -> String {
    match e {
        ParseErr::Serde(s) => format!("{}: `{}` {}: {}", cmd, key, HELP, s),
        ParseErr::Line(i, s) => format!("{}: `{}` line {}: {}", cmd, key, i, s),
    }
}

// ---------------------------------------------------------------- solving

/// A region a sketch closes: its outline (counter-clockwise) and holes (clockwise).
#[derive(Clone, Debug)]
pub struct Region {
    pub outline: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
    /// The line each edge of each ring is drawn by: the outline's, then each hole's.
    pub lines: Vec<Vec<usize>>,
}

impl Region {
    pub fn area(&self) -> f64 {
        let mut a = super::area(&self.outline).abs();
        for h in &self.holes {
            a -= super::area(h).abs();
        }
        a
    }
}

/// The ring turned round, its first point kept first.
fn reverse_keep_first(r: &[P2]) -> Vec<P2> {
    if r.is_empty() {
        return Vec::new();
    }
    let mut out = vec![r[0]];
    out.extend(r[1..].iter().rev());
    out
}

/// The sketch solved into regions, or its problems.
pub fn solve(lines: &mut [Line]) -> Result<Vec<Region>, Vec<Problem>> {
    if lines.is_empty() {
        return Err(Vec::new());
    }
    // what can't be drawn is said alone
    let mut bad = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if let Some(why) = l.curve.undrawable() {
            bad.push(Problem::Undrawable(i, why));
        }
    }
    if !bad.is_empty() {
        return Err(bad);
    }
    for l in lines.iter_mut() {
        l.pts = l.curve.points();
    }
    for (i, l) in lines.iter().enumerate() {
        let len: f64 = l.pts.windows(2).map(|w| super::dist(w[0], w[1])).sum();
        if len <= TOL {
            bad.push(Problem::Short(i));
        }
    }
    if !bad.is_empty() {
        return Err(bad);
    }
    let pl: Vec<Vec<P2>> = lines.iter().map(|l| l.pts.clone()).collect();
    let closed: Vec<bool> = lines.iter().map(|l| l.curve.closed()).collect();
    let probs = problems(&pl, &closed);
    if !probs.is_empty() {
        return Err(probs);
    }
    // the loops, each from its first line, end to end: the ring, its lines, and the line of
    // each of its edges
    let n = lines.len();
    let mut used = vec![false; n];
    let mut loops: Vec<(Vec<P2>, Vec<usize>, Vec<usize>)> = Vec::new();
    for s in 0..n {
        if used[s] {
            continue;
        }
        used[s] = true;
        let first = &lines[s].pts;
        if closed[s] || super::dist(first[0], *first.last().unwrap()) <= TOL {
            let ring = first[..first.len() - 1].to_vec();
            let el = vec![s; ring.len()];
            loops.push((ring, vec![s], el));
            continue;
        }
        let mut ring: Vec<P2> = first[..first.len() - 1].to_vec();
        let mut el: Vec<usize> = vec![s; ring.len()];
        let mut members = vec![s];
        let start = first[0];
        let mut end = *first.last().unwrap();
        while super::dist(end, start) > TOL {
            let mut found = false;
            for k in 0..n {
                if used[k] || closed[k] {
                    continue;
                }
                let l = &lines[k].pts;
                if super::dist(l[0], end) <= TOL {
                    ring.extend_from_slice(&l[..l.len() - 1]);
                    el.extend(std::iter::repeat(k).take(l.len() - 1));
                    end = *l.last().unwrap();
                } else if super::dist(*l.last().unwrap(), end) <= TOL {
                    let rev: Vec<P2> = l.iter().rev().copied().collect();
                    ring.extend_from_slice(&rev[..rev.len() - 1]);
                    el.extend(std::iter::repeat(k).take(rev.len() - 1));
                    end = rev[rev.len() - 1];
                } else {
                    continue;
                }
                used[k] = true;
                members.push(k);
                found = true;
                break;
            }
            if !found {
                break;
            }
        }
        loops.push((ring, members, el));
    }
    // a loop with no area
    let mut flat = Vec::new();
    for (ring, members, _) in &loops {
        if !(super::area(ring).abs() > 0.0) {
            let mut ms = members.clone();
            ms.sort();
            flat.push(Problem::NoArea(ms));
        }
    }
    if !flat.is_empty() {
        return Err(flat);
    }
    // turned round keeping the first point: edge k is the old edge n-1-k
    let turned = |r: &Vec<P2>, el: &Vec<usize>| -> (Vec<P2>, Vec<usize>) {
        let m = el.len();
        (reverse_keep_first(r), (0..m).map(|k| el[m - 1 - k]).collect())
    };
    // nest them: inside an even number of others, an outline; odd, a hole of the innermost
    let depth: Vec<usize> = loops
        .iter()
        .enumerate()
        .map(|(i, (r, _, _))| loops.iter().enumerate().filter(|(j, (o, _, _))| *j != i && super::inside_raw(o, r[0])).count())
        .collect();
    let mut regions: Vec<Region> = Vec::new();
    let mut index_of: Vec<Option<usize>> = vec![None; loops.len()];
    for (i, (r, _, el)) in loops.iter().enumerate() {
        if depth[i] % 2 == 0 {
            let (outline, edges) = if super::area(r) < 0.0 { turned(r, el) } else { (r.clone(), el.clone()) };
            index_of[i] = Some(regions.len());
            regions.push(Region { outline, holes: Vec::new(), lines: vec![edges] });
        }
    }
    for (i, (r, _, el)) in loops.iter().enumerate() {
        if depth[i] % 2 == 1 {
            // the innermost outline round it
            let mut best: Option<usize> = None;
            for (j, (o, _, _)) in loops.iter().enumerate() {
                if j != i && depth[j] % 2 == 0 && depth[j] + 1 == depth[i] && super::inside_raw(o, r[0]) {
                    best = Some(j);
                }
            }
            if let Some(j) = best {
                let k = index_of[j].unwrap();
                let (hole, edges) = if super::area(r) > 0.0 { turned(r, el) } else { (r.clone(), el.clone()) };
                regions[k].holes.push(hole);
                regions[k].lines.push(edges);
            }
        }
    }
    Ok(regions)
}

/// The message for a sketch that doesn't solve.
pub fn unsolved(probs: &[Problem]) -> String {
    if probs.is_empty() {
        return "the lines don't make closed loops: there are no lines: draw the outline".to_string();
    }
    format!("the lines don't make closed loops: {}", describe(probs, "line"))
}

/// One outline and its holes from a sketch, or the message saying what's wrong.
pub fn solve_one(lines: &mut [Line]) -> Result<(Vec<P2>, Vec<Vec<P2>>), String> {
    let regions = match solve(lines) {
        Ok(r) => r,
        Err(p) => {
            if p.is_empty() {
                return Err("the sketch isn't one outline: there are no lines: draw the outline".to_string());
            }
            return Err(format!("the sketch isn't one outline: {}", describe(&p, "line")));
        }
    };
    if regions.len() != 1 {
        return Err(format!(
            "the sketch isn't one outline: the lines make {} separate outlines, where one is wanted",
            regions.len()
        ));
    }
    let r = regions.into_iter().next().unwrap();
    Ok((r.outline, r.holes))
}

/// The one region a sketch closes (an outline and its holes), or the message saying what's wrong.
pub fn solve_region(lines: &mut [Line]) -> Result<Region, String> {
    let regions = match solve(lines) {
        Ok(r) => r,
        Err(p) => {
            if p.is_empty() {
                return Err("the sketch isn't one outline: there are no lines: draw the outline".to_string());
            }
            return Err(format!("the sketch isn't one outline: {}", describe(&p, "line")));
        }
    };
    if regions.len() != 1 {
        return Err(format!(
            "the sketch isn't one outline: the lines make {} separate outlines, where one is wanted",
            regions.len()
        ));
    }
    Ok(regions.into_iter().next().unwrap())
}

/// What an element keeps of its sketch: each line with its part id and GUID.
pub fn to_value(pr: &mut crate::project::Project, lines: &[Line], kept: &[(u64, String)]) -> Value {
    let mut out = Vec::with_capacity(lines.len());
    for l in lines {
        let (id, guid) = match l.id.and_then(|i| kept.iter().find(|k| k.0 == i)) {
            Some((i, g)) => (*i, g.clone()),
            None => (pr.alloc_lib_id(), crate::rand::guid()),
        };
        let mut m = Map::new();
        m.insert("id", Value::u(id));
        m.insert("guid", Value::s(&guid));
        for (k, v) in &l.fields.items {
            m.insert(k, v.clone());
        }
        out.push(Value::Obj(m));
    }
    Value::Arr(out)
}
