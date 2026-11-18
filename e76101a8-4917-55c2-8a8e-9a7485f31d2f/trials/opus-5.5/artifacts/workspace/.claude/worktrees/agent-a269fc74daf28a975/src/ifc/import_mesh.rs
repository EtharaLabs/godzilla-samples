//! Bodies as the triangles a family's mesh form holds: each face cut into triangles by ear
//! clipping, an extrusion as prisms (its profile's holes cut out of it in pieces, one side of
//! each hole edge at a time), a swept disk as a cylinder along each straight piece of its
//! directrix, a block as a box; each item with the style that colours it.

use super::import_geom::{self as geom, add, cross, dot, mul, norm, sub, unit, Tf, V2, V3};
use super::import_model::Model;
use super::step::{Entity, P};

pub type Tri = [V3; 3];

/// Segments in a full circle, in a mesh.
pub const SEGMENTS: usize = 24;

/// The triangles of an item, and the styled item that colours them (one a mapped item carries
/// wins over the ones in its map).
pub struct Part {
    pub style: Option<u64>,
    pub tris: Vec<Tri>,
}

/// The parts of a product's `Body`, in the project's coordinates.
pub fn body_parts(m: &Model, pid: u64) -> Vec<Part> {
    let mut out = Vec::new();
    let e = match m.get(pid) {
        Some(e) => e,
        None => return out,
    };
    let tf = geom::product_tf(m, pid);
    for rep in geom::rep_items(m, e, "Body") {
        if let Some(re) = m.get(rep) {
            for it in re.p(3).refs() {
                item(m, it, &tf, None, false, &mut out, 0);
            }
        }
    }
    out
}

