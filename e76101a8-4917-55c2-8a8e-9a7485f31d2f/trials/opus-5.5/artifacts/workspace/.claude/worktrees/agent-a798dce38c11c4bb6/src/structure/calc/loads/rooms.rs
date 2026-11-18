//! The model's rooms as `load_points` measures them, inside the walls' finish: a private stand-in
//! for the architecture part's room boundaries, read from the project as the file holds it.
//!
//! A room's level is cut at its `computation_height` (1200 mm over it): the walls the cut passes
//! through (their base at or under it, their top over it) that bound rooms, and the room
//! separation lines of the level, bound it. Each wall is its plan footprint (its faces each side
//! of its location line, by its type's thickness and core); two walls meeting end to end are
//! mitred, and a wall ending within another's half thickness (and a millimetre) of its centre
//! line is cut on that wall's face. The room is the free face of those outlines around its
//! point, less the walls standing free inside it; a face another room (one of a lower id) has is
//! not its, and a room where nothing encloses its point is skipped. A frozen room keeps the
//! boundary it was frozen with.

use crate::json::{Map, Value};
use crate::project::Project;
use std::collections::HashMap;

type P = [f64; 2];

const WHY: &str = "not enclosed by walls";

fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
}
fn mul(a: P, k: f64) -> P {
    [a[0] * k, a[1] * k]
}
fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
fn crs(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
fn len(a: P) -> f64 {
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
fn dist(a: P, b: P) -> f64 {
    len(sub(a, b))
}

fn point(v: Option<&Value>) -> Option<P> {
    let a = v?.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

fn num(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

/// The model's rooms in id order: (name, area m², perimeter m) of those measured, and the
/// skipped ones as `{id, name, why}`.
pub fn model_rooms(pr: &Project) -> (Vec<(String, f64, f64)>, Vec<Value>) {
    let model = Model::read(pr);
    let mut found = Vec::new();
    let mut skipped = Vec::new();
    let mut plans: HashMap<String, Plan> = HashMap::new();
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) != Some("room") {
            continue;
        }
        let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
        let skip = |skipped: &mut Vec<Value>| {
            let mut o = Map::new();
            o.insert("id", Value::u(*id));
            o.insert("name", Value::s(&name));
            o.insert("why", Value::s(WHY));
            skipped.push(Value::Obj(o));
        };
        if e.get("frozen").and_then(|f| f.as_bool()) == Some(true) {
            if let Some(k) = e.get("kept").and_then(|k| k.get("finish")) {
                if let Some((a, p)) = kept_measure(k) {
                    found.push((name, a / 1e6, p / 1000.0));
                    continue;
                }
            }
        }
        let level = e.get("level").and_then(|l| l.as_str()).unwrap_or("").to_string();
        let Some(q) = point(e.get("point")) else {
            skip(&mut skipped);
            continue;
        };
        if !model.levels.contains_key(&level) {
            skip(&mut skipped);
            continue;
        }
        let plan = plans.entry(level.clone()).or_insert_with(|| Plan::of_level(&model, &level));
        match plan.room_at(q) {
            Some((a, p)) => found.push((name, a / 1e6, p / 1000.0)),
            None => skip(&mut skipped),
        }
    }
    (found, skipped)
}

/// The area (mm²) and perimeter (mm) of a kept boundary `{outer, holes}`.
fn kept_measure(k: &Value) -> Option<(f64, f64)> {
    let ring = |v: &Value| -> Option<Vec<P>> { v.as_arr()?.iter().map(|p| point(Some(p))).collect() };
    let outer = ring(k.get("outer")?)?;
    let mut a = area(&outer).abs();
    let mut p = perimeter(&outer);
    if let Some(hs) = k.get("holes").and_then(|h| h.as_arr()) {
        for h in hs {
            let h = ring(h)?;
            a -= area(&h).abs();
            p += perimeter(&h);
        }
    }
    Some((a, p))
}

fn area(p: &[P]) -> f64 {
    let mut s = 0.0;
    for i in 0..p.len() {
        let (a, b) = (p[i], p[(i + 1) % p.len()]);
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

fn perimeter(p: &[P]) -> f64 {
    (0..p.len()).map(|i| dist(p[i], p[(i + 1) % p.len()])).sum()
}

/// Whether the point is inside the polygon (an even-odd ray to +x).
fn inside(poly: &[P], q: P) -> bool {
    let n = poly.len();
    let mut c = false;
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        if (a[1] > q[1]) != (b[1] > q[1]) {
            let x = a[0] + (q[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
            if q[0] < x {
                c = !c;
            }
        }
    }
    c
}

// ---------------------------------------------------------------- the model as rooms see it

struct WallType {
    thickness: f64,
    core: (f64, f64),
}

struct Wall {
    base: f64,
    top: f64,
    bounding: bool,
    start: P,
    end: P,
    arc: f64,
    /// The exterior face's distance to the left of the location line, and the thickness.
    left: f64,
    thickness: f64,
}

struct Model {
    /// Level GUID → (elevation, computation height).
    levels: HashMap<String, (f64, f64)>,
    walls: Vec<Wall>,
    /// Room separation lines by level.
    separators: Vec<(String, P, P)>,
}

impl Model {
    fn read(pr: &Project) -> Model {
        let mut levels = HashMap::new();
        for e in pr.elements.values() {
            if e.get("category").and_then(|c| c.as_str()) == Some("level") {
                if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
                    let elev = num(e, "elevation").unwrap_or(0.0);
                    let ch = num(e, "computation_height").unwrap_or(1200.0);
                    levels.insert(g.to_string(), (elev, ch));
                }
            }
        }
        // the wall types by their library GUID
        let mut types: HashMap<String, WallType> = HashMap::new();
        let defs = pr.section("types").and_then(|t| t.get("wall")).and_then(|w| w.as_obj());
        for entry in pr.library.values() {
            if entry.get("kind").and_then(|k| k.as_str()) != Some("type:wall") {
                continue;
            }
            let (Some(g), Some(n)) = (entry.get("guid").and_then(|g| g.as_str()), entry.get("name").and_then(|n| n.as_str()))
            else {
                continue;
            };
            if let Some(t) = defs.and_then(|d| d.get(n)) {
                types.insert(g.to_string(), wall_type(t));
            }
        }
        let mut walls = Vec::new();
        let mut separators = Vec::new();
        for e in pr.elements.values() {
            match e.get("category").and_then(|c| c.as_str()) {
                Some("wall") => {
                    let (Some(s), Some(t)) = (point(e.get("start")), point(e.get("end"))) else { continue };
                    let level = e.get("level").and_then(|l| l.as_str()).unwrap_or("").to_string();
                    let elev = levels.get(&level).map(|l| l.0).unwrap_or(0.0);
                    let base = elev + num(e, "base_offset").unwrap_or(0.0);
                    let top = match e.get("top_level").and_then(|l| l.as_str()).and_then(|g| levels.get(g)) {
                        Some(l) => l.0 + num(e, "top_offset").unwrap_or(0.0),
                        None => base + num(e, "height").unwrap_or(0.0),
                    };
                    let wt = e.get("type").and_then(|g| g.as_str()).and_then(|g| types.get(g));
                    let thickness = wt.map(|w| w.thickness).unwrap_or(200.0);
                    let core = wt.map(|w| w.core).unwrap_or((0.0, thickness));
                    let left = match e.get("location").and_then(|l| l.as_str()).unwrap_or("centre") {
                        "exterior-finish" => 0.0,
                        "interior-finish" => thickness,
                        "core-centre" => (core.0 + core.1) / 2.0,
                        "exterior-core" => core.0,
                        "interior-core" => core.1,
                        _ => thickness / 2.0,
                    };
                    walls.push(Wall {
                        base,
                        top,
                        bounding: e.get("room_bounding").and_then(|b| b.as_bool()) != Some(false),
                        start: s,
                        end: t,
                        arc: num(e, "arc").unwrap_or(0.0),
                        left,
                        thickness,
                    });
                }
                Some("roomseparator") => {
                    let (Some(s), Some(t)) = (point(e.get("start")), point(e.get("end"))) else { continue };
                    let level = e.get("level").and_then(|l| l.as_str()).unwrap_or("").to_string();
                    separators.push((level, s, t));
                }
                _ => {}
            }
        }
        Model { levels, walls, separators }
    }
}

/// A wall type's thickness and its core (from its exterior face, from its first structure layer
/// to its last; all of it where it has none).
fn wall_type(t: &Value) -> WallType {
    let layers: Vec<(String, f64)> = t
        .get("layers")
        .and_then(|l| l.as_arr())
        .map(|ls| {
            ls.iter()
                .map(|l| {
                    (
                        l.get("function").and_then(|f| f.as_str()).unwrap_or("").to_string(),
                        l.get("thickness").and_then(|x| x.as_f64()).unwrap_or(0.0),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let sum: f64 = layers.iter().map(|l| l.1).sum();
    let thickness = t.get("thickness").and_then(|x| x.as_f64()).unwrap_or(if layers.is_empty() { 200.0 } else { sum });
    let mut core = (0.0, thickness);
    let first = layers.iter().position(|l| l.0 == "structure");
    let last = layers.iter().rposition(|l| l.0 == "structure");
    if let (Some(f), Some(l)) = (first, last) {
        let a: f64 = layers[..f].iter().map(|x| x.1).sum();
        let b: f64 = layers[..=l].iter().map(|x| x.1).sum();
        core = (a, b);
    }
    WallType { thickness, core }
}

// ---------------------------------------------------------------- footprints

/// A wall's footprint: its left face and right face as polylines from its start to its end, the
/// way it runs at each end, and its centre line (for the T joins).
#[derive(Clone)]
struct Outline {
    left: Vec<P>,
    right: Vec<P>,
    centre: Vec<P>,
    half: f64,
    dir_start: P,
    dir_end: P,
}

/// The arc through both ends turning `sweep` degrees counter-clockwise: centre, radius, start
/// angle, sweep in radians.
fn arc_of(s: P, t: P, sweep: f64) -> Option<(P, f64, f64, f64)> {
    let sw = sweep.to_radians();
    let chord = dist(s, t);
    if chord < 1e-9 || sw.abs() < 1e-12 {
        return None;
    }
    let r = chord / 2.0 / (sw.abs() / 2.0).sin();
    let mid = mul(add(s, t), 0.5);
    let d = (r * r - (chord / 2.0).powi(2)).max(0.0).sqrt();
    let n = [-(t[1] - s[1]) / chord, (t[0] - s[0]) / chord];
    let sign = if (sw > 0.0) == (sw.abs() < std::f64::consts::PI) { 1.0 } else { -1.0 };
    let c = add(mid, mul(n, sign * d));
    let a0 = (s[1] - c[1]).atan2(s[0] - c[0]);
    Some((c, r, a0, sw))
}

/// A wall's outline between two ends (its own, or where a T join carries them).
fn outline(w: &Wall, start: P, end: P) -> Option<Outline> {
    let lo = w.left;
    let ro = w.thickness - w.left;
    let mid = (lo - ro) / 2.0; // the centre line's offset to the left of the location line
    if w.arc != 0.0 {
        if let Some((c, r, a0, sw)) = arc_of(start, end, w.arc) {
            let tol = 1.0f64;
            let n = if r > tol { ((sw.abs() / (2.0 * (1.0 - tol / r).acos())).ceil() as usize).max(1) } else { 1 };
            // to the left of a counter-clockwise arc is its centre
            let ccw = sw > 0.0;
            let ring = |off: f64| -> Vec<P> {
                let rr = if ccw { r - off } else { r + off };
                (0..=n)
                    .map(|k| {
                        let a = a0 + sw * k as f64 / n as f64;
                        [c[0] + rr * a.cos(), c[1] + rr * a.sin()]
                    })
                    .collect()
            };
            let travel = |a: f64| if ccw { [-a.sin(), a.cos()] } else { [a.sin(), -a.cos()] };
            return Some(Outline {
                left: ring(lo),
                right: ring(-ro),
                centre: ring(mid),
                half: w.thickness / 2.0,
                dir_start: travel(a0),
                dir_end: travel(a0 + sw),
            });
        }
    }
    let d = sub(end, start);
    let l = len(d);
    if l < 1e-6 {
        return None;
    }
    let u = mul(d, 1.0 / l);
    let nl = [-u[1], u[0]];
    let off = |k: f64| vec![add(start, mul(nl, k)), add(end, mul(nl, k))];
    Some(Outline { left: off(lo), right: off(-ro), centre: off(mid), half: w.thickness / 2.0, dir_start: u, dir_end: u })
}

/// Where two lines (a point and a direction each) cross.
fn cross_lines(p: P, u: P, q: P, v: P) -> Option<P> {
    let den = crs(u, v);
    if den.abs() < 1e-9 * len(u) * len(v) {
        return None;
    }
    let t = crs(sub(q, p), v) / den;
    Some(add(p, mul(u, t)))
}

/// The walls' outlines with their joins: two ends meeting end to end (and only two) are mitred,
/// their faces carried to where they cross; an end meeting no other, within a wall's half
/// thickness and a millimetre of its centre line, is carried to it.
fn joined(walls: &[&Wall]) -> Vec<Outline> {
    let n = walls.len();
    let own: Vec<Option<Outline>> = walls.iter().map(|w| outline(w, w.start, w.end)).collect();
    let ends: Vec<(usize, bool, P)> = (0..n)
        .filter(|i| own[*i].is_some())
        .flat_map(|i| [(i, true, walls[i].start), (i, false, walls[i].end)])
        .collect();
    let meeting = |a: usize| -> Vec<usize> {
        (0..ends.len()).filter(|&b| b != a && ends[b].0 != ends[a].0 && dist(ends[b].2, ends[a].2) <= 1.0).collect()
    };
    // T joins: the end, within a wall's half thickness (and a millimetre) of its centre line, is cut
    // on that wall's face toward it
    let mut outs: Vec<Option<Outline>> = (0..n).map(|i| outline(walls[i], walls[i].start, walls[i].end)).collect();
    for a in 0..ends.len() {
        let (i, at_start, p) = ends[a];
        if walls[i].arc != 0.0 || !meeting(a).is_empty() {
            continue;
        }
        let axis = sub(walls[i].end, walls[i].start);
        let inward = if at_start { axis } else { mul(axis, -1.0) };
        let mut best: Option<(f64, usize, usize)> = None;
        for (j, o) in own.iter().enumerate() {
            let Some(o) = o else { continue };
            if j == i {
                continue;
            }
            let c = &o.centre;
            for k in 0..c.len() - 1 {
                let (s0, s1) = (c[k], c[k + 1]);
                let ab = sub(s1, s0);
                let l2 = dot(ab, ab);
                if l2 < 1e-12 {
                    continue;
                }
                let t = dot(sub(p, s0), ab) / l2;
                if t < 0.0 || t > 1.0 || (k == 0 && t <= 1e-9) || (k == c.len() - 2 && t >= 1.0 - 1e-9) {
                    continue;
                }
                let d = dist(p, add(s0, mul(ab, t)));
                if d > o.half + 1.0 || crs(ab, inward).abs() < 1e-9 * l2.sqrt() * len(inward) {
                    continue;
                }
                if best.map(|(bd, _, _)| d < bd).unwrap_or(true) {
                    best = Some((d, j, k));
                }
            }
        }
        let Some((_, j, k)) = best else { continue };
        let Some(ob) = &own[j] else { continue };
        let ab = sub(ob.centre[k + 1], ob.centre[k]);
        let face = if crs(ab, inward) > 0.0 { &ob.left } else { &ob.right };
        let (f0, fd) = (face[k], sub(face[k + 1], face[k]));
        let Some(oa) = &mut outs[i] else { continue };
        let li = if at_start { 0 } else { oa.left.len() - 1 };
        let ri = if at_start { 0 } else { oa.right.len() - 1 };
        let (Some(ql), Some(qr)) = (cross_lines(oa.left[li], axis, f0, fd), cross_lines(oa.right[ri], axis, f0, fd)) else {
            continue;
        };
        oa.left[li] = ql;
        oa.right[ri] = qr;
    }
    // ends meeting: the first two (by id) are mitred, their faces carried to where they cross; where
    // a third wall ending there would overlap the two mitred, none is mitred, and with two of the
    // three in line the third is cut on their faces
    let face_end = |o: &Outline, at_start: bool, left: bool| -> (P, P) {
        // each face as seen going out of the joint along its wall: out of a start the left face is
        // on the left, out of an end the right face
        let f = if left == at_start { &o.left } else { &o.right };
        if at_start {
            (f[0], mul(o.dir_start, -1.0))
        } else {
            (f[f.len() - 1], o.dir_end)
        }
    };
    let set = |o: &mut Outline, at_start: bool, left: bool, q: P| {
        let f = if left == at_start { &mut o.left } else { &mut o.right };
        let k = if at_start { 0 } else { f.len() - 1 };
        f[k] = q;
    };
    let mut done = vec![false; ends.len()];
    for a in 0..ends.len() {
        if done[a] {
            continue;
        }
        let mut group = vec![a];
        group.extend(meeting(a));
        group.sort();
        for &g in &group {
            done[g] = true;
        }
        if group.len() < 2 {
            continue;
        }
        let p = ends[a].2;
        let (i, ia, _) = ends[group[0]];
        let (j, jb, _) = ends[group[1]];
        let (Some(oi), Some(oj)) = (&outs[i], &outs[j]) else { continue };
        let (p1, u1) = face_end(oi, ia, true);
        let (q1, v1) = face_end(oj, jb, false);
        let (p2, u2) = face_end(oi, ia, false);
        let (q2, v2) = face_end(oj, jb, true);
        let (Some(m1), Some(m2)) = (cross_lines(p1, u1, q1, v1), cross_lines(p2, u2, q2, v2)) else { continue };
        // a mitre running far off (walls almost in line) is left out
        let reach = 10.0 * (oi.half + oj.half).max(1.0);
        if dist(m1, p) > reach || dist(m2, p) > reach {
            continue;
        }
        let mut oi2 = oi.clone();
        let mut oj2 = oj.clone();
        set(&mut oi2, ia, true, m1);
        set(&mut oi2, ia, false, m2);
        set(&mut oj2, jb, false, m1);
        set(&mut oj2, jb, true, m2);
        // a third wall ending there that the mitred two would overlap leaves them all square
        if group.len() > 2 {
            let (pi, pj) = (polygon(&oi2), polygon(&oj2));
            let crowded = group[2..].iter().any(|&g| {
                let Some(o) = &outs[ends[g].0] else { return false };
                let q = polygon(o);
                overlap(&q, &pi) > 1e-6 || overlap(&q, &pj) > 1e-6
            });
            if crowded {
                // two of them in line butt square, and the other is cut on their faces toward it,
                // each of its faces on the face of the one of the two it runs into
                if group.len() == 3 {
                    tee_cut(&mut outs, walls, &ends, &group);
                }
                continue;
            }
        }
        outs[i] = Some(oi2);
        outs[j] = Some(oj2);
    }
    outs.into_iter().flatten().collect()
}

/// Three ends meeting where two of the walls are in line: the third is cut on their faces.
fn tee_cut(outs: &mut [Option<Outline>], walls: &[&Wall], ends: &[(usize, bool, P)], group: &[usize]) {
    let away = |o: &Outline, at_start: bool| if at_start { o.dir_start } else { mul(o.dir_end, -1.0) };
    let parallel = |x: usize, y: usize| -> bool {
        let (Some(ox), Some(oy)) = (&outs[ends[x].0], &outs[ends[y].0]) else { return false };
        let (u, v) = (away(ox, ends[x].1), away(oy, ends[y].1));
        crs(u, v).abs() < 1e-9 && dot(u, v) < 0.0
    };
    let pairs = [(0, 1, 2), (0, 2, 1), (1, 2, 0)];
    let Some(&(x, y, z)) = pairs.iter().find(|&&(x, y, _)| parallel(group[x], group[y])) else { return };
    let (gx, gy, gz) = (group[x], group[y], group[z]);
    let (iz, zs, p) = ends[gz];
    if walls[iz].arc != 0.0 {
        return;
    }
    let Some(oz) = outs[iz].clone() else { return };
    let uz = away(&oz, zs);
    // the face of each in-line wall toward the cut one, and the way that wall goes from the point
    let mut faces: Vec<(P, P, P)> = Vec::new();
    for g in [gx, gy] {
        let (i, at_start, _) = ends[g];
        let Some(o) = &outs[i] else { return };
        let a = away(o, at_start);
        // to the left of the way out is the face on the left going out of a start, the right out of an end
        let left_side = crs(a, uz) > 0.0;
        let f = if left_side == at_start { &o.left } else { &o.right };
        let (q, d) = if at_start { (f[0], sub(f[1], f[0])) } else { (f[f.len() - 1], sub(f[f.len() - 2], f[f.len() - 1])) };
        faces.push((q, d, a));
    }
    let k = |f: &Vec<P>, at_start: bool| if at_start { 0 } else { f.len() - 1 };
    let mut oz2 = oz.clone();
    for left in [true, false] {
        let fz = if left { &oz.left } else { &oz.right };
        let pz = fz[k(fz, zs)];
        let mut cut = None;
        for (q, d, a) in &faces {
            if let Some(m) = cross_lines(pz, uz, *q, *d) {
                if dot(sub(m, p), *a) >= -1e-9 {
                    cut = Some(m);
                    break;
                }
            }
        }
        if let Some(m) = cut {
            let f = if left { &mut oz2.left } else { &mut oz2.right };
            let kk = k(f, zs);
            f[kk] = m;
        }
    }
    outs[iz] = Some(oz2);
}

/// The area two convex polygons share (Sutherland-Hodgman, either winding).
fn overlap(a: &[P], b: &[P]) -> f64 {
    if a.len() < 3 || b.len() < 3 {
        return 0.0;
    }
    let sign = if area(b) < 0.0 { -1.0 } else { 1.0 };
    let mut out: Vec<P> = a.to_vec();
    for k in 0..b.len() {
        let (c0, c1) = (b[k], b[(k + 1) % b.len()]);
        let side = |p: P| sign * crs(sub(c1, c0), sub(p, c0));
        let inp = std::mem::take(&mut out);
        for m in 0..inp.len() {
            let (p, q) = (inp[m], inp[(m + 1) % inp.len()]);
            let (sp, sq) = (side(p), side(q));
            if sp >= 0.0 {
                out.push(p);
            }
            if (sp >= 0.0) != (sq >= 0.0) {
                let t = sp / (sp - sq);
                out.push(add(p, mul(sub(q, p), t)));
            }
        }
        if out.is_empty() {
            return 0.0;
        }
    }
    area(&out).abs()
}

fn polygon(o: &Outline) -> Vec<P> {
    let mut p = o.left.clone();
    p.extend(o.right.iter().rev());
    p
}

// ---------------------------------------------------------------- the plan's faces

struct Plan {
    walls: Vec<Vec<P>>,
    verts: Vec<P>,
    /// Each cycle of half-edges: its vertices, signed area and the component it belongs to.
    cycles: Vec<(Vec<usize>, f64, usize)>,
    taken: Vec<usize>,
}

impl Plan {
    fn of_level(m: &Model, level: &str) -> Plan {
        let (elev, ch) = m.levels.get(level).copied().unwrap_or((0.0, 1200.0));
        let cut = elev + ch;
        let walls: Vec<&Wall> = m.walls.iter().filter(|w| w.bounding && w.base <= cut && cut < w.top).collect();
        let outlines = joined(&walls);
        let polys: Vec<Vec<P>> = outlines.iter().map(polygon).collect();
        let mut segs: Vec<(P, P)> = Vec::new();
        for p in &polys {
            for k in 0..p.len() {
                segs.push((p[k], p[(k + 1) % p.len()]));
            }
        }
        for (l, s, t) in &m.separators {
            if l == level {
                segs.push((*s, *t));
            }
        }
        let (verts, cycles) = faces(&segs);
        Plan { walls: polys, verts, cycles, taken: Vec::new() }
    }

    fn ring(&self, c: usize) -> Vec<P> {
        self.cycles[c].0.iter().map(|i| self.verts[*i]).collect()
    }

    /// The room around a point: its area (mm²) and perimeter (mm), if it is enclosed and no room
    /// has its face already.
    fn room_at(&mut self, q: P) -> Option<(f64, f64)> {
        if self.walls.iter().any(|w| inside(w, q)) {
            return None;
        }
        let mut best: Option<(usize, f64)> = None;
        for (c, (_, a, _)) in self.cycles.iter().enumerate() {
            if *a <= 1e-6 {
                continue;
            }
            if inside(&self.ring(c), q) && best.map(|(_, ba)| *a < ba).unwrap_or(true) {
                best = Some((c, *a));
            }
        }
        let (f, _) = best?;
        if self.taken.contains(&f) {
            return None;
        }
        self.taken.push(f);
        // measured from the vertex the face was found from, as the original sums it
        let outer = self.ring(f);
        let comp = self.cycles[f].2;
        let mut a = area(&outer);
        let mut p = perimeter(&outer);
        for (h, (vs, ha, hc)) in self.cycles.iter().enumerate() {
            if *ha >= -1e-6 || *hc == comp {
                continue;
            }
            let v = self.verts[vs[0]];
            if !inside(&outer, v) {
                continue;
            }
            // the face holding the hole directly: the smallest of the other components' faces round it
            let mut holder: Option<(usize, f64)> = None;
            for (c, (_, ca, cc)) in self.cycles.iter().enumerate() {
                if *ca <= 1e-6 || *cc == *hc {
                    continue;
                }
                if inside(&self.ring(c), v) && holder.map(|(_, ba)| *ca < ba).unwrap_or(true) {
                    holder = Some((c, *ca));
                }
            }
            if holder.map(|(c, _)| c) != Some(f) {
                continue;
            }
            let ring = self.ring(h);
            a -= ha.abs();
            p += perimeter(&ring);
        }
        Some((a, p))
    }
}

fn key(p: P) -> (i64, i64) {
    ((p[0] * 1e4).round() as i64, (p[1] * 1e4).round() as i64)
}

/// Where segment b meets segment a, as parameters along a.
fn meet(a0: P, a1: P, b0: P, b1: P) -> Vec<f64> {
    let d = sub(a1, a0);
    let e = sub(b1, b0);
    let l2 = dot(d, d);
    if l2 < 1e-12 {
        return vec![];
    }
    let den = crs(d, e);
    let mut out = Vec::new();
    if den.abs() < 1e-9 * l2.sqrt() * len(e).max(1e-12) {
        // parallel: lying along each other they don't split each other
        return out;
    }
    let w = sub(b0, a0);
    let t = crs(w, e) / den;
    let u = crs(w, d) / den;
    let tl = 1e-9;
    if t > -tl && t < 1.0 + tl && u > -tl && u < 1.0 + tl {
        out.push(t.clamp(0.0, 1.0));
    }
    out
}

/// The cycles the segments make: each with its vertices, signed area and connected component.
fn faces(segs: &[(P, P)]) -> (Vec<P>, Vec<(Vec<usize>, f64, usize)>) {
    let mut pieces: Vec<(P, P)> = Vec::new();
    for (i, s) in segs.iter().enumerate() {
        let mut ts = vec![0.0, 1.0];
        for (j, o) in segs.iter().enumerate() {
            if i != j {
                ts.extend(meet(s.0, s.1, o.0, o.1));
            }
        }
        ts.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        // a point where another meets this one at an end is that end itself
        let pt = |t: f64| {
            let q = add(s.0, mul(sub(s.1, s.0), t));
            if t <= 0.0 || key(q) == key(s.0) {
                s.0
            } else if t >= 1.0 || key(q) == key(s.1) {
                s.1
            } else {
                q
            }
        };
        for w in ts.windows(2) {
            let (a, b) = (pt(w[0]), pt(w[1]));
            if key(a) != key(b) {
                pieces.push((a, b));
            }
        }
    }
    let mut verts: Vec<P> = Vec::new();
    let mut vid: HashMap<(i64, i64), usize> = HashMap::new();
    let mut edges: std::collections::BTreeSet<(usize, usize)> = std::collections::BTreeSet::new();
    for (a, b) in pieces {
        let ia = *vid.entry(key(a)).or_insert_with(|| {
            verts.push(a);
            verts.len() - 1
        });
        let ib = *vid.entry(key(b)).or_insert_with(|| {
            verts.push(b);
            verts.len() - 1
        });
        if ia != ib {
            edges.insert((ia.min(ib), ia.max(ib)));
        }
    }
    // connected components
    let mut parent: Vec<usize> = (0..verts.len()).collect();
    fn root(p: &mut Vec<usize>, x: usize) -> usize {
        let mut r = x;
        while p[r] != r {
            r = p[r];
        }
        let mut y = x;
        while p[y] != r {
            let n = p[y];
            p[y] = r;
            y = n;
        }
        r
    }
    for &(a, b) in &edges {
        let (ra, rb) = (root(&mut parent, a), root(&mut parent, b));
        if ra != rb {
            parent[ra] = rb;
        }
    }
    let mut out: Vec<Vec<usize>> = vec![Vec::new(); verts.len()];
    for &(a, b) in &edges {
        out[a].push(b);
        out[b].push(a);
    }
    let ang = |a: usize, b: usize| (verts[b][1] - verts[a][1]).atan2(verts[b][0] - verts[a][0]);
    for (a, o) in out.iter_mut().enumerate() {
        o.sort_by(|x, y| ang(a, *x).partial_cmp(&ang(a, *y)).unwrap_or(std::cmp::Ordering::Equal));
    }
    let mut used: std::collections::HashSet<(usize, usize)> = std::collections::HashSet::new();
    let mut cycles = Vec::new();
    for a in 0..verts.len() {
        for &b in &out[a] {
            if used.contains(&(a, b)) {
                continue;
            }
            let mut cyc = vec![a];
            let (mut u, mut v) = (a, b);
            let mut steps = 0;
            loop {
                used.insert((u, v));
                let o = &out[v];
                let k = o.iter().position(|x| *x == u).unwrap_or(0);
                let w = o[(k + o.len() - 1) % o.len()];
                u = v;
                v = w;
                if u == a && v == b {
                    break;
                }
                cyc.push(u);
                steps += 1;
                if steps > 4 * edges.len() + 4 {
                    break;
                }
            }
            let pts: Vec<P> = cyc.iter().map(|i| verts[*i]).collect();
            let comp = root(&mut parent, a);
            cycles.push((cyc, area(&pts), comp));
        }
    }
    (verts, cycles)
}
