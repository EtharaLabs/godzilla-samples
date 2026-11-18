//! Falls: a floor's or flat roof's shape from its drains and the least fall. Ridges drawn part the
//! top first (the faces of the outline, its openings and the ridges); in each part each drain takes
//! what is nearer it than any other of the part's drains, ridges run where two meet at the top's
//! height, a valley runs from each drain to each corner of its part (round an opening's corners,
//! which lie on the drain's cone, where it can't see straight), and each drain goes down as far as
//! the fall takes its farthest corner (to the tenth of a millimetre).

use super::shape::{SLine, SPoint, Shape};
use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::graph::Graph;
use crate::geom::{self, P2};
use crate::json::Value;
use crate::session::Session;

fn pc(p: P2) -> String {
    format!("({:.0}, {:.0})", p[0], p[1])
}

/// Ridges as serde reads `Vec<[P2; 2]>`.
fn de_ridges(v: &Value) -> Result<Vec<(P2, P2)>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    for r in a {
        let Value::Arr(pts) = r else {
            return Err(format!("invalid type: {}, expected an array of length 2", r.kind_name()));
        };
        let mut got: Vec<P2> = Vec::new();
        for (i, q) in pts.iter().enumerate() {
            if i >= 2 {
                return Err(format!("invalid length {}, expected fewer elements in array", pts.len()));
            }
            let Value::Arr(c) = q else {
                return Err(format!("invalid type: {}, expected tuple struct P2", q.kind_name()));
            };
            let mut xy = [0.0; 2];
            for (k, x) in c.iter().enumerate() {
                if k >= 2 {
                    return Err(format!("invalid length {}, expected fewer elements in array", c.len()));
                }
                match x {
                    Value::Num(n) => xy[k] = n.as_f64(),
                    o => return Err(format!("invalid type: {}, expected f64", o.kind_name())),
                }
            }
            if c.len() < 2 {
                return Err(format!("invalid length {}, expected tuple struct P2 with 2 elements", c.len()));
            }
            got.push(xy);
        }
        if got.len() < 2 {
            return Err(format!("invalid length {}, expected an array of length 2", pts.len()));
        }
        out.push((got[0], got[1]));
    }
    Ok(out)
}

/// The polygon clipped to the half-plane nearer `a` than `b` (Sutherland-Hodgman).
fn clip_nearer(poly: &[P2], a: P2, b: P2) -> Vec<P2> {
    let m = geom::lerp(a, b, 0.5);
    let n = geom::sub(b, a);
    // signed distance: negative on a's side
    let sd = |p: P2| geom::dot(geom::sub(p, m), n);
    let k = poly.len();
    let mut out = Vec::with_capacity(k + 2);
    for i in 0..k {
        let cur = poly[i];
        let next = poly[(i + 1) % k];
        let dc = sd(cur);
        let dn = sd(next);
        let inside_c = dc <= 0.0;
        let inside_n = dn <= 0.0;
        if inside_c {
            out.push(cur);
        }
        if inside_c != inside_n {
            let t = dc / (dc - dn);
            out.push(geom::lerp(cur, next, t));
        }
    }
    out
}

fn near(a: P2, b: P2) -> bool {
    geom::dist(a, b) <= 1e-3
}

/// A ring with repeated corners dropped.
fn dedupe(ring: Vec<P2>) -> Vec<P2> {
    let mut clean: Vec<P2> = Vec::new();
    for q in ring {
        if clean.last().map(|l| near(*l, q)).unwrap_or(false) {
            continue;
        }
        clean.push(q);
    }
    while clean.len() > 1 && near(clean[0], *clean.last().unwrap()) {
        clean.pop();
    }
    clean
}

/// The edges that bound the top: the outline's, the openings' and the ridges'.
struct Bounds {
    edges: Vec<(P2, P2)>,
    outline: Vec<P2>,
    holes: Vec<Vec<P2>>,
}

impl Bounds {
    /// Whether segment p-q lies along one of the edges.
    fn along(&self, p: P2, q: P2) -> bool {
        self.edges.iter().any(|(a, b)| geom::seg_dist(*a, *b, p) <= 1e-6 && geom::seg_dist(*a, *b, q) <= 1e-6)
    }