/// `over`: the style that colours the item (with `fixed`, as a mapped item gives it: what is
/// inside its map is coloured as it is, or not at all).
fn item(m: &Model, id: u64, tf: &Tf, over: Option<u64>, fixed: bool, out: &mut Vec<Part>, depth: usize) {
    if depth > 32 {
        return;
    }
    let e = match m.get(id) {
        Some(e) => e,
        None => return,
    };
    let style = if fixed { over } else { over.or_else(|| m.styled.get(&id).copied()) };
    let mut push = |tris: Vec<Tri>| {
        if !tris.is_empty() {
            out.push(Part { style, tris });
        }
    };
    match e.name.as_str() {
        "IFCTRIANGULATEDFACESET" | "IFCTRIANGULATEDIRREGULARNETWORK" => {
            // (Coordinates, Normals, Closed, CoordIndex, PnIndex)
            let pts = match e.p(0).r().and_then(|r| point_list(m, r, tf)) {
                Some(p) => p,
                None => return,
            };
            let pn = ints(e.p(4));
            let mut tris = Vec::new();
            for t in index_lists(e.p(3)) {
                let v: Option<Vec<V3>> = t.iter().map(|i| at(&pts, &pn, *i)).collect();
                if let Some(v) = v {
                    if v.len() == 3 {
                        tris.push([v[0], v[1], v[2]]);
                    }
                }
            }
            push(tris);
        }
        "IFCPOLYGONALFACESET" => {
            // (Coordinates, Closed, Faces, PnIndex)
            let pts = match e.p(0).r().and_then(|r| point_list(m, r, tf)) {
                Some(p) => p,
                None => return,
            };
            let pn = ints(e.p(3));
            let mut tris = Vec::new();
            for f in e.p(2).refs() {
                let fe = match m.get(f) {
                    Some(x) => x,
                    None => continue,
                };
                let idx = ints(fe.p(0));
                let v: Option<Vec<V3>> = idx.iter().map(|i| at(&pts, &pn, *i)).collect();
                if let Some(v) = v {
                    tris.extend(ear_clip(&v));
                }
            }
            push(tris);
        }
        "IFCFACETEDBREP" | "IFCFACETEDBREPWITHVOIDS" | "IFCADVANCEDBREP" | "IFCADVANCEDBREPWITHVOIDS" => {
            let mut tris = Vec::new();
            if let Some(sh) = e.p(0).r() {
                shell(m, sh, tf, &mut tris);
            }
            push(tris);
        }
        "IFCSHELLBASEDSURFACEMODEL" | "IFCFACEBASEDSURFACEMODEL" => {
            let mut tris = Vec::new();
            for sh in e.p(0).refs() {
                shell(m, sh, tf, &mut tris);
            }
            push(tris);
        }
        "IFCCLOSEDSHELL" | "IFCOPENSHELL" | "IFCCONNECTEDFACESET" => {
            let mut tris = Vec::new();
            shell(m, id, tf, &mut tris);
            push(tris);
        }
        "IFCEXTRUDEDAREASOLID" | "IFCEXTRUDEDAREASOLIDTAPERED" => {
            push(extrusion(m, e, tf).unwrap_or_default());
        }
        "IFCBLOCK" => {
            // (Position, XLength, YLength, ZLength)
            let pos = e.p(0).r().map(|r| geom::axis_placement(m, r)).unwrap_or(Tf::ID);
            let s = m.scale;
            let (x, y, z) = (e.p(1).num().unwrap_or(0.0) * s, e.p(2).num().unwrap_or(0.0) * s, e.p(3).num().unwrap_or(0.0) * s);
            let poly = vec![[0.0, 0.0], [x, 0.0], [x, y], [0.0, y]];
            push(prism(&poly, &tf.then(&pos), [0.0, 0.0, 1.0], z));
        }
        "IFCSWEPTDISKSOLID" => {
            // (Directrix, Radius, InnerRadius, StartParam, EndParam): a cylinder along each piece
            let r = e.p(1).num().unwrap_or(0.0) * m.scale;
            let pts = match e.p(0).r().and_then(|c| curve(m, c)) {
                Some(p) => p,
                None => return,
            };
            let circle = circle_points(r);
            let mut tris = Vec::new();
            for w in pts.windows(2) {
                let (a, b) = (tf.apply(w[0]), tf.apply(w[1]));
                let len = norm(sub(b, a));
                if len < 1e-9 {
                    continue;
                }
                let d = unit(sub(b, a));
                let mut x = cross([0.0, 0.0, 1.0], d);
                if norm(x) < 1e-9 {
                    x = [1.0, 0.0, 0.0];
                }
                let x = unit(x);
                let y = cross(d, x);
                let frame = Tf { x, y, z: d, t: a };
                tris.extend(prism(&circle, &frame, [0.0, 0.0, 1.0], len));
            }
            push(tris);
        }
        "IFCCSGSOLID" => {
            if let Some(r) = e.p(0).r() {
                item(m, r, tf, style, fixed, out, depth + 1);
            }
        }
        "IFCBOOLEANRESULT" | "IFCBOOLEANCLIPPINGRESULT" => {
            // what is taken away is left out; a union keeps both
            let op = e.p(0).enm().unwrap_or("");
            if let Some(r) = e.p(1).r() {
                item(m, r, tf, style, fixed, out, depth + 1);
            }
            if op == "UNION" {
                if let Some(r) = e.p(2).r() {
                    item(m, r, tf, style, fixed, out, depth + 1);
                }
            }
        }
        "IFCMAPPEDITEM" => {
            // (MappingSource: IfcRepresentationMap(MappingOrigin, MappedRepresentation), MappingTarget)
            let src = match e.p(0).r().and_then(|r| m.get(r)) {
                Some(s) => s,
                None => return,
            };
            let origin = src.p(0).r().map(|r| geom::axis_placement(m, r)).unwrap_or(Tf::ID);
            let target = e.p(1).r().map(|r| geom::operator(m, r)).unwrap_or(Tf::ID);
            let t2 = tf.then(&target).then(&origin);
            if let Some(rep) = src.p(1).r().and_then(|r| m.get(r)) {
                for it in rep.p(3).refs() {
                    item(m, it, &t2, style, true, out, depth + 1);
                }
            }
        }
        _ => {}
    }
}

fn ints(p: &P) -> Vec<i64> {
    p.list().map(|l| l.iter().filter_map(|x| x.int()).collect()).unwrap_or_default()
}

fn index_lists(p: &P) -> Vec<Vec<i64>> {
    p.list().map(|l| l.iter().map(ints).collect()).unwrap_or_default()
}

fn at(pts: &[V3], pn: &[i64], i: i64) -> Option<V3> {
    let j = if pn.is_empty() { i } else { *pn.get((i - 1) as usize)? };
    if j < 1 {
        return None;
    }
    pts.get((j - 1) as usize).copied()
}

