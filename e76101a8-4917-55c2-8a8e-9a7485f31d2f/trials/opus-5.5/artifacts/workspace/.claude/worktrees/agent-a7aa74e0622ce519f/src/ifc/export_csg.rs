//! Solids cut by solids, as Evan Wallace's csg.js does it: each solid a list of polygons (here
//! the triangles a form is written as), built into a BSP tree whose planes split them, and a
//! subtraction done by clipping each tree to the other. What it gives is then written as
//! fans of triangles over corners merged where they round to the same micrometre.

use super::geom::*;

const EPS: f64 = 1e-5;

#[derive(Clone, Debug)]
pub struct Poly {
    pub verts: Vec<V3>,
    pub n: V3,
    pub w: f64,
}

/// A unit vector, as glam makes it: times one over the length.
fn unit(v: V3) -> V3 {
    let r = 1.0 / v.length();
    v3(v.x * r, v.y * r, v.z * r)
}

impl Poly {
    pub fn new(verts: Vec<V3>) -> Poly {
        let n = unit((verts[1] - verts[0]).cross(verts[2] - verts[0]));
        let w = n.dot(verts[0]);
        Poly { verts, n, w }
    }

    fn flip(&mut self) {
        self.verts.reverse();
        self.n = -self.n;
        self.w = -self.w;
    }
}

#[derive(Clone, Copy, Debug)]
struct Plane {
    n: V3,
    w: f64,
}

impl Plane {
    fn flip(&mut self) {
        self.n = -self.n;
        self.w = -self.w;
    }