    /// Whether the straight way from p to q stays on the top: across no edge, through no opening.
    fn clear(&self, p: P2, q: P2) -> bool {
        for (a, b) in &self.edges {
            let o1 = geom::orient(*a, *b, p);
            let o2 = geom::orient(*a, *b, q);
            let o3 = geom::orient(p, q, *a);
            let o4 = geom::orient(p, q, *b);
            let eps = 1e-9 * geom::dist(*a, *b).max(1.0) * geom::dist(p, q).max(1.0);
            if ((o1 > eps && o2 < -eps) || (o1 < -eps && o2 > eps)) && ((o3 > eps && o4 < -eps) || (o3 < -eps && o4 > eps)) {
                return false;
            }
        }
        // the middle of the way on the top (the original's test: a way through an opening from
        // corner to corner whose middle is a corner passes)
        let m = geom::lerp(p, q, 0.5);
        let o = &self.outline;
        if !(geom::inside(o, m) || (0..o.len()).any(|i| geom::seg_dist(o[i], o[(i + 1) % o.len()], m) < 1e-6)) {
            return false;
        }
        !self.holes.iter().any(|h| geom::inside(h, m))
    }

    /// Whether segment p-q runs through a corner of the outline or an opening part way along.
    fn through_corner(&self, p: P2, q: P2) -> bool {
        let dd = geom::sub(q, p);
        let l2 = geom::dot(dd, dd);
        if l2 <= 0.0 {
            return false;
        }
        std::iter::once(&self.outline).chain(self.holes.iter()).flatten().any(|v| {
            let t = geom::dot(geom::sub(*v, p), dd) / l2;
            t > 1e-9 && t < 1.0 - 1e-9 && geom::seg_dist(p, q, *v) < 1e-6
        })
    }

    /// The pieces of segment a-b outside the openings.
    fn outside_holes(&self, a: P2, b: P2) -> Vec<(P2, P2)> {
        let mut ts = vec![0.0, 1.0];
        for h in &self.holes {
            let n = h.len();
            for i in 0..n {
                if let Some((t, _)) = geom::seg_cross(a, b, h[i], h[(i + 1) % n]) {
                    ts.push(t);
                }
            }
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap_or(std::cmp::Ordering::Equal));
        let mut out = Vec::new();
        for w in ts.windows(2) {
            if w[1] - w[0] < 1e-9 {
                continue;
            }
            let m = geom::lerp(a, b, (w[0] + w[1]) / 2.0);
            if self.holes.iter().any(|h| geom::inside(h, m)) {
                continue;
            }
            out.push((geom::lerp(a, b, w[0]), geom::lerp(a, b, w[1])));
        }
        out
    }
}

/// A part of the top between ridges: its ring and the openings inside it.
struct Part {
    ring: Vec<P2>,
    holes: Vec<Vec<P2>>,
}

/// The parts the ridges cut the top into, as the faces of its edges are traced.
fn parts_of(outline: &[P2], holes: &[Vec<P2>], ridges: &[(P2, P2)]) -> Vec<Part> {
    if ridges.is_empty() {
        return vec![Part { ring: outline.to_vec(), holes: holes.to_vec() }];
    }
    let mut segs: Vec<(P2, P2)> = Vec::new();
    for r in std::iter::once(outline).chain(holes.iter().map(|h| h.as_slice())) {
        let n = r.len();
        for i in 0..n {
            segs.push((r[i], r[(i + 1) % n]));
        }
    }
    segs.extend_from_slice(ridges);
    let g = Graph::build(&segs, 1.0);
    let comps = g.parts();
    let mut out = Vec::new();
    for f in g.faces() {
        if f.area <= 1e-6 {
            continue;
        }
        let ring = g.pts(&f.ring);
        // a point just inside the face, by its first edge
        let (a, b) = (ring[0], ring[1]);
        let m = geom::add(geom::lerp(a, b, 0.5), geom::scale(geom::left(geom::unit(geom::sub(b, a))), 1e-3));
        if holes.iter().any(|h| geom::inside_raw(h, m)) || !geom::inside_raw(outline, m) {
            continue;
        }
        let comp = comps[f.ring[0]];
        let inner: Vec<Vec<P2>> = holes
            .iter()
            .filter(|h| {
                let k = g.verts.iter().position(|v| geom::dist(*v, h[0]) <= 1e-6);
                k.map(|k| comps[k] != comp).unwrap_or(true) && geom::inside_raw(&ring, h[0])
            })
            .cloned()
            .collect();
        out.push(Part { ring, holes: inner });
    }
    out
}