fn point_list(m: &Model, id: u64, tf: &Tf) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    let s = m.scale;
    Some(
        e.p(0)
            .list()?
            .iter()
            .map(|c| {
                let v = c.nums().unwrap_or_default();
                tf.apply([*v.first().unwrap_or(&0.0) * s, *v.get(1).unwrap_or(&0.0) * s, *v.get(2).unwrap_or(&0.0) * s])
            })
            .collect(),
    )
}

/// The faces of a shell, each its outer bound cut into triangles (a hole in a face is left in).
fn shell(m: &Model, id: u64, tf: &Tf, out: &mut Vec<Tri>) {
    let e = match m.get(id) {
        Some(e) => e,
        None => return,
    };
    for f in e.p(0).refs() {
        let fe = match m.get(f) {
            Some(x) => x,
            None => continue,
        };
        let bounds = fe.p(0).refs();
        let pick = bounds
            .iter()
            .copied()
            .find(|b| m.get(*b).map(|x| x.name == "IFCFACEOUTERBOUND").unwrap_or(false))
            .or_else(|| bounds.first().copied());
        let b = match pick.and_then(|b| m.get(b)) {
            Some(b) => b,
            None => continue,
        };
        let mut pts = match b.p(0).r().and_then(|l| loop_points(m, l, tf)) {
            Some(p) => p,
            None => continue,
        };
        if b.p(1).boolean() == Some(false) {
            pts.reverse();
        }
        out.extend(ear_clip(&pts));
    }
}

fn loop_points(m: &Model, id: u64, tf: &Tf) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    if e.name != "IFCPOLYLOOP" {
        return None;
    }
    let mut v = Vec::new();
    for r in e.p(0).refs() {
        v.push(tf.apply(geom::p3(m, r)?));
    }
    Some(v)
}

// ---------------------------------------------------------------- curves and profiles

fn circle_points(r: f64) -> Vec<V2> {
    (0..SEGMENTS)
        .map(|i| {
            let a = 2.0 * std::f64::consts::PI * i as f64 / SEGMENTS as f64;
            [r * a.cos(), r * a.sin()]
        })
        .collect()
}

/// A curve's points as a mesh follows it: arcs of circles and ellipses in segments of a
/// 24-gon; an indexed polycurve by its points as they are.
fn curve(m: &Model, id: u64) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    match e.name.as_str() {
        "IFCINDEXEDPOLYCURVE" => {
            let pl = m.get(e.p(0).r()?)?;
            let s = m.scale;
            let coords: Vec<V3> = pl
                .p(0)
                .list()?
                .iter()
                .filter_map(|c| {
                    let v = c.nums()?;
                    Some([*v.first().unwrap_or(&0.0) * s, *v.get(1).unwrap_or(&0.0) * s, *v.get(2).unwrap_or(&0.0) * s])
                })
                .collect();
            let mut out: Vec<V3> = Vec::new();
            let mut push = |p: V3| {
                if out.last().map(|l| norm(sub(*l, p)) < 1e-9).unwrap_or(false) {
                    return;
                }
                out.push(p);
            };
            match e.p(1) {
                P::List(segs) if !segs.is_empty() => {
                    for sgm in segs {
                        if let P::Typed(_, v) = sgm {
                            for i in v.first().map(ints).unwrap_or_default() {
                                push(*coords.get((i - 1).max(0) as usize)?);
                            }
                        }
                    }
                }
                _ => {
                    for p in &coords {
                        push(*p);
                    }
                }
            }
            Some(out)
        }
        "IFCCOMPOSITECURVE" | "IFCCOMPOSITECURVEONSURFACE" => {
            let mut out: Vec<V3> = Vec::new();
            for seg in e.p(0).refs() {
                let s = m.get(seg)?;
                let mut pts = curve(m, s.p(2).r()?)?;
                if s.p(1).boolean() == Some(false) {
                    pts.reverse();
                }
                for p in pts {
                    if out.last().map(|l| norm(sub(*l, p)) < 1e-9).unwrap_or(false) {
                        continue;
                    }
                    out.push(p);
                }
            }
            Some(out)
        }
        _ => geom::curve_seg(m, id, SEGMENTS),
    }
}

