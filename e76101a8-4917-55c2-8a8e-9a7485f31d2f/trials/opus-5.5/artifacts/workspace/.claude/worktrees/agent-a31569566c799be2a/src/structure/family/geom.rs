//! A family's forms as solids: a profile (or a circle, 32 sides) swept across its plane or
//! turned about an axis (32 steps to a turn), or triangles as a file brings them; their boxes
//! before any void cuts them; and voids cutting the solid forms listed before them (convex
//! polygons in binary space partitions, as `csg.js` does it).

pub type V3 = [f64; 3];

/// Sides of a circle, steps of a full turn.
pub const SEGMENTS: usize = 32;

fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn add(a: V3, b: V3) -> V3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
fn scale(a: V3, s: f64) -> V3 {
    [a[0] * s, a[1] * s, a[2] * s]
}
fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: V3, b: V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
fn len(a: V3) -> f64 {
    dot(a, a).sqrt()
}
fn lerp(a: V3, b: V3, t: f64) -> V3 {
    add(a, scale(sub(b, a), t))
}

/// A box: its least and greatest corners.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Bbox {
    pub min: V3,
    pub max: V3,
}

impl Bbox {
    pub fn of(points: impl IntoIterator<Item = V3>) -> Option<Bbox> {
        let mut b: Option<Bbox> = None;
        for p in points {
            b = Some(match b {
                None => Bbox { min: p, max: p },
                Some(mut x) => {
                    for i in 0..3 {
                        x.min[i] = x.min[i].min(p[i]);
                        x.max[i] = x.max[i].max(p[i]);
                    }
                    x
                }
            });
        }
        b
    }
    /// Whether two boxes share some volume (touching doesn't count).
    pub fn overlaps(&self, o: &Bbox) -> bool {
        (0..3).all(|i| self.min[i] < o.max[i] && o.min[i] < self.max[i])
    }
    /// Whether two boxes meet, touching (to within the cutting's 1e-5) counting: when a void
    /// cuts a solid.
    pub fn meets(&self, o: &Bbox) -> bool {
        (0..3).all(|i| self.min[i] <= o.max[i] + EPS && o.min[i] <= self.max[i] + EPS)
    }
}

/// A closed surface: convex polygons, each turned out (counter-clockwise seen from outside).
#[derive(Clone, Debug, Default)]
pub struct Solid {
    pub polys: Vec<Vec<V3>>,
}

impl Solid {
    pub fn bbox(&self) -> Option<Bbox> {
        Bbox::of(self.polys.iter().flat_map(|p| p.iter().copied()))
    }
    /// Its surface as triangles, turned out.
    pub fn triangles(&self) -> Vec<[V3; 3]> {
        let mut out = Vec::new();
        for p in &self.polys {
            for i in 1..p.len().saturating_sub(1) {
                out.push([p[0], p[i], p[i + 1]]);
            }
        }
        out
    }
    /// How many triangles it comes to.
    pub fn triangle_count(&self) -> usize {
        self.polys.iter().map(|p| p.len().saturating_sub(2)).sum()
    }
    /// The same surface as triangles: each polygon fanned from its first corner.
    pub fn fanned(&self) -> Solid {
        Solid { polys: self.triangles().into_iter().map(|t| t.to_vec()).collect() }
    }
    /// Its volume (negative where its polygons are turned in).
    pub fn volume(&self) -> f64 {
        self.triangles().iter().map(|t| dot(t[0], cross(t[1], t[2])) / 6.0).sum()
    }
    /// Each polygon turned the other way as the original turns its triangles: its first corner
    /// first, the others in reverse.
    fn swap_corners(&mut self) {
        for p in &mut self.polys {
            p[1..].reverse();
        }
    }
}