/// A polygon's triangles, ears clipped from its first corner on.
fn ears(ring: &[P2]) -> Vec<[P2; 3]> {
    let mut poly: Vec<P2> = if geom::area(ring) < 0.0 { ring.iter().rev().copied().collect() } else { ring.to_vec() };
    let mut out = Vec::new();
    let mut guard = 0;
    let mut i = 0;
    while poly.len() > 3 && guard < 10000 {
        guard += 1;
        let n = poly.len();
        let (a, b, c) = (poly[(i + n - 1) % n], poly[i % n], poly[(i + 1) % n]);
        let convex = geom::orient(a, b, c) > 0.0;
        let empty = poly.iter().all(|q| {
            *q == a || *q == b || *q == c || {
                let (o1, o2, o3) = (geom::orient(a, b, *q), geom::orient(b, c, *q), geom::orient(c, a, *q));
                !(o1 >= 0.0 && o2 >= 0.0 && o3 >= 0.0)
            }
        });
        if convex && empty {
            out.push([a, b, c]);
            poly.remove(i % n);
            if i >= poly.len() {
                i = 0;
            }
        } else {
            i = (i + 1) % n;
        }
    }
    if poly.len() == 3 {
        out.push([poly[0], poly[1], poly[2]]);
    }
    out
}

/// Where the message says a part lies: the middle of its largest triangle.
fn part_label(part: &Part) -> P2 {
    let tris: Vec<[P2; 3]> = if part.holes.is_empty() {
        ears(&part.ring)
    } else {
        match crate::geom::tri::constrained(&part.ring, &part.holes, &[], &[]) {
            Ok(t) => t.tris.iter().map(|tr| [t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]]).collect(),
            Err(_) => Vec::new(),
        }
    };
    let mut best: Option<(f64, P2)> = None;
    for [a, b, c] in tris {
        let ar = geom::orient(a, b, c).abs();
        let mid = [(a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0];
        if best.map(|(x, _)| ar >= x).unwrap_or(true) {
            best = Some((ar, mid));
        }
    }
    best.map(|b| b.1).unwrap_or(part.ring[0])
}

/// The shortest ways from a drain round the openings' corners: each node's distance and the node
/// it is reached from (node 0 the drain, then `nodes`).
fn ways(bounds: &Bounds, all: &[P2]) -> (Vec<f64>, Vec<usize>) {
    let n = all.len();
    let mut dist = vec![f64::INFINITY; n];
    let mut from = vec![0usize; n];
    let mut done = vec![false; n];
    dist[0] = 0.0;
    for _ in 0..n {
        let mut k = None;
        for i in 0..n {
            if !done[i] && dist[i].is_finite() && k.map(|k: usize| dist[i] < dist[k]).unwrap_or(true) {
                k = Some(i);
            }
        }
        let Some(k) = k else { break };
        done[k] = true;
        for j in 0..n {
            if done[j] || !bounds.clear(all[k], all[j]) {
                continue;
            }
            let dd = dist[k] + geom::dist(all[k], all[j]);
            if dd < dist[j] {
                dist[j] = dd;
                from[j] = k;
            }
        }
    }
    (dist, from)
}

