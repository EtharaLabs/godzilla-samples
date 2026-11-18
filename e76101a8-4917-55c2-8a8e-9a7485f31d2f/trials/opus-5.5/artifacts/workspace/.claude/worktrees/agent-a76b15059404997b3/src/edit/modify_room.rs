//! A room frozen by `modify` keeps the boundary it has now: its region at the bounding lines (the
//! walls' centre lines, room separation lines, columns' outlines) and at their faces, as the room
//! solver finds them. This is a stand-in for the room solver of the architecture part, for rooms
//! bounded by straight walls, room separation lines and rectangular columns.
//!
//! The lines are put in order (walls by id, then separation lines, then columns), split where they
//! meet, and each region's boundary is walked with the region on its left (turning as far right
//! as it can at each meeting point), from the first piece of the first line on it; a hole's walk
//! is reversed. The faces follow the walls' faces (each wall's face runs between the corners where
//! it meets the walls joined to it, end to end or on their side): where one wall's run gives way
//! to the next, the corner is where the next face meets this one's line, found along the next
//! face from its start (as the original finds it, to the last digit for square plans). Curved
//! walls and round columns are beyond this stand-in.

use crate::json::Value;
use crate::project::Project;

const EPS: f64 = 1e-6;

type P = [f64; 2];

struct Seg {
    a: P,
    b: P,
    half: f64,
    /// Its faces, left then right, each from the corner at its start to the corner at its end
    /// (where the walls it's joined to meet them); a line with no thickness is its own face.
    faces: [[P; 2]; 2],
}

fn seg(a: P, b: P, half: f64) -> Seg {
    Seg { a, b, half, faces: [[a, b], [a, b]] }
}

/// Where two lines meet (each a point and a direction); None for parallel ones.
fn meet(p1: P, d1: P, p2: P, d2: P) -> Option<P> {
    let den = cross(d1, d2);
    if den.abs() <= EPS * EPS * dot(d1, d1).sqrt() * dot(d2, d2).sqrt() {
        return None;
    }
    let s = cross(sub(p2, p1), d2) / den;
    Some([p1[0] + d1[0] * s, p1[1] + d1[1] * s])
}

/// A wall's face line on a side (1 left, -1 right): a point of it and its direction.
fn face_line(s: &Seg, side: f64) -> (P, P) {
    let d = sub(s.b, s.a);
    let l = dot(d, d).sqrt();
    let n = [-d[1] / l, d[0] / l];
    ([s.a[0] + n[0] * s.half * side, s.a[1] + n[1] * s.half * side], d)
}

/// The walls' faces, each ending where it meets the face of the wall joined to it: end to end
/// (the faces on the same side of the chain), or ending on another wall's side (its face toward
/// it); a free end squares off.
fn wall_faces(walls: &mut [(P, P, Seg)]) {
    let ends: Vec<[P; 2]> = walls.iter().map(|(s, e, _)| [*s, *e]).collect();
    let mut all: Vec<[[P; 2]; 2]> = Vec::new();
    for i in 0..walls.len() {
        let mut faces = [[[0.0; 2]; 2]; 2];
        for (fi, side) in [(0usize, 1.0f64), (1, -1.0)] {
            let (fp, fd) = face_line(&walls[i].2, side);
            for k in 0..2 {
                let q = ends[i][k];
                let centre_end = if k == 0 { walls[i].2.a } else { walls[i].2.b };
                let cap = {
                    let d = sub(walls[i].2.b, walls[i].2.a);
                    let l = dot(d, d).sqrt();
                    [centre_end[0] - d[1] / l * walls[i].2.half * side, centre_end[1] + d[0] / l * walls[i].2.half * side]
                };
                let others: Vec<(usize, usize)> = (0..walls.len())
                    .filter(|j| *j != i)
                    .flat_map(|j| { let ej = ends[j]; (0..2usize).filter(move |kj| near(ej[*kj], q)).map(move |kj| (j, kj)) })
                    .collect();
                let corner = if others.len() == 1 {
                    let (j, kj) = others[0];
                    let same = (k == 1 && kj == 0) || (k == 0 && kj == 1);
                    let (op, od) = face_line(&walls[j].2, if same { side } else { -side });
                    meet(fp, fd, op, od).unwrap_or(cap)
                } else if others.is_empty() {
                    // a wall ending on another's side stops at its face
                    let mut c = cap;
                    for j in 0..walls.len() {
                        if j == i {
                            continue;
                        }
                        let (ja, jb) = (walls[j].2.a, walls[j].2.b);
                        let dj = sub(jb, ja);
                        let lj = dot(dj, dj);
                        let w = sub(centre_end, ja);
                        let t = dot(w, dj) / lj;
                        if t <= 0.0 || t >= 1.0 || cross(dj, w).abs() / lj.sqrt() > EPS {
                            continue;
                        }
                        let other_end = if k == 0 { walls[i].2.b } else { walls[i].2.a };
                        let toward = if cross(dj, sub(other_end, ja)) >= 0.0 { 1.0 } else { -1.0 };
                        let (op, od) = face_line(&walls[j].2, toward);
                        c = meet(fp, fd, op, od).unwrap_or(cap);
                        break;
                    }
                    c
                } else {
                    cap
                };
                faces[fi][k] = corner;
            }
        }
        all.push(faces);
    }
    for (w, f) in walls.iter_mut().zip(all) {
        w.2.faces = f;
    }
}