/// Triangles moved by a map of points; a map that mirrors turns each back out by swapping its
/// last two corners.
pub fn mapped(tris: &[[V3; 3]], f: &dyn Fn(V3) -> V3, mirrors: bool) -> Vec<[V3; 3]> {
    tris.iter().map(|t| if mirrors { [f(t[0]), f(t[2]), f(t[1])] } else { [f(t[0]), f(t[1]), f(t[2])] }).collect()
}

/// The signed area of a profile (counter-clockwise positive).
pub fn area(p: &[[f64; 2]]) -> f64 {
    let n = p.len();
    let mut a = 0.0;
    for i in 0..n {
        let j = (i + 1) % n;
        a += p[i][0] * p[j][1] - p[j][0] * p[i][1];
    }
    a / 2.0
}

/// A circle as the polygon the original draws it with.
pub fn circle(c: [f64; 2], r: f64) -> Vec<[f64; 2]> {
    (0..SEGMENTS)
        .map(|k| {
            let t = 2.0 * std::f64::consts::PI * k as f64 / SEGMENTS as f64;
            [c[0] + r * t.cos(), c[1] + r * t.sin()]
        })
        .collect()
}

/// A profile counter-clockwise (reversed as it is given when it runs the other way), then
/// without the points that repeat the one before them and those at its end that repeat its
/// first.
fn clean(p: &[[f64; 2]]) -> Vec<[f64; 2]> {
    let mut given = p.to_vec();
    if area(&given) < 0.0 {
        given.reverse();
    }
    let mut out: Vec<[f64; 2]> = Vec::with_capacity(given.len());
    for q in given {
        if out.last().map(|l| (l[0] - q[0]).abs() < 1e-9 && (l[1] - q[1]).abs() < 1e-9).unwrap_or(false) {
            continue;
        }
        out.push(q);
    }
    while out.len() > 1 {
        let (f, l) = (out[0], out[out.len() - 1]);
        if (f[0] - l[0]).abs() < 1e-9 && (f[1] - l[1]).abs() < 1e-9 {
            out.pop();
        } else {
            break;
        }
    }
    out
}

