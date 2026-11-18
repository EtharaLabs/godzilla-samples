//! Plan geometry the import needs: the faces the walls' lines make in plan (to tell whether
//! walls enclose a point, as BIMCraft's rooms find their boundaries), and arcs as chords.

const EPS: f64 = 1e-6;

pub type P = [f64; 2];

fn cross(o: P, a: P, b: P) -> f64 {
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
}

/// Where two segments meet (as parameters along the first), if they do.
fn meet(a0: P, a1: P, b0: P, b1: P) -> Vec<f64> {
    let d = [a1[0] - a0[0], a1[1] - a0[1]];
    let e = [b1[0] - b0[0], b1[1] - b0[1]];
    let den = d[0] * e[1] - d[1] * e[0];
    let len2 = d[0] * d[0] + d[1] * d[1];
    if len2 < EPS * EPS {
        return vec![];
    }
    let mut out = Vec::new();
    if den.abs() < 1e-12 {
        // parallel: collinear overlap gives the other's ends that lie on this one
        if cross(a0, a1, b0).abs() / len2.sqrt() > 1e-6 {
            return vec![];
        }
        for q in [b0, b1] {
            let t = ((q[0] - a0[0]) * d[0] + (q[1] - a0[1]) * d[1]) / len2;
            if t > -1e-9 && t < 1.0 + 1e-9 {
                out.push(t.clamp(0.0, 1.0));
            }
        }
        return out;
    }
    let w = [b0[0] - a0[0], b0[1] - a0[1]];
    let t = (w[0] * e[1] - w[1] * e[0]) / den;
    let u = (w[0] * d[1] - w[1] * d[0]) / den;
    let tl = 1e-9;
    if t > -tl && t < 1.0 + tl && u > -tl && u < 1.0 + tl {
        out.push(t.clamp(0.0, 1.0));
    }
    out
}

pub struct Faces {
    /// Each bounded face's outer boundary, counter-clockwise.
    pub faces: Vec<Vec<P>>,
}

fn key(p: P) -> (i64, i64) {
    ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64)
}

/// The bounded faces the segments make in plan.
pub fn faces(segs: &[(P, P)]) -> Faces {
    // split every segment where another meets it
    let mut pieces: Vec<(P, P)> = Vec::new();
    for (i, s) in segs.iter().enumerate() {
        let mut ts = vec![0.0, 1.0];
        for (j, o) in segs.iter().enumerate() {
            if i != j {
                ts.extend(meet(s.0, s.1, o.0, o.1));
            }
        }
        ts.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let pt = |t: f64| [s.0[0] + t * (s.1[0] - s.0[0]), s.0[1] + t * (s.1[1] - s.0[1])];
        for w in ts.windows(2) {
            let (a, b) = (pt(w[0]), pt(w[1]));
            if key(a) != key(b) {
                pieces.push((a, b));
            }
        }
    }
    // vertices and undirected edges
    let mut verts: Vec<P> = Vec::new();
    let mut vid: std::collections::HashMap<(i64, i64), usize> = std::collections::HashMap::new();
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
    // half-edges, each vertex's outgoing ones sorted by angle
    let mut out: Vec<Vec<usize>> = vec![Vec::new(); verts.len()];
    for &(a, b) in &edges {
        out[a].push(b);
        out[b].push(a);
    }
    let ang = |a: usize, b: usize| (verts[b][1] - verts[a][1]).atan2(verts[b][0] - verts[a][0]);
    for (a, o) in out.iter_mut().enumerate() {
        o.sort_by(|x, y| ang(a, *x).partial_cmp(&ang(a, *y)).unwrap());
    }
    let mut used: std::collections::HashSet<(usize, usize)> = std::collections::HashSet::new();
    let mut faces = Vec::new();
    for a in 0..verts.len() {
        for &b in &out[a] {
            if used.contains(&(a, b)) {
                continue;
            }
            // walk: at each vertex take the next edge clockwise from the one we came in by
            let mut cyc = vec![a];
            let (mut u, mut v) = (a, b);
            let mut steps = 0;
            loop {
                used.insert((u, v));
                let o = &out[v];
                let k = o.iter().position(|x| *x == u).unwrap();
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
            if area(&pts) > EPS {
                faces.push(pts);
            }
        }
    }
    Faces { faces }
}

pub fn area(p: &[P]) -> f64 {
    let mut s = 0.0;
    for i in 0..p.len() {
        let (a, b) = (p[i], p[(i + 1) % p.len()]);
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

/// Whether the point is inside the polygon, not on its edge.
pub fn inside(poly: &[P], q: P) -> bool {
    let n = poly.len();
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        let len = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
        if len > 0.0 && cross(a, b, q).abs() / len < 1e-6 {
            let t = ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / (len * len);
            if t >= -1e-9 && t <= 1.0 + 1e-9 {
                return false;
            }
        }
    }
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

impl Faces {
    /// The smallest face the point is inside.
    pub fn around(&self, q: P) -> Option<&Vec<P>> {
        let mut best: Option<(&Vec<P>, f64)> = None;
        for f in &self.faces {
            if inside(f, q) {
                let a = area(f);
                if best.map(|(_, ba)| a < ba).unwrap_or(true) {
                    best = Some((f, a));
                }
            }
        }
        best.map(|(f, _)| f)
    }
}

/// Points along an arc in plan, as chords within half a millimetre of it.
pub fn arc_points(centre: P, radius: f64, a0: f64, sweep: f64) -> Vec<P> {
    let tol = 0.5f64;
    let n = if radius > tol {
        let step = 2.0 * (1.0 - tol / radius).acos();
        ((sweep.abs() / step).ceil() as usize).max(1)
    } else {
        1
    };
    (0..=n)
        .map(|k| {
            let a = a0 + sweep * k as f64 / n as f64;
            [centre[0] + radius * a.cos(), centre[1] + radius * a.sin()]
        })
        .collect()
}