fn pt(v: Option<&Value>) -> Option<P> {
    let a = v?.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

fn guid_el(pr: &Project, v: Option<&Value>) -> Option<u64> {
    pr.find_guid(v?.as_str()?)
}

fn elev(pr: &Project, id: u64) -> f64 {
    crate::model::elev(pr, id)
}

fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
fn cross(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
fn near(a: P, b: P) -> bool {
    (a[0] - b[0]).abs() <= EPS && (a[1] - b[1]).abs() <= EPS
}

/// A wall type's thickness and layers (function, thickness).
fn wall_type(pr: &Project, w: &Value) -> Option<(f64, Vec<(String, f64)>)> {
    let name = pr.lib_name(w.get("type")?.as_str()?)?;
    let ty = pr.section("types")?.get("wall")?.get(&name)?;
    let mut layers = Vec::new();
    if let Some(a) = ty.get("layers").and_then(|l| l.as_arr()) {
        for l in a {
            let f = l.get("function").and_then(|x| x.as_str()).unwrap_or("structure").to_string();
            let t = l.get("thickness").and_then(|x| x.as_f64()).unwrap_or(0.0);
            layers.push((f, t));
        }
    }
    let t = ty.get("thickness").and_then(|x| x.as_f64()).unwrap_or_else(|| layers.iter().map(|(_, t)| *t).sum());
    Some((t, layers))
}

/// The lines that bound rooms on a level at its computation height, in the solver's order.
fn bounding(pr: &Project, level: u64) -> Option<Vec<Seg>> {
    let lv = pr.el(level)?;
    let z = elev(pr, level) + lv.get("computation_height").and_then(|x| x.as_f64()).unwrap_or(1200.0);
    let mut out = Vec::new();
    let mut walls: Vec<(P, P, Seg)> = Vec::new();
    for (_, w) in pr.elements.iter().filter(|(_, e)| e.get("category").and_then(|c| c.as_str()) == Some("wall")) {
        if w.get("room_bounding").and_then(|b| b.as_bool()) == Some(false) {
            continue;
        }
        let Some(wl) = guid_el(pr, w.get("level")) else { continue };
        let base = elev(pr, wl) + w.get("base_offset").and_then(|x| x.as_f64()).unwrap_or(0.0);
        let top = match guid_el(pr, w.get("top_level")) {
            Some(tl) => elev(pr, tl) + w.get("top_offset").and_then(|x| x.as_f64()).unwrap_or(0.0),
            None => base + w.get("height").and_then(|x| x.as_f64()).unwrap_or(0.0),
        };
        if !(base <= z && z < top) {
            continue;
        }
        if w.get("arc").and_then(|a| a.as_f64()).unwrap_or(0.0) != 0.0 {
            return None;
        }
        let (Some(s), Some(e)) = (pt(w.get("start")), pt(w.get("end"))) else { continue };
        let (t, layers) = wall_type(pr, w)?;
        let loc = w.get("location").and_then(|l| l.as_str()).unwrap_or("centre");
        let d = super::modify::location_offset(loc, t, &layers);
        let dir = sub(e, s);
        let len = dot(dir, dir).sqrt();
        if len <= EPS {
            continue;
        }
        let n = [-dir[1] / len, dir[0] / len];
        let a = [s[0] - n[0] * d, s[1] - n[1] * d];
        let b = [e[0] - n[0] * d, e[1] - n[1] * d];
        walls.push((s, e, seg(a, b, t / 2.0)));
    }
    // two walls joined end to end meet where their centre lines do
    let ends: Vec<[P; 2]> = walls.iter().map(|(s, e, _)| [*s, *e]).collect();
    for i in 0..walls.len() {
        for k in 0..2 {
            let q = ends[i][k];
            let others: Vec<usize> = (0..walls.len()).filter(|j| *j != i && (near(ends[*j][0], q) || near(ends[*j][1], q))).collect();
            if others.len() != 1 {
                continue;
            }
            let j = others[0];
            let (ai, bi) = (walls[i].2.a, walls[i].2.b);
            let (aj, bj) = (walls[j].2.a, walls[j].2.b);
            let mine = if k == 0 { ai } else { bi };
            if near(mine, aj) || near(mine, bj) {
                continue;
            }
            let d1 = sub(bi, ai);
            let d2 = sub(bj, aj);
            let den = cross(d1, d2);
            if den.abs() <= EPS {
                continue;
            }
            let u = cross(sub(aj, ai), d2) / den;
            let x = [ai[0] + d1[0] * u, ai[1] + d1[1] * u];
            if k == 0 {
                walls[i].2.a = x;
            } else {
                walls[i].2.b = x;
            }
        }
    }
    wall_faces(&mut walls);
    out.extend(walls.into_iter().map(|(_, _, s)| s));
    for (_, r) in pr.elements.iter().filter(|(_, e)| e.get("category").and_then(|c| c.as_str()) == Some("roomseparator")) {
        if guid_el(pr, r.get("level")) != Some(level) {
            continue;
        }
        let (Some(a), Some(b)) = (pt(r.get("start")), pt(r.get("end"))) else { continue };
        out.push(seg(a, b, 0.0));
    }
    for (_, c) in pr.elements.iter().filter(|(_, e)| {
        matches!(e.get("category").and_then(|c| c.as_str()), Some("column") | Some("structuralcolumn"))
    }) {
        if c.get("room_bounding").and_then(|b| b.as_bool()) == Some(false) {
            continue;
        }
        let Some(cl) = guid_el(pr, c.get("level")) else { continue };
        let base = elev(pr, cl) + c.get("base_offset").and_then(|x| x.as_f64()).unwrap_or(0.0);
        let top = match guid_el(pr, c.get("top_level")) {
            Some(tl) => elev(pr, tl),
            None => base + c.get("height").and_then(|x| x.as_f64()).unwrap_or(0.0),
        };
        if !(base <= z && z < top) {
            continue;
        }
        let cat = c.get("category").and_then(|x| x.as_str()).unwrap_or("column");
        let sec = if cat == "column" { "column" } else { "structural_column" };
        let name = c.get("type").and_then(|t| t.as_str()).and_then(|g| pr.lib_name(g))?;
        let ty = pr.section("types")?.get(sec)?.get(&name)?;
        if ty.get("round").and_then(|r| r.as_bool()).unwrap_or(false) {
            return None;
        }
        let w = ty.get("width").and_then(|x| x.as_f64()).unwrap_or(0.0) / 2.0;
        let dd = ty.get("depth").and_then(|x| x.as_f64()).unwrap_or(0.0) / 2.0;
        let at = pt(c.get("at"))?;
        let ang = c.get("angle").and_then(|a| a.as_f64()).unwrap_or(0.0).to_radians();
        let (sn, cs) = ang.sin_cos();
        let corner = |x: f64, y: f64| -> P { [at[0] + x * cs - y * sn, at[1] + x * sn + y * cs] };
        let k = [corner(-w, -dd), corner(w, -dd), corner(w, dd), corner(-w, dd)];
        for i in 0..4 {
            out.push(seg(k[i], k[(i + 1) % 4], 0.0));
        }
    }
    Some(out)
}

struct Arr {
    verts: Vec<P>,
    /// Half-edges: (from, to, owner segment); 2k forward along the segment, 2k + 1 back.
    he: Vec<(usize, usize, usize)>,
}

fn vertex(verts: &mut Vec<P>, p: P) -> usize {
    if let Some(i) = verts.iter().position(|v| near(*v, p)) {
        return i;
    }
    verts.push(p);
    verts.len() - 1
}

/// The segments split where they meet.
fn arrange(segs: &[Seg]) -> Arr {
    let mut verts: Vec<P> = Vec::new();
    let mut he: Vec<(usize, usize, usize)> = Vec::new();
    let mut seen: Vec<(usize, usize)> = Vec::new();
    for (i, s) in segs.iter().enumerate() {
        let d = sub(s.b, s.a);
        let l2 = dot(d, d);
        if l2 <= EPS * EPS {
            continue;
        }
        let mut ts: Vec<f64> = vec![0.0, 1.0];
        for (j, o) in segs.iter().enumerate() {
            if i == j {
                continue;
            }
            let e = sub(o.b, o.a);
            let den = cross(d, e);
            if den.abs() > EPS * EPS {
                let w = sub(o.a, s.a);
                let t = cross(w, e) / den;
                let u = cross(w, d) / den;
                let tol_t = EPS / l2.sqrt();
                let tol_u = EPS / dot(e, e).sqrt();
                if t > -tol_t && t < 1.0 + tol_t && u > -tol_u && u < 1.0 + tol_u {
                    ts.push(t.clamp(0.0, 1.0));
                }
            } else {
                // parallel: the other's ends on this one
                for q in [o.a, o.b] {
                    let w = sub(q, s.a);
                    if cross(d, w).abs() / l2.sqrt() <= EPS {
                        let t = dot(w, d) / l2;
                        if t > 0.0 && t < 1.0 {
                            ts.push(t);
                        }
                    }
                }
            }
        }
        ts.sort_by(|a, b| a.total_cmp(b));
        let mut pts: Vec<usize> = Vec::new();
        for t in ts {
            let p = if t == 0.0 {
                s.a
            } else if t == 1.0 {
                s.b
            } else {
                [s.a[0] + d[0] * t, s.a[1] + d[1] * t]
            };
            let v = vertex(&mut verts, p);
            if pts.last() != Some(&v) {
                pts.push(v);
            }
        }
        for w in pts.windows(2) {
            let key = (w[0].min(w[1]), w[0].max(w[1]));
            if seen.contains(&key) {
                continue;
            }
            seen.push(key);
            he.push((w[0], w[1], i));
            he.push((w[1], w[0], i));
        }
    }
    Arr { verts, he }
}

fn angle(arr: &Arr, h: usize) -> f64 {
    let (a, b, _) = arr.he[h];
    let d = sub(arr.verts[b], arr.verts[a]);
    d[1].atan2(d[0])
}

/// The boundary walks: each half-edge's next with its region on the left.
fn cycles(arr: &Arr) -> Vec<Vec<usize>> {
    let n = arr.he.len();
    let mut out_of: Vec<Vec<usize>> = vec![Vec::new(); arr.verts.len()];
    for h in 0..n {
        out_of[arr.he[h].0].push(h);
    }
    for list in out_of.iter_mut() {
        list.sort_by(|a, b| angle(arr, *a).total_cmp(&angle(arr, *b)));
    }
    let twin = |h: usize| h ^ 1;
    let next = |h: usize| -> usize {
        let v = arr.he[h].1;
        let list = &out_of[v];
        let t = twin(h);
        let i = list.iter().position(|x| *x == t).unwrap_or(0);
        list[(i + list.len() - 1) % list.len()]
    };
    let mut done = vec![false; n];
    let mut out = Vec::new();
    for h in 0..n {
        if done[h] {
            continue;
        }
        let mut c = Vec::new();
        let mut x = h;
        while !done[x] {
            done[x] = true;
            c.push(x);
            x = next(x);
        }
        out.push(c);
    }
    out
}

fn area(arr: &Arr, c: &[usize]) -> f64 {
    let mut s = 0.0;
    for h in c {
        let (a, b, _) = arr.he[*h];
        s += cross(arr.verts[a], arr.verts[b]);
    }
    s / 2.0
}

fn inside(poly: &[P], p: P) -> bool {
    let mut c = false;
    let n = poly.len();
    for i in 0..n {
        let a = poly[i];
        let b = poly[(i + n - 1) % n];
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let x = (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0];
            if p[0] < x {
                c = !c;
            }
        }
    }
    c
}

/// A walk from its first piece (the lowest half-edge), as half-edges.
fn from_first(c: &[usize]) -> Vec<usize> {
    let i = (0..c.len()).min_by_key(|i| c[*i]).unwrap_or(0);
    c[i..].iter().chain(c[..i].iter()).copied().collect()
}

fn pts_of(arr: &Arr, c: &[usize]) -> Vec<P> {
    c.iter().map(|h| arr.verts[arr.he[*h].0]).collect()
}

/// A walk's faces: each run of one line offset to its left by its half thickness, meeting the next.
fn faces(arr: &Arr, segs: &[Seg], c: &[usize]) -> Vec<P> {
    let n = c.len();
    // the face a half-edge runs along, from where it starts to where it ends as walked: the
    // line's left face going its way, its right face going back
    let face = |h: usize| -> (P, P) {
        let (a, b, o) = arr.he[h];
        let s = &segs[o];
        let fwd = dot(sub(arr.verts[b], arr.verts[a]), sub(s.b, s.a)) > 0.0;
        if fwd {
            (s.faces[0][0], s.faces[0][1])
        } else {
            (s.faces[1][1], s.faces[1][0])
        }
    };
    let mut out = Vec::new();
    for k in 0..n {
        let hp = c[(k + n - 1) % n];
        let h = c[k];
        let (_, _, op) = arr.he[hp];
        let (_, _, o) = arr.he[h];
        // the same wall going on: no corner here (a line of no thickness keeps its points)
        if op == o && (hp ^ 1) != h && (hp & 1) == (h & 1) && segs[o].half > 0.0 {
            continue;
        }
        let (a0, a1) = face(hp);
        let (b0, b1) = face(h);
        let da = sub(a1, a0);
        let db = sub(b1, b0);
        let den = cross(db, da);
        if den.abs() <= EPS * EPS * dot(da, da).sqrt() * dot(db, db).sqrt() {
            // in line (or back on itself, round a free end): the point off each line's side
            let v = arr.verts[arr.he[h].0];
            let off = |hh: usize| -> P {
                let (x, y, oo) = arr.he[hh];
                let d = sub(arr.verts[y], arr.verts[x]);
                let l = dot(d, d).sqrt();
                let t = segs[oo].half;
                [v[0] - d[1] / l * t, v[1] + d[0] / l * t]
            };
            let (pa, pb) = (off(hp), off(h));
            out.push(pa);
            if !near(pa, pb) {
                out.push(pb);
            }
            continue;
        }
        // where the next face meets this one's line, along the next face from its start
        let u = cross(sub(a0, b0), da) / den;
        out.push([b0[0] + u * db[0], b0[1] + u * db[1]]);
    }
    out
}

fn region(outer: Vec<P>, holes: Vec<Vec<P>>) -> Value {
    let pv = |p: &P| Value::Arr(vec![Value::f(p[0]), Value::f(p[1])]);
    jobj! {
        "outer" => Value::Arr(outer.iter().map(pv).collect()),
        "holes" => Value::Arr(holes.iter().map(|h| Value::Arr(h.iter().map(pv).collect())).collect()),
    }
}

/// What the solver says of a room's boundary now.
pub enum Kept {
    /// {centre, finish}, as `kept` holds them.
    Found(Value),
    /// Not enclosed, or in a space another room has first.
    Unbounded,
    /// What this stand-in can't work out (curved walls, round columns).
    Unknown,
}

/// The boundary a room has now.
pub fn kept(pr: &Project, id: u64, room: &Value) -> Kept {
    match solve(pr, id, room) {
        Ok(v) => Kept::Found(v),
        Err(true) => Kept::Unbounded,
        Err(false) => Kept::Unknown,
    }
}

/// Err(true): unbounded; Err(false): unknown.
fn solve(pr: &Project, id: u64, room: &Value) -> Result<Value, bool> {
    let level = guid_el(pr, room.get("level")).ok_or(false)?;
    let p = pt(room.get("point")).ok_or(false)?;
    let segs = bounding(pr, level).ok_or(false)?;
    let arr = arrange(&segs);
    let cs = cycles(&arr);
    // the smallest region round the point
    let mut best: Option<(f64, usize)> = None;
    for (i, c) in cs.iter().enumerate() {
        let a = area(&arr, c);
        if a <= EPS {
            continue;
        }
        if inside(&pts_of(&arr, c), p) && best.map(|(ba, _)| a < ba).unwrap_or(true) {
            best = Some((a, i));
        }
    }
    let (_, oi) = best.ok_or(true)?;
    let outer = &cs[oi];
    let outer_pts = pts_of(&arr, outer);
    // islands inside it: walks the other way round, not inside another island
    let mut holes: Vec<usize> = Vec::new();
    for (i, c) in cs.iter().enumerate() {
        if i == oi || area(&arr, c) >= -EPS {
            continue;
        }
        // an island stands apart: none of its points on the region's boundary
        let ps = pts_of(&arr, c);
        if ps.iter().all(|q| inside(&outer_pts, *q) && !outer_pts.iter().any(|o| near(*o, *q))) {
            holes.push(i);
        }
    }
    let hole_pts: Vec<Vec<P>> = holes.iter().map(|i| pts_of(&arr, &cs[*i])).collect();
    let keep: Vec<usize> = holes
        .iter()
        .enumerate()
        .filter(|(k, _)| {
            let q = hole_pts[*k][0];
            !hole_pts.iter().enumerate().any(|(j, hp)| j != *k && inside(hp, q))
        })
        .map(|(_, i)| *i)
        .collect();
    for i in &keep {
        if inside(&pts_of(&arr, &cs[*i]), p) {
            return Err(true);
        }
    }
    // a space another room has first is that room's
    for (oid, e) in pr.elements.range(..id) {
        if e.get("category").and_then(|c| c.as_str()) != Some("room") || guid_el(pr, e.get("level")) != Some(level) {
            continue;
        }
        let _ = oid;
        if let Some(q) = pt(e.get("point")) {
            if inside(&outer_pts, q) && !keep.iter().any(|i| inside(&pts_of(&arr, &cs[*i]), q)) {
                return Err(true);
            }
        }
    }
    let first = from_first(outer);
    let mut hs: Vec<Vec<usize>> = keep.iter().map(|i| from_first(&cs[*i])).collect();
    hs.sort_by_key(|h| h[0]);
    let centre_holes: Vec<Vec<P>> = hs
        .iter()
        .map(|h| {
            let mut v = pts_of(&arr, h);
            v.reverse();
            v
        })
        .collect();
    let finish_holes: Vec<Vec<P>> = hs
        .iter()
        .map(|h| {
            let mut v = faces(&arr, &segs, h);
            v.reverse();
            v
        })
        .collect();
    Ok(jobj! {
        "centre" => region(pts_of(&arr, &first), centre_holes),
        "finish" => region(faces(&arr, &segs, &first), finish_holes),
    })
}