    /// Sorts a polygon to the lists for its side of the plane, split where it spans it.
    fn split(&self, p: Poly, cf: &mut Vec<Poly>, cb: &mut Vec<Poly>, front: &mut Vec<Poly>, back: &mut Vec<Poly>) {
        const COP: u8 = 0;
        const FR: u8 = 1;
        const BK: u8 = 2;
        const SP: u8 = 3;
        let mut ptype = 0u8;
        let mut types = Vec::with_capacity(p.verts.len());
        for v in &p.verts {
            let t = self.n.dot(*v) - self.w;
            let ty = if t < -EPS {
                BK
            } else if t > EPS {
                FR
            } else {
                COP
            };
            ptype |= ty;
            types.push(ty);
        }
        match ptype {
            COP => {
                if self.n.dot(p.n) > 0.0 {
                    cf.push(p)
                } else {
                    cb.push(p)
                }
            }
            FR => front.push(p),
            BK => back.push(p),
            _ => {
                let n = p.verts.len();
                let mut f = Vec::with_capacity(n + 1);
                let mut b = Vec::with_capacity(n + 1);
                for i in 0..n {
                    let j = (i + 1) % n;
                    let (ti, tj) = (types[i], types[j]);
                    let (vi, vj) = (p.verts[i], p.verts[j]);
                    if ti != BK {
                        f.push(vi);
                    }
                    if ti != FR {
                        b.push(vi);
                    }
                    if (ti | tj) == SP {
                        let t = (self.w - self.n.dot(vi)) / self.n.dot(vj - vi);
                        let v = vi + (vj - vi) * t;
                        f.push(v);
                        b.push(v);
                    }
                }
                if f.len() >= 3 {
                    front.push(Poly::new(f));
                }
                if b.len() >= 3 {
                    back.push(Poly::new(b));
                }
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

impl Node {
    fn of(polys: Vec<Poly>) -> Node {
        let mut n = Node::default();
        n.build(polys);
        n
    }

    fn invert(&mut self) {
        for p in self.polys.iter_mut() {
            p.flip();
        }
        if let Some(pl) = self.plane.as_mut() {
            pl.flip();
        }
        if let Some(f) = self.front.as_mut() {
            f.invert();
        }
        if let Some(b) = self.back.as_mut() {
            b.invert();
        }
        std::mem::swap(&mut self.front, &mut self.back);
    }

    fn clip_polys(&self, polys: Vec<Poly>) -> Vec<Poly> {
        let Some(pl) = self.plane else { return polys };
        let mut front = Vec::new();
        let mut back = Vec::new();
        for p in polys {
            let (mut f2, mut b2) = (Vec::new(), Vec::new());
            pl.split(p, &mut f2, &mut b2, &mut front, &mut back);
            // coplanar ones go with the side they face
            front.append(&mut f2);
            back.append(&mut b2);
        }
        let mut front = match &self.front {
            Some(f) => f.clip_polys(front),
            None => front,
        };
        let back = match &self.back {
            Some(b) => b.clip_polys(back),
            None => Vec::new(),
        };
        front.extend(back);
        front
    }

    fn clip_to(&mut self, bsp: &Node) {
        let polys = std::mem::take(&mut self.polys);
        self.polys = bsp.clip_polys(polys);
        if let Some(f) = self.front.as_mut() {
            f.clip_to(bsp);
        }
        if let Some(b) = self.back.as_mut() {
            b.clip_to(bsp);
        }
    }

    fn all(&self, out: &mut Vec<Poly>) {
        out.extend(self.polys.iter().cloned());
        if let Some(f) = &self.front {
            f.all(out);
        }
        if let Some(b) = &self.back {
            b.all(out);
        }
    }

    fn build(&mut self, polys: Vec<Poly>) {
        if polys.is_empty() {
            return;
        }
        if self.plane.is_none() {
            self.plane = Some(Plane { n: polys[0].n, w: polys[0].w });
        }
        let pl = self.plane.unwrap();
        let mut front = Vec::new();
        let mut back = Vec::new();
        for p in polys {
            let mut cop = Vec::new();
            let mut cop2 = Vec::new();
            pl.split(p, &mut cop, &mut cop2, &mut front, &mut back);
            self.polys.append(&mut cop);
            self.polys.append(&mut cop2);
        }
        if !front.is_empty() {
            self.front.get_or_insert_with(Box::default).build(front);
        }
        if !back.is_empty() {
            self.back.get_or_insert_with(Box::default).build(back);
        }
    }
}

/// `a` less `b`.
pub fn subtract(a: &[Poly], b: &[Poly]) -> Vec<Poly> {
    let mut na = Node::of(a.to_vec());
    let mut nb = Node::of(b.to_vec());
    na.invert();
    na.clip_to(&nb);
    nb.clip_to(&na);
    nb.invert();
    nb.clip_to(&na);
    nb.invert();
    let mut bp = Vec::new();
    nb.all(&mut bp);
    na.build(bp);
    na.invert();
    let mut out = Vec::new();
    na.all(&mut out);
    out
}

/// Polygons as the triangles of their fans, corners kept as they are.
pub fn as_triangles(polys: &[Poly]) -> Vec<Poly> {
    let mut out = Vec::new();
    for p in polys {
        for i in 1..p.verts.len().saturating_sub(1) {
            out.push(Poly::new(vec![p.verts[0], p.verts[i], p.verts[i + 1]]));
        }
    }
    out
}

/// The polygons as triangles: a fan from each one's first corner, its corners merged with
/// those that round to the same micrometre, listed in the order first met.
pub fn triangles(polys: &[Poly], mx: bool, my: bool) -> (Vec<V3>, Vec<[usize; 3]>) {
    let mut pts: Vec<V3> = Vec::new();
    let mut index: std::collections::HashMap<(i64, i64, i64), usize> = std::collections::HashMap::new();
    let mut tris = Vec::new();
    let mut id = |v: V3, pts: &mut Vec<V3>| -> usize {
        let k = ((v.x * 1e6).round() as i64, (v.y * 1e6).round() as i64, (v.z * 1e6).round() as i64);
        *index.entry(k).or_insert_with(|| {
            pts.push(v);
            pts.len() - 1
        })
    };
    for p in polys {
        if !mx && !my {
            let ids: Vec<usize> = p.verts.iter().map(|v| id(*v, &mut pts)).collect();
            for i in 1..ids.len().saturating_sub(1) {
                tris.push([ids[0], ids[i], ids[i + 1]]);
            }
            continue;
        }
        // mirrored (across the x axis, the y axis or both): each triangle turned to keep
        // facing out, its corners listed in the order it then has
        let m = |v: V3| v3(if mx { -v.x } else { v.x }, if my { -v.y } else { v.y }, v.z);
        for i in 1..p.verts.len().saturating_sub(1) {
            let (j, k) = if mx != my { (i + 1, i) } else { (i, i + 1) };
            let a = id(m(p.verts[0]), &mut pts);
            let b = id(m(p.verts[j]), &mut pts);
            let c = id(m(p.verts[k]), &mut pts);
            tris.push([a, b, c]);
        }
    }
    (pts, tris)
}