/// A simple polygon (counter-clockwise) cut into triangles by its ears.
pub fn triangulate(p: &[[f64; 2]]) -> Vec<[usize; 3]> {
    let n = p.len();
    if n < 3 {
        return Vec::new();
    }
    let mut idx: Vec<usize> = (0..n).collect();
    let mut out = Vec::with_capacity(n - 2);
    let cross2 = |a: [f64; 2], b: [f64; 2], c: [f64; 2]| (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    let inside = |q: [f64; 2], a: [f64; 2], b: [f64; 2], c: [f64; 2]| {
        cross2(a, b, q) >= 0.0 && cross2(b, c, q) >= 0.0 && cross2(c, a, q) >= 0.0
    };
    let mut guard = 0;
    while idx.len() > 3 && guard < n * n {
        guard += 1;
        let m = idx.len();
        let mut cut = None;
        for i in 0..m {
            let (ia, ib, ic) = (idx[(i + m - 1) % m], idx[i], idx[(i + 1) % m]);
            let (a, b, c) = (p[ia], p[ib], p[ic]);
            if cross2(a, b, c) <= 0.0 {
                continue;
            }
            let blocked = idx.iter().any(|&j| j != ia && j != ib && j != ic && inside(p[j], a, b, c) && p[j] != a && p[j] != b && p[j] != c);
            if !blocked {
                cut = Some(i);
                break;
            }
        }
        // a polygon no ear can be cut from (it crosses itself): cut the first corner anyway
        let i = cut.unwrap_or(0);
        let m = idx.len();
        out.push([idx[(i + m - 1) % m], idx[i], idx[(i + 1) % m]]);
        idx.remove(i);
    }
    if idx.len() == 3 {
        // the last ear, as the others: the corner before the first, the first, the one after it
        out.push([idx[2], idx[0], idx[1]]);
    }
    out
}

/// The sketch planes: a profile's (a, b) and the sweep's s in the family's x, y, z.
pub fn place(plane: super::model::Plane, a: f64, b: f64, s: f64) -> V3 {
    use super::model::Plane::*;
    match plane {
        XY => [a, b, s],
        XZ => [a, s, b],
        YZ => [s, a, b],
    }
}

/// A profile swept from `from` to `to` across its plane, as triangles in the original's order:
/// for each triangle of the profile (a, b, c), (a, b, c) at `to` and (a, c, b) at `from`; then
/// for each edge a to b of it (counter-clockwise), (a, b, b') and (a, b', a') from `from` to `to`
/// (primed at `to`); each turned the other way (its last two corners swapped) in the xz plane,
/// where a counter-clockwise profile faces against the sweep.
pub fn extrude(plane: super::model::Plane, profile: &[[f64; 2]], from: f64, to: f64) -> Solid {
    let p = clean(profile);
    let mut s = Solid::default();
    if p.len() < 3 {
        return s;
    }
    let at = |i: usize, z: f64| place(plane, p[i][0], p[i][1], z);
    for [a, b, c] in triangulate(&p) {
        s.polys.push(vec![at(a, to), at(b, to), at(c, to)]);
        s.polys.push(vec![at(a, from), at(c, from), at(b, from)]);
    }
    let n = p.len();
    for a in 0..n {
        let b = (a + 1) % n;
        s.polys.push(vec![at(a, from), at(b, from), at(b, to)]);
        s.polys.push(vec![at(a, from), at(b, to), at(a, to)]);
    }
    if plane == super::model::Plane::XZ {
        s.swap_corners();
    }
    s
}

/// Rotates `p` about the line through `o` along unit `u` by `t` radians (right-handed).
fn rotate(p: V3, o: V3, u: V3, t: f64) -> V3 {
    // the point's foot on the axis stays; the rest of it turns about it
    let foot = add(o, scale(u, dot(sub(p, o), u)));
    let r = sub(p, foot);
    let (c, sn) = (t.cos(), t.sin());
    add(foot, add(scale(r, c), scale(cross(u, r), sn)))
}

/// How many steps a turn of `deg` degrees takes.
pub fn steps(deg: f64) -> usize {
    ((deg.abs() / 360.0 * SEGMENTS as f64).ceil() as usize).max(1)
}

/// A profile turned about an axis in its plane from `from` to `to` degrees, as triangles in the
/// original's order: unless it turns all the way round, for each triangle of the profile
/// (a, b, c), (a, b, c) where it ends and (a, c, b) where it starts; then for each edge a to b of
/// the profile (counter-clockwise), step by step, (a, b, b') and (a, b', a') (primed a step on),
/// those with two corners in one point (on the axis) left out; all turned the other way (their
/// last two corners swapped) where that turns them out.
pub fn revolve(plane: super::model::Plane, profile: &[[f64; 2]], axis: [[f64; 2]; 2], from: f64, to: f64) -> Solid {
    let p = clean(profile);
    let mut s = Solid::default();
    if p.len() < 3 {
        return s;
    }
    let o = place(plane, axis[0][0], axis[0][1], 0.0);
    let e = sub(place(plane, axis[1][0], axis[1][1], 0.0), o);
    let l = len(e);
    if l == 0.0 {
        return s;
    }
    let u = scale(e, 1.0 / l);
    let span = to - from;
    let full = span >= 360.0;
    let n_steps = steps(span);
    let pts3: Vec<V3> = p.iter().map(|q| place(plane, q[0], q[1], 0.0)).collect();
    let ring = |k: usize| -> Vec<V3> {
        let t = (from + span * k as f64 / n_steps as f64).to_radians();
        pts3.iter().map(|q| rotate(*q, o, u, t)).collect()
    };
    // all the way round, the last step comes back to the first ring
    let rings: Vec<Vec<V3>> = (0..=n_steps).map(|k| ring(if full && k == n_steps { 0 } else { k })).collect();
    if !full {
        let (start, end) = (&rings[0], &rings[n_steps]);
        for [a, b, c] in triangulate(&p) {
            s.polys.push(vec![end[a], end[b], end[c]]);
            s.polys.push(vec![start[a], start[c], start[b]]);
        }
    }
    let same = |a: V3, b: V3| len(sub(a, b)) < 1e-9;
    let n = p.len();
    for a in 0..n {
        let b = (a + 1) % n;
        for k in 0..n_steps {
            let (r0, r1) = (&rings[k], &rings[k + 1]);
            for t in [[r0[a], r0[b], r1[b]], [r0[a], r1[b], r1[a]]] {
                if !(same(t[0], t[1]) || same(t[1], t[2]) || same(t[0], t[2])) {
                    s.polys.push(t.to_vec());
                }
            }
        }
    }
    if s.volume() < 0.0 {
        s.swap_corners();
    }
    s
}

/// Triangles as a file brings them.
pub fn mesh(tris: &[[[f64; 3]; 3]]) -> Solid {
    Solid { polys: tris.iter().map(|t| t.to_vec()).collect() }
}

// ---------------------------------------------------------------- cutting (csg.js's BSP)

const EPS: f64 = 1e-5;

#[derive(Clone, Copy, Debug)]
struct Plane {
    n: V3,
    w: f64,
}

impl Plane {
    fn of(p: &[V3]) -> Option<Plane> {
        // Newell's normal: robust for any convex polygon
        let mut n = [0.0; 3];
        for i in 0..p.len() {
            let (a, b) = (p[i], p[(i + 1) % p.len()]);
            n[0] += (a[1] - b[1]) * (a[2] + b[2]);
            n[1] += (a[2] - b[2]) * (a[0] + b[0]);
            n[2] += (a[0] - b[0]) * (a[1] + b[1]);
        }
        let l = len(n);
        if !(l > 1e-12) || !l.is_finite() {
            return None;
        }
        let n = scale(n, 1.0 / l);
        Some(Plane { n, w: dot(n, p[0]) })
    }
    fn flip(&mut self) {
        self.n = scale(self.n, -1.0);
        self.w = -self.w;
    }
}

#[derive(Clone, Debug)]
struct Poly {
    v: Vec<V3>,
    plane: Plane,
}

impl Poly {
    fn new(v: Vec<V3>) -> Option<Poly> {
        let plane = Plane::of(&v)?;
        Some(Poly { v, plane })
    }
    fn flip(&mut self) {
        self.v.reverse();
        self.plane.flip();
    }
}

const COPLANAR: u8 = 0;
const FRONT: u8 = 1;
const BACK: u8 = 2;
const SPANNING: u8 = 3;

/// The lists a plane sorts polygons into: those in it facing its way, those in it facing the
/// other way, those in front of it, those behind it (where a polygon it splits leaves its two
/// parts).
struct Lists<'a> {
    co_front: &'a mut Vec<Poly>,
    co_back: Option<&'a mut Vec<Poly>>,
    front: &'a mut Vec<Poly>,
    back: &'a mut Vec<Poly>,
}