/// A closed loop of a curve in plan, without its repeated last point.
fn loop2(m: &Model, id: u64) -> Option<Vec<V2>> {
    let pts = curve(m, id)?;
    let mut v: Vec<V2> = pts.iter().map(|p| [p[0], p[1]]).collect();
    while v.len() > 1 {
        let (a, b) = (v[0], v[v.len() - 1]);
        if (a[0] - b[0]).abs() < 1e-9 && (a[1] - b[1]).abs() < 1e-9 {
            v.pop();
        } else {
            break;
        }
    }
    if v.len() < 3 {
        return None;
    }
    Some(v)
}

/// A profile as a mesh cuts it: its outline and the holes in it (only an arbitrary profile
/// with voids has any), in its own plan.
fn profile(m: &Model, id: u64) -> Option<(Vec<V2>, Vec<Vec<V2>>)> {
    let e = m.get(id)?;
    let pos = |i: usize| -> Tf { e.p(i).r().map(|r| geom::axis_placement(m, r)).unwrap_or(Tf::ID) };
    let tr = |tf: &Tf, v: Vec<V2>| -> Vec<V2> {
        v.into_iter()
            .map(|p| {
                let q = tf.apply([p[0], p[1], 0.0]);
                [q[0], q[1]]
            })
            .collect()
    };
    let s = m.scale;
    match e.name.as_str() {
        "IFCRECTANGLEPROFILEDEF" | "IFCROUNDEDRECTANGLEPROFILEDEF" | "IFCRECTANGLEHOLLOWPROFILEDEF" => {
            let (hx, hy) = (e.p(3).num()? * s / 2.0, e.p(4).num()? * s / 2.0);
            Some((tr(&pos(2), vec![[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]), Vec::new()))
        }
        "IFCCIRCLEPROFILEDEF" | "IFCCIRCLEHOLLOWPROFILEDEF" => {
            let r = e.p(3).num()? * s;
            Some((tr(&pos(2), circle_points(r)), Vec::new()))
        }
        "IFCELLIPSEPROFILEDEF" => {
            let (a, b) = (e.p(3).num()? * s, e.p(4).num()? * s);
            let pts = (0..SEGMENTS)
                .map(|i| {
                    let t = 2.0 * std::f64::consts::PI * i as f64 / SEGMENTS as f64;
                    [a * t.cos(), b * t.sin()]
                })
                .collect();
            Some((tr(&pos(2), pts), Vec::new()))
        }
        "IFCARBITRARYCLOSEDPROFILEDEF" | "IFCARBITRARYPROFILEDEFWITHVOIDS" => {
            let outer = loop2(m, e.p(2).r()?)?;
            let mut holes = Vec::new();
            if e.name == "IFCARBITRARYPROFILEDEFWITHVOIDS" {
                for h in e.p(3).refs() {
                    if let Some(l) = loop2(m, h) {
                        holes.push(l);
                    }
                }
            }
            Some((outer, holes))
        }
        "IFCDERIVEDPROFILEDEF" => {
            let (o, h) = profile(m, e.p(2).r()?)?;
            let op = e.p(3).r().map(|r| geom::operator(m, r)).unwrap_or(Tf::ID);
            Some((tr(&op, o), h.into_iter().map(|l| tr(&op, l)).collect()))
        }
        _ => {
            // the other parametric profiles by the outline the shared reading gives them
            let (o, h, _) = geom::profile(m, id)?;
            Some((o, h))
        }
    }
}

fn extrusion(m: &Model, e: &Entity, tf: &Tf) -> Option<Vec<Tri>> {
    // IfcExtrudedAreaSolid(SweptArea, Position, ExtrudedDirection, Depth)
    let (mut outer, mut holes) = profile(m, e.p(0).r()?)?;
    let pos = e.p(1).r().map(|r| geom::axis_placement(m, r)).unwrap_or(Tf::ID);
    let d = unit(geom::dir3(m, e.p(2)).unwrap_or([0.0, 0.0, 1.0]));
    let depth = e.p(3).num()? * m.scale;
    if geom::area2(&outer) < 0.0 {
        outer.reverse();
    }
    for h in holes.iter_mut() {
        if geom::area2(h) < 0.0 {
            h.reverse();
        }
    }
    let ptf = tf.then(&pos);
    let mut tris = Vec::new();
    for piece in cut_holes(outer, &holes) {
        tris.extend(prism(&piece, &ptf, d, depth));
    }
    Some(tris)
}

fn cross2(a: V2, b: V2) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}

