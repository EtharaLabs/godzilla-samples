//! The straight skeleton of a roof's footprint: its outline counter-clockwise and its
//! courtyards clockwise, the roof to the left of every edge, each edge moving in at a speed of
//! its own (a gable's 0). Each edge's face is the ring it sweeps: its start, its end, and the
//! skeleton's nodes back, each with the time the wavefront reached it.

use super::geom::*;

const EPS: f64 = 1e-9;

#[derive(Clone, Copy, Debug)]
struct Edge {
    a: V2,
    d: V2,
    n: V2,
    w: f64,
}

#[derive(Clone, Copy, Debug)]
struct Vert {
    p: V2,
    t0: f64,
    vel: V2,
    el: usize,
    er: usize,
    prev: usize,
    next: usize,
    alive: bool,
    node: usize,
}

impl Vert {
    fn at(&self, t: f64) -> V2 {
        self.p + self.vel * (t - self.t0)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Node {
    pub p: V2,
    pub t: f64,
}

/// An arc of the skeleton: from one node to another, between the faces of two edges (the
/// wavefront vertex's incoming and outgoing edges).
#[derive(Clone, Copy, Debug)]
struct Arc {
    from: usize,
    to: usize,
    el: usize,
    er: usize,
}

/// The node at a point, made the first time the wavefront reaches it.
fn node_at(nodes: &mut Vec<Node>, p: V2, t: f64) -> usize {
    for (i, n) in nodes.iter().enumerate() {
        if n.t > 0.0 && n.p.distance(p) < 1e-6 {
            return i;
        }
    }
    nodes.push(Node { p, t });
    nodes.len() - 1
}

fn velocity(e1: &Edge, e2: &Edge) -> V2 {
    // v·n1 = w1, v·n2 = w2
    let det = e1.n.x * e2.n.y - e1.n.y * e2.n.x;
    if det.abs() < 1e-12 {
        // parallel edges: straight on
        let w = if e1.w > e2.w { e1.w } else { e2.w };
        return e1.n * w;
    }
    let x = (e1.w * e2.n.y - e2.w * e1.n.y) / det;
    let y = (e1.n.x * e2.w - e2.n.x * e1.w) / det;
    v2(x, y)
}

/// Each edge's face, numbered as the edges are (each ring's edge i from its point i to the
/// next, the rings in turn); none for an edge that doesn't move (a gable).
pub fn faces(rings: &[Vec<V2>], speeds: &[f64]) -> Vec<Option<Vec<Node>>> {
    let mut edges: Vec<Edge> = Vec::new();
    let mut nodes: Vec<Node> = Vec::new();
    let mut verts: Vec<Vert> = Vec::new();
    let mut edge_start: Vec<usize> = Vec::new();
    let mut edge_end: Vec<usize> = Vec::new();
    for ring in rings {
        let n = ring.len();
        let base = edges.len();
        for i in 0..n {
            let a = ring[i];
            let b = ring[(i + 1) % n];
            let d = (b - a).normalize();
            let w = speeds.get(base + i).copied().unwrap_or(1.0);
            edges.push(Edge { a, d, n: d.perp(), w });
        }
        let vbase = verts.len();
        for i in 0..n {
            let el = base + (i + n - 1) % n;
            let er = base + i;
            let node = nodes.len();
            nodes.push(Node { p: ring[i], t: 0.0 });
            verts.push(Vert {
                p: ring[i],
                t0: 0.0,
                vel: velocity(&edges[el], &edges[er]),
                el,
                er,
                prev: vbase + (i + n - 1) % n,
                next: vbase + (i + 1) % n,
                alive: true,
                node,
            });
        }
        for i in 0..n {
            edge_start.push(vbase + i);
            edge_end.push(vbase + (i + 1) % n);
        }
    }
    let ne = edges.len();
    let mut arcs: Vec<Arc> = Vec::new();
    let mut t_now = 0.0f64;
    let mut guard = 0;
    loop {
        guard += 1;
        if guard > 10000 {
            break;
        }
        // the next event: an edge of the wavefront shrinking away, or a reflex vertex
        // reaching an edge it doesn't bound
        let mut best: Option<(f64, usize, Option<usize>)> = None;
        for (i, v) in verts.iter().enumerate() {
            if !v.alive {
                continue;
            }
            let u = &verts[v.next];
            let e = &edges[v.er];
            let rate = (u.vel - v.vel).dot(e.d);
            if rate < -EPS {
                let len = (u.at(t_now) - v.at(t_now)).dot(e.d);
                let t = t_now + len / (-rate);
                if t >= t_now - 1e-9 && best.map(|b| t < b.0 - 1e-12).unwrap_or(true) {
                    best = Some((t.max(t_now), i, None));
                }
            }
        }
        for (i, v) in verts.iter().enumerate() {
            if !v.alive {
                continue;
            }
            let din = edges[v.el].d;
            let dout = edges[v.er].d;
            if din.cross(dout) >= -EPS {
                continue;
            }
            for (j, a) in verts.iter().enumerate() {
                if !a.alive || j == i || a.next == i {
                    continue;
                }
                let f = &edges[a.er];
                if a.er == v.el || a.er == v.er {
                    continue;
                }
                let den = f.w - v.vel.dot(f.n);
                if den <= EPS {
                    continue;
                }
                let t = ((v.at(t_now) - f.a).dot(f.n) - f.w * t_now) / den + t_now;
                if t < t_now - 1e-9 {
                    continue;
                }
                let x = v.at(t);
                let b = &verts[a.next];
                let sa = (x - a.at(t)).dot(f.d);
                let sb = (b.at(t) - x).dot(f.d);
                if sa < -1e-7 || sb < -1e-7 {
                    continue;
                }
                if best.map(|bb| t < bb.0 - 1e-9).unwrap_or(true) {
                    best = Some((t.max(t_now), i, Some(j)));
                }
            }
        }
        let Some((t, i, split)) = best else { break };
        // an event all but at once with the last happens with it
        let t = if t - t_now < 1e-6 { t_now } else { t };
        t_now = t;
        match split {
            None => {
                // edge event: vertex i and its next meet
                let j = verts[i].next;
                let x = verts[i].at(t);
                let node = node_at(&mut nodes, x, t);
                // every other vertex of this wavefront at the same point meets there too
                let mut group = vec![i, j];
                loop {
                    let first = group[0];
                    let pv = verts[first].prev;
                    if group.contains(&pv) {
                        break;
                    }
                    if verts[pv].at(t).distance(x) < 1e-6 {
                        group.insert(0, pv);
                    } else {
                        break;
                    }
                }
                loop {
                    let last = *group.last().unwrap();
                    let nv = verts[last].next;
                    if group.contains(&nv) {
                        break;
                    }
                    if verts[nv].at(t).distance(x) < 1e-6 {
                        group.push(nv);
                    } else {
                        break;
                    }
                }
                for &g in &group {
                    arcs.push(Arc { from: verts[g].node, to: node, el: verts[g].el, er: verts[g].er });
                    verts[g].alive = false;
                }
                let first = group[0];
                let last = *group.last().unwrap();
                let pv = verts[first].prev;
                let nv = verts[last].next;
                if pv == last || group.len() >= 3 && verts[last].next == first {
                    // the whole wavefront closed at this point
                    continue;
                }
                if pv == nv {
                    // two vertices left: they are the ends of a ridge
                    let o = pv;
                    arcs.push(Arc { from: verts[o].node, to: node, el: verts[o].el, er: verts[o].er });
                    verts[o].alive = false;
                    continue;
                }
                let el = verts[first].el;
                let er = verts[last].er;
                let k = verts.len();
                verts.push(Vert {
                    p: x,
                    t0: t,
                    vel: velocity(&edges[el], &edges[er]),
                    el,
                    er,
                    prev: pv,
                    next: nv,
                    alive: true,
                    node,
                });
                verts[pv].next = k;
                verts[nv].prev = k;
            }
            Some(j) => {
                // split event: vertex i reaches the edge from j to its next
                let x = verts[i].at(t);
                let node = node_at(&mut nodes, x, t);
                let v = verts[i];
                arcs.push(Arc { from: v.node, to: node, el: v.el, er: v.er });
                verts[i].alive = false;
                let a = j;
                let b = verts[a].next;
                let f = verts[a].er;
                // one wavefront: from v's prev to x (edges v.el, f), on to b
                let k1 = verts.len();
                verts.push(Vert { p: x, t0: t, vel: velocity(&edges[v.el], &edges[f]), el: v.el, er: f, prev: v.prev, next: b, alive: true, node });
                let k2 = verts.len();
                verts.push(Vert { p: x, t0: t, vel: velocity(&edges[f], &edges[v.er]), el: f, er: v.er, prev: a, next: v.next, alive: true, node });
                verts[v.prev].next = k1;
                verts[b].prev = k1;
                verts[a].next = k2;
                verts[v.next].prev = k2;
                for k in [k1, k2] {
                    // a wavefront of two vertices is a ridge
                    let p = verts[k].prev;
                    if verts[p].prev == k && verts[k].alive {
                        arcs.push(Arc { from: verts[p].node, to: verts[k].node, el: verts[p].el, er: verts[p].er });
                        verts[p].alive = false;
                        verts[k].alive = false;
                    }
                }
            }
        }
    }
    // each edge's face: its start, its end, then the arcs round back to its start
    let mut out = Vec::with_capacity(ne);
    for e in 0..ne {
        if edges[e].w <= EPS {
            out.push(None);
            continue;
        }
        let a = verts[edge_start[e]].node;
        let b = verts[edge_end[e]].node;
        let mut ring = vec![a, b];
        let mut cur = b;
        let mut used = vec![false; arcs.len()];
        let mut ok = false;
        for _ in 0..arcs.len() + 2 {
            if cur == a {
                ok = true;
                break;
            }
            // leave cur along an arc with this face on its right going out (el == e, from cur)
            // or one on its left coming in (er == e, to cur)
            let mut next = None;
            for (k, arc) in arcs.iter().enumerate() {
                if used[k] {
                    continue;
                }
                if arc.el == e && arc.from == cur {
                    next = Some((k, arc.to));
                    break;
                }
                if arc.er == e && arc.to == cur {
                    next = Some((k, arc.from));
                    break;
                }
            }
            let Some((k, nn)) = next else { break };
            used[k] = true;
            if nn == a {
                ok = true;
                break;
            }
            ring.push(nn);
            cur = nn;
        }
        if !ok {
            out.push(None);
            continue;
        }
        let mut face: Vec<Node> = Vec::new();
        for k in &ring {
            let n = nodes[*k];
            if face.last().map(|l| l.p.distance(n.p) < 1e-6).unwrap_or(false) {
                continue;
            }
            face.push(n);
        }
        while face.len() > 1 && face[0].p.distance(face[face.len() - 1].p) < 1e-6 {
            face.pop();
        }
        out.push(Some(face));
    }
    out
}