/// A polygon sorted by a plane, as csg.js's `splitPolygon` does it; with no list of its own for
/// those in the plane facing the other way, they go with those facing its way.
fn split(plane: &Plane, poly: &Poly, to: Lists) {
    let mut ptype = 0u8;
    let types: Vec<u8> = poly
        .v
        .iter()
        .map(|v| {
            let t = dot(plane.n, *v) - plane.w;
            let ty = if t < -EPS {
                BACK
            } else if t > EPS {
                FRONT
            } else {
                COPLANAR
            };
            ptype |= ty;
            ty
        })
        .collect();
    match ptype {
        COPLANAR => {
            if dot(plane.n, poly.plane.n) > 0.0 {
                to.co_front.push(poly.clone())
            } else {
                match to.co_back {
                    Some(l) => l.push(poly.clone()),
                    None => to.co_front.push(poly.clone()),
                }
            }
        }
        FRONT => to.front.push(poly.clone()),
        BACK => to.back.push(poly.clone()),
        _ => {
            let (mut fv, mut bv) = (Vec::new(), Vec::new());
            let n = poly.v.len();
            for i in 0..n {
                let j = (i + 1) % n;
                let (ti, tj) = (types[i], types[j]);
                let (vi, vj) = (poly.v[i], poly.v[j]);
                if ti != BACK {
                    fv.push(vi);
                }
                if ti != FRONT {
                    bv.push(vi);
                }
                if (ti | tj) == SPANNING {
                    let t = (plane.w - dot(plane.n, vi)) / dot(plane.n, sub(vj, vi));
                    let mut v = lerp(vi, vj, t);
                    // on a plane square to an axis, the cut lies on it exactly
                    for a in 0..3 {
                        let (b, c) = ((a + 1) % 3, (a + 2) % 3);
                        if plane.n[b] == 0.0 && plane.n[c] == 0.0 && plane.n[a] != 0.0 {
                            v[a] = plane.w / plane.n[a];
                        }
                    }
                    fv.push(v);
                    bv.push(v);
                }
            }
            if fv.len() >= 3 {
                to.front.push(Poly { v: fv, plane: poly.plane });
            }
            if bv.len() >= 3 {
                to.back.push(Poly { v: bv, plane: poly.plane });
            }
        }
    }
}