/// The part of a polygon on one side of the line through `a` and `b` (the left, or the right),
/// the points on the line kept on both.
fn clip(poly: &[V2], a: V2, b: V2, left: bool) -> Vec<V2> {
    let ab = [b[0] - a[0], b[1] - a[1]];
    let side = |p: V2| cross2(ab, [p[0] - a[0], p[1] - a[1]]);
    let keep = |s: f64| if left { s >= 0.0 } else { s <= 0.0 };
    let n = poly.len();
    let mut out = Vec::new();
    for i in 0..n {
        let (p, q) = (poly[i], poly[(i + 1) % n]);
        let (sp, sq) = (side(p), side(q));
        if keep(sp) {
            out.push(p);
        }
        if (sp < 0.0 && sq > 0.0) || (sp > 0.0 && sq < 0.0) {
            let t = sp / (sp - sq);
            out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
        }
    }
    out
}

fn bounds(p: &[V2]) -> (V2, V2) {
    let mut lo = [f64::INFINITY; 2];
    let mut hi = [f64::NEG_INFINITY; 2];
    for q in p {
        for k in 0..2 {
            lo[k] = lo[k].min(q[k]);
            hi[k] = hi[k].max(q[k]);
        }
    }
    (lo, hi)
}

fn solid_piece(p: &[V2]) -> bool {
    p.len() >= 3 && geom::area2(p).abs() > 1e-9
}

/// A profile less its holes, in pieces that have none: each hole (a hole that isn't convex, each
/// triangle ear clipping cuts it into) taken out of every piece it reaches, its edges in turn
/// cutting off what lies beyond them; what is left inside the hole goes.
fn cut_holes(outer: Vec<V2>, holes: &[Vec<V2>]) -> Vec<Vec<V2>> {
    let mut pieces = vec![outer];
    for h in holes {
        if h.len() < 3 {
            continue;
        }
        let parts: Vec<Vec<V2>> = if convex(h) { vec![h.clone()] } else { ears2(h).into_iter().map(|t| t.to_vec()).collect() };
        for part in parts {
            pieces = take_out(pieces, &part);
        }
    }
    pieces
}

fn convex(h: &[V2]) -> bool {
    let n = h.len();
    (0..n).all(|i| {
        let (a, b, c) = (h[(i + n - 1) % n], h[i], h[(i + 1) % n]);
        cross2([b[0] - a[0], b[1] - a[1]], [c[0] - b[0], c[1] - b[1]]) >= 0.0
    })
}

/// Ear clipping in plan (a counter-clockwise polygon): the first ear from the start each time,
/// the last three as the ear at the start.
fn ears2(poly: &[V2]) -> Vec<[V2; 3]> {
    let mut v: Vec<V2> = poly.to_vec();
    let mut out = Vec::new();
    let turn = |a: V2, b: V2, c: V2| cross2([b[0] - a[0], b[1] - a[1]], [c[0] - b[0], c[1] - b[1]]);
    let side = |a: V2, b: V2, q: V2| cross2([b[0] - a[0], b[1] - a[1]], [q[0] - a[0], q[1] - a[1]]);
    while v.len() >= 3 {
        let k = v.len();
        let mut found = None;
        for j in 0..k {
            let (a, b, c) = (v[(j + k - 1) % k], v[j], v[(j + 1) % k]);
            if turn(a, b, c) <= 0.0 {
                continue;
            }
            let inside = v.iter().any(|q| *q != a && *q != b && *q != c && side(a, b, *q) >= 0.0 && side(b, c, *q) >= 0.0 && side(c, a, *q) >= 0.0);
            if !inside {
                found = Some(j);
                break;
            }
        }
        match found {
            Some(j) => {
                out.push([v[(j + k - 1) % k], v[j], v[(j + 1) % k]]);
                v.remove(j);
            }
            None => break,
        }
    }
    out
}