pub fn cmd_falls(s: &mut Session, p: &Value) -> R<Value> {
    let c = "falls";
    known_only(p, c, &["id", "drains", "fall", "ridges"])?;
    let idv = match opt_ref(p, c, "id")? {
        Some(v) => v,
        None => return Err("falls: `id`, the floor or flat roof to shape, is required".into()),
    };
    let pr = &s.project;
    let Some(id) = by_ref(pr, &idv) else {
        return Err(format!("falls: no element {}", ref_word(pr, &idv)));
    };
    let e = pr.el(id).unwrap().clone();
    match cat(&e) {
        "floor" => {}
        "roof" => {
            if let Some(why) = super::shape::unshapeable(&e) {
                return Err(format!("falls: {}: {}", id, why));
            }
        }
        _ => return Err(format!("falls: {}: only floors and flat roofs have shapes", id)),
    }
    let drains_in: Vec<P2> = match params::get(p, "drains") {
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                match params::point_of(x) {
                    Some(q) => out.push(q),
                    None => return Err(format!("falls: `drains`: {} is not a point [x, y] in mm", x.to_compact())),
                }
            }
            out
        }
        _ => return Err("falls: `drains` [[x, y], …] is required".into()),
    };
    let fall = match params::get(p, "fall") {
        None => return Err("falls: `fall`, the least fall in %, is required".into()),
        Some(v) => match params::mm_of(v) {
            Some(x) => x,
            None => return Err(format!("falls: `fall` must be a number in mm, got {}", v.to_compact())),
        },
    };
    let ridges = match params::get(p, "ridges") {
        None => Vec::new(),
        Some(v) => de_ridges(v).map_err(|er| format!("falls: `ridges` is a list of lines [[x, y], [x, y]]: {}", er))?,
    };
    if !(fall > 0.0 && fall <= 100.0) {
        return Err(format!("falls: `fall` is a percentage over 0 and at most 100, not {}", d(fall)));
    }
    if drains_in.is_empty() {
        return Err("falls: give at least one drain".into());
    }
    let (b, holes) = super::shape::region(&e);
    for q in &drains_in {
        let inside = geom::inside(&b, *q) && !holes.iter().any(|h| geom::inside(h, *q) || (0..h.len()).any(|i| geom::seg_dist(h[i], h[(i + 1) % h.len()], *q) < 1e-9));
        if !inside {
            return Err(format!("falls: the drain at {} is outside the outline", pc(*q)));
        }
    }
    for i in 0..drains_in.len() {
        for j in i + 1..drains_in.len() {
            if geom::dist(drains_in[i], drains_in[j]) <= 1.0 {
                return Err(format!(
                    "falls: the drains at {} and {} are within a millimetre of each other: one is enough",
                    pc(drains_in[i]),
                    pc(drains_in[j])
                ));
            }
        }
    }
    // the edges that bound the top
    let mut edges: Vec<(P2, P2)> = Vec::new();
    for r in std::iter::once(&b).chain(holes.iter()) {
        let n = r.len();
        for i in 0..n {
            edges.push((r[i], r[(i + 1) % n]));
        }
    }
    // each ridge runs from the outline, an opening or another ridge to another
    for (i, (ra, rb)) in ridges.iter().enumerate() {
        let on_edge = |q: P2| {
            edges.iter().any(|(a, b2)| geom::seg_dist(*a, *b2, q) <= 1.0)
                || ridges.iter().enumerate().any(|(j, (a, b2))| j != i && geom::seg_dist(*a, *b2, q) <= 1.0)
        };
        let m = geom::lerp(*ra, *rb, 0.5);
        let inside = geom::inside(&b, m) && !holes.iter().any(|h| geom::inside(h, m));
        if !(geom::dist(*ra, *rb) > 1.0) || !on_edge(*ra) || !on_edge(*rb) || !inside {
            return Err(format!(
                "falls: the ridge from {} to {} doesn't divide the top: run it to the outline, an opening or another ridge",
                pc(*ra),
                pc(*rb)
            ));
        }
    }
    edges.extend_from_slice(&ridges);
    let bounds = Bounds { edges, outline: b.clone(), holes: holes.clone() };
    // the parts, each with its drains
    let parts = parts_of(&b, &holes, &ridges);
    let mut part_drains: Vec<Vec<P2>> = vec![Vec::new(); parts.len()];
    // (a drain on a ridge goes with the part to its left, or below it on a level one)
    let within = |ring: &[P2], q: P2| {
        let n = ring.len();
        let mut c = false;
        for i in 0..n {
            let (a, b2) = (ring[i], ring[(i + 1) % n]);
            if (a[1] > q[1]) != (b2[1] > q[1]) {
                let x = (b2[0] - a[0]) * (q[1] - a[1]) / (b2[1] - a[1]) + a[0];
                if x < q[0] {
                    c = !c;
                }
            }
        }
        c
    };
    for q in &drains_in {
        if let Some(k) = parts.iter().position(|pt| within(&pt.ring, *q) && !pt.holes.iter().any(|h| geom::inside_raw(h, *q))) {
            part_drains[k].push(*q);
        }
    }
    for (k, pt) in parts.iter().enumerate() {
        if part_drains[k].is_empty() {
            return Err(format!("falls: the part of the top between ridges round {} has no drain: give it one", pc(part_label(pt))));
        }
    }
    let drains: Vec<P2> = part_drains.iter().flatten().copied().collect();
    let corners: Vec<P2> = b.iter().chain(holes.iter().flatten()).copied().collect();
    let mut points: Vec<SPoint> = drains.iter().map(|q| SPoint { id: None, guid: None, at: *q, z: 0.0 }).collect();
    let mut extra: Vec<(P2, f64)> = Vec::new();
    let mut lines: Vec<SLine> = Vec::new();
    let mut drawn: Vec<(P2, P2)> = Vec::new();
    let add_line = |lines: &mut Vec<SLine>, drawn: &mut Vec<(P2, P2)>, a: P2, b2: P2| {
        if drawn.iter().any(|(x, y)| (near(*x, a) && near(*y, b2)) || (near(*x, b2) && near(*y, a))) {
            return;
        }
        drawn.push((a, b2));
        lines.push(SLine { id: None, guid: None, a, b: b2 });
    };
    for (a, b2) in &ridges {
        add_line(&mut lines, &mut drawn, *a, *b2);
    }
    let known = |extra: &Vec<(P2, f64)>, q: P2| corners.iter().any(|c0| near(*c0, q)) || drains.iter().any(|x| near(*x, q)) || extra.iter().any(|x| near(x.0, q));
    let mut di = 0;
    for (k, pt) in parts.iter().enumerate() {
        let mine = &part_drains[k];
        for (i, dq) in mine.iter().enumerate() {
            let mut cell = pt.ring.clone();
            let mut cell_holes: Vec<Vec<P2>> = pt.holes.clone();
            for (j, other) in mine.iter().enumerate() {
                if j != i {
                    cell = clip_nearer(&cell, *dq, *other);
                    for h in cell_holes.iter_mut() {
                        *h = clip_nearer(h, *dq, *other);
                    }
                }
            }
            let cell = dedupe(cell);
            let cell_holes: Vec<Vec<P2>> = cell_holes.into_iter().map(dedupe).collect();
            // the ways to every corner, round the openings' corners
            let nodes: Vec<P2> = holes.iter().flatten().copied().collect();
            let mut all = vec![*dq];
            all.extend_from_slice(&nodes);
            let (dist, from) = ways(&bounds, &all);
            let reach = |q: P2| -> Option<(f64, usize)> {
                if let Some(n) = (1..all.len()).find(|n| near(all[*n], q)) {
                    return if dist[n].is_finite() { Some((dist[n], from[n])) } else { None };
                }
                let mut best: Option<(f64, usize)> = None;
                for (n, at) in all.iter().enumerate() {
                    if !dist[n].is_finite() || !bounds.clear(*at, q) {
                        continue;
                    }
                    let dd = dist[n] + geom::dist(*at, q);
                    if best.map(|b0| dd <= b0.0).unwrap_or(true) {
                        best = Some((dd, n));
                    }
                }
                best
            };
            let targets: Vec<P2> = cell.iter().copied().chain(cell_holes.iter().flatten().copied()).collect();
            let mut far: f64 = 0.0;
            let mut way: Vec<(P2, f64, usize)> = Vec::new();
            for q in &targets {
                match reach(*q) {
                    Some((dd, n)) => {
                        far = far.max(dd);
                        way.push((*q, dd, n));
                    }
                    None => {
                        return Err(format!(
                            "falls: the drain at {} can't see the corner at {} across the outline or a ridge: add a drain on that side",
                            pc(*dq),
                            pc(*q)
                        ))
                    }
                }
            }
            let depth = (fall / 100.0 * far * 10.0).ceil() / 10.0;
            points[di].z = -depth;
            di += 1;
            let cone = |dd: f64| ((-depth + fall / 100.0 * dd) * 10.0).ceil() / 10.0;
            // the new corners of the cell (an opening's on the cone), then each opening's corners
            // on the cone and its new ones
            for q in &cell {
                if nodes.iter().any(|x| near(*x, *q)) {
                    if !extra.iter().any(|x| near(x.0, *q)) {
                        let dd = way.iter().find(|w| near(w.0, *q)).map(|w| w.1).unwrap_or(0.0);
                        extra.push((*q, cone(dd)));
                    }
                } else if !known(&extra, *q) {
                    extra.push((*q, 0.0));
                }
            }
            for h in &cell_holes {
                for q in h {
                    if nodes.iter().any(|x| near(*x, *q)) && !extra.iter().any(|x| near(x.0, *q)) {
                        let dd = way.iter().find(|w| near(w.0, *q)).map(|w| w.1).unwrap_or(0.0);
                        extra.push((*q, cone(dd)));
                    }
                }
                for q in h {
                    if !known(&extra, *q) {
                        extra.push((*q, 0.0));
                    }
                }
            }
            // a valley to each corner from where its way last turns
            for (q, _, n) in &way {
                let from_pt = all[*n];
                if near(from_pt, *q) || bounds.along(from_pt, *q) || bounds.through_corner(from_pt, *q) {
                    continue;
                }
                add_line(&mut lines, &mut drawn, from_pt, *q);
            }
            // ridges where the cell meets its neighbours, but through the openings
            let m = cell.len();
            for t in 0..m {
                let (a, b2) = (cell[t], cell[(t + 1) % m]);
                if bounds.along(a, b2) {
                    continue;
                }
                for (x, y) in bounds.outside_holes(a, b2) {
                    add_line(&mut lines, &mut drawn, x, y);
                }
            }
        }
    }
    for (q, z) in extra {
        points.push(SPoint { id: None, guid: None, at: q, z });
    }
    // every plane falls to a drain at least as much as asked
    {
        let at: Vec<P2> = points.iter().map(|q| q.at).collect();
        let ls: Vec<(P2, P2)> = lines.iter().map(|l| (l.a, l.b)).collect();
        match crate::geom::tri::constrained(&b, &holes, &at, &ls) {
            Err(er) => return Err(format!("falls: the falls don't fold into planes: {}", er)),
            Ok(t) => {
                let zs: Vec<f64> = t
                    .pts
                    .iter()
                    .map(|q| points.iter().find(|x| geom::dist(x.at, *q) <= crate::geom::tri::TOL).map(|x| x.z).unwrap_or(0.0))
                    .collect();
                for tr in &t.tris {
                    let (pa, pb, pcn) = (t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]);
                    let (za, zb, zc) = (zs[tr[0]], zs[tr[1]], zs[tr[2]]);
                    let e1 = geom::sub(pb, pa);
                    let e2 = geom::sub(pcn, pa);
                    let det = geom::cross(e1, e2);
                    if det.abs() < 1e-9 {
                        continue;
                    }
                    let gx = ((zb - za) * e2[1] - (zc - za) * e1[1]) / det;
                    let gy = (e1[0] * (zc - za) - e2[0] * (zb - za)) / det;
                    if (gx * gx + gy * gy).sqrt() < fall / 100.0 - 1e-9 {
                        let mid = [(pa[0] + pb[0] + pcn[0]) / 3.0, (pa[1] + pb[1] + pcn[1]) / 3.0];
                        return Err(format!(
                            "falls: round {} the top can't fall {} % to a drain: add a drain there, or a ridge to part it off",
                            pc(mid),
                            d(fall)
                        ));
                    }
                }
            }
        }
    }
    let mut sh = Shape { points, lines };
    let v = sh.to_value(&mut s.project);
    let el = s.project.el_mut(id).unwrap();
    let order: &[&str] = if cat(el) == "roof" { super::roofs::ORDER } else { super::slabs::FLOOR_ORDER };
    put(el, order, "shape", v);
    let pr = &s.project;
    let e = pr.el(id).unwrap();
    let sh = Shape::read(e);
    let (lo, hi) = super::shape::top_range(pr, e, &sh);
    let drains_v: Vec<Value> = sh.points.iter().take(drains.len()).map(|p| jobj! {"at" => pv(p.at), "z" => p.z}).collect();
    let r2 = |x: f64| (x * 100.0).round() / 100.0;
    Ok(jobj! {
        "drains" => Value::Arr(drains_v),
        "faces" => super::shape::faces(e, &sh),
        "id" => id,
        "top" => Value::Arr(vec![Value::f(r2(lo)), Value::f(r2(hi))]),
    })
}