#[derive(Default)]
struct Node {
    plane: Option<Plane>,
    front: Option<Box<Node>>,
    back: Option<Box<Node>>,
    polys: Vec<Poly>,
}

/// How much work cutting may take before the shape is called too complex (some seconds' worth:
/// a 4000-triangle torus cut by another takes about a hundred million).
const BUDGET: usize = 300_000_000;

impl Node {
    fn new(polys: Vec<Poly>, budget: &mut usize) -> Node {
        let mut n = Node::default();
        n.build(polys, budget);
        n
    }
    fn invert(&mut self) {
        let mut stack: Vec<&mut Node> = vec![self];
        while let Some(n) = stack.pop() {
            for p in &mut n.polys {
                p.flip();
            }
            if let Some(pl) = &mut n.plane {
                pl.flip();
            }
            std::mem::swap(&mut n.front, &mut n.back);
            if let Some(f) = n.front.as_deref_mut() {
                stack.push(f);
            }
            if let Some(b) = n.back.as_deref_mut() {
                stack.push(b);
            }
        }
    }
    /// The polygons outside this tree's solid. In the original's order: worked with a stack, at
    /// each node those in front go on to its front (or out at once where it has none), those
    /// behind to its back (or away where it has none), the back taken first.
    fn clip_polygons(&self, polys: Vec<Poly>, budget: &mut usize) -> Vec<Poly> {
        let mut out = Vec::new();
        let mut work: Vec<(&Node, Vec<Poly>)> = vec![(self, polys)];
        while let Some((n, ps)) = work.pop() {
            let Some(pl) = &n.plane else {
                out.extend(ps);
                continue;
            };
            *budget = budget.saturating_sub(ps.len() + 1);
            let (mut f, mut b) = (Vec::new(), Vec::new());
            for p in &ps {
                let (mut cf, mut cb) = (Vec::new(), Vec::new());
                split(pl, p, Lists { co_front: &mut cf, co_back: Some(&mut cb), front: &mut f, back: &mut b });
                f.append(&mut cf);
                b.append(&mut cb);
            }
            match &n.front {
                Some(fr) => work.push((fr, f)),
                None => out.extend(f),
            }
            if let Some(bk) = &n.back {
                work.push((bk, b));
            }
        }
        out
    }
    fn clip_to(&mut self, other: &Node, budget: &mut usize) {
        let mut stack: Vec<&mut Node> = vec![self];
        while let Some(n) = stack.pop() {
            let ps = std::mem::take(&mut n.polys);
            n.polys = other.clip_polygons(ps, budget);
            if let Some(f) = n.front.as_deref_mut() {
                stack.push(f);
            }
            if let Some(b) = n.back.as_deref_mut() {
                stack.push(b);
            }
        }
    }
    /// Every polygon of the tree in the original's order: the root's, then, node by node off a
    /// stack (the last put on first), its front's and its back's as it comes to them. With
    /// `through`, a node left with no polygons and one child stands for that child.
    fn all(&self, through: bool) -> Vec<Poly> {
        fn pass(mut n: &Node, through: bool) -> &Node {
            while through && n.polys.is_empty() {
                match (&n.front, &n.back) {
                    (Some(f), None) => n = f,
                    (None, Some(b)) => n = b,
                    _ => break,
                }
            }
            n
        }
        let root = pass(self, through);
        let mut out: Vec<Poly> = root.polys.clone();
        let mut stack: Vec<&Node> = vec![root];
        while let Some(n) = stack.pop() {
            for child in [&n.front, &n.back].into_iter().flatten() {
                let c = pass(child, through);
                out.extend(c.polys.iter().cloned());
                stack.push(c);
            }
        }
        out
    }
    fn build(&mut self, polys: Vec<Poly>, budget: &mut usize) {
        let mut work: Vec<(*mut Node, Vec<Poly>)> = vec![(self as *mut Node, polys)];
        while let Some((np, ps)) = work.pop() {
            if ps.is_empty() || *budget == 0 {
                continue;
            }
            *budget = budget.saturating_sub(ps.len());
            // SAFETY: each node is reached once, from its parent's own box, while the tree grows
            let n = unsafe { &mut *np };
            if n.plane.is_none() {
                n.plane = Some(ps[0].plane);
            }
            let pl = n.plane.unwrap();
            // those in the plane stay in the node, either way they face, as they come
            let (mut f, mut b) = (Vec::new(), Vec::new());
            for p in &ps {
                split(&pl, p, Lists { co_front: &mut n.polys, co_back: None, front: &mut f, back: &mut b });
            }
            if !f.is_empty() {
                let fr = n.front.get_or_insert_with(|| Box::new(Node::default()));
                work.push((fr.as_mut() as *mut Node, f));
            }
            if !b.is_empty() {
                let bk = n.back.get_or_insert_with(|| Box::new(Node::default()));
                work.push((bk.as_mut() as *mut Node, b));
            }
        }
    }
}