/// Pieces less a convex hole: a piece the hole's box is clear of stays whole.
fn take_out(pieces: Vec<Vec<V2>>, h: &[V2]) -> Vec<Vec<V2>> {
    let n = h.len();
    let hb = bounds(h);
    let mut next = Vec::new();
    for p in pieces {
        let pb = bounds(&p);
        if hb.0[0] > pb.1[0] || hb.1[0] < pb.0[0] || hb.0[1] > pb.1[1] || hb.1[1] < pb.0[1] {
            next.push(p);
            continue;
        }
        let mut rest = p;
        for i in 0..n {
            let (a, b) = (h[i], h[(i + 1) % n]);
            let beyond = clip(&rest, a, b, false);
            if solid_piece(&beyond) {
                next.push(beyond);
            }
            rest = clip(&rest, a, b, true);
            if !solid_piece(&rest) {
                break;
            }
        }
    }
    next
}

/// A prism: a plan polygon (counter-clockwise) in a frame, pushed `depth` along `dir` (in the
/// frame's terms): its sides, its base (looking down) and its top.
fn prism(poly: &[V2], tf: &Tf, dir: V3, depth: f64) -> Vec<Tri> {
    let off = mul(dir, depth);
    let base: Vec<V3> = poly.iter().map(|p| tf.apply([p[0], p[1], 0.0])).collect();
    let top: Vec<V3> = poly.iter().map(|p| tf.apply(add([p[0], p[1], 0.0], off))).collect();
    let n = poly.len();
    let mut out = Vec::new();
    for i in 0..n {
        let j = (i + 1) % n;
        out.push([base[i], base[j], top[i]]);
        out.push([top[i], base[j], top[j]]);
    }
    let mut b = base.clone();
    b.reverse();
    out.extend(ear_clip(&b));
    out.extend(ear_clip(&top));
    out
}

// ---------------------------------------------------------------- triangles

fn newell(poly: &[V3]) -> V3 {
    let mut n = [0.0; 3];
    let k = poly.len();
    for i in 0..k {
        let (a, b) = (poly[i], poly[(i + 1) % k]);
        n[0] += (a[1] - b[1]) * (a[2] + b[2]);
        n[1] += (a[2] - b[2]) * (a[0] + b[0]);
        n[2] += (a[0] - b[0]) * (a[1] + b[1]);
    }
    n
}

/// A planar polygon in triangles: the first ear from its start each time (the vertex before
/// it, it, the one after), down to the last three.
pub fn ear_clip(poly: &[V3]) -> Vec<Tri> {
    let n = newell(poly);
    let mut v: Vec<V3> = poly.to_vec();
    let mut out = Vec::new();
    let turn = |a: V3, b: V3, c: V3| dot(cross(sub(b, a), sub(c, b)), n);
    let side = |a: V3, b: V3, q: V3| dot(cross(sub(b, a), sub(q, a)), n);
    while v.len() >= 3 {
        let k = v.len();
        let mut found = None;
        for j in 0..k {
            let (a, b, c) = (v[(j + k - 1) % k], v[j], v[(j + 1) % k]);
            if turn(a, b, c) <= 0.0 {
                continue;
            }
            let mut ok = true;
            for q in &v {
                if *q == a || *q == b || *q == c {
                    continue;
                }
                if side(a, b, *q) >= 0.0 && side(b, c, *q) >= 0.0 && side(c, a, *q) >= 0.0 {
                    ok = false;
                    break;
                }
            }
            if ok {
                found = Some(j);
                break;
            }
        }
        match found {
            Some(j) => {
                let k = v.len();
                out.push([v[(j + k - 1) % k], v[j], v[(j + 1) % k]]);
                v.remove(j);
            }
            None => break,
        }
    }
    out
}

/// A triangle as a mesh keeps it: turned to start at its least corner (by x, then y, then z),
/// its way round kept.
pub fn canonical(t: Tri) -> Tri {
    let less = |a: &V3, b: &V3| -> bool {
        for k in 0..3 {
            if a[k] != b[k] {
                return a[k] < b[k];
            }
        }
        false
    };
    let mut k = 0;
    for i in 1..3 {
        if less(&t[i], &t[k]) {
            k = i;
        }
    }
    [t[k], t[(k + 1) % 3], t[(k + 2) % 3]]
}