fn polys_of(s: &Solid) -> Vec<Poly> {
    s.polys.iter().filter_map(|p| Poly::new(p.clone())).collect()
}

/// `a` with `b` taken out of it (as triangles, each polygon fanned from its first corner, so
/// that what comes out is cut again as the original cuts it); None when it's too much work.
/// csg.js's steps, the polygons in the original's order: what is left of `a`'s tree, then
/// `b`'s polygons left inside it, put through `a`'s tree once more (as they are, then turned)
/// rather than built into it.
pub fn subtract(a: &Solid, b: &Solid) -> Option<Solid> {
    if a.polys.is_empty() || b.polys.is_empty() {
        return Some(a.clone());
    }
    let mut budget = BUDGET;
    let mut na = Node::new(polys_of(a), &mut budget);
    let mut nb = Node::new(polys_of(b), &mut budget);
    na.invert();
    na.clip_to(&nb, &mut budget);
    nb.clip_to(&na, &mut budget);
    nb.invert();
    nb.clip_to(&na, &mut budget);
    nb.invert();
    let mut inside = na.clip_polygons(nb.all(true), &mut budget);
    for p in &mut inside {
        p.flip();
    }
    let inside = na.clip_polygons(inside, &mut budget);
    na.invert();
    if budget == 0 {
        return None;
    }
    let polys: Vec<Vec<V3>> = na.all(false).into_iter().chain(inside).map(|p| p.v).collect();
    Some(Solid { polys }.fanned())
}
