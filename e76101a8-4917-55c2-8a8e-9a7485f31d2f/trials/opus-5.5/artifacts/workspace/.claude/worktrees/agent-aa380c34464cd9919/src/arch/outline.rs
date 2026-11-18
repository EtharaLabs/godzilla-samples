//! The outline of a level's walls: their centre lines as a planar graph, the outer edge of its
//! largest part (a floor's or a roof's footprint by default), and the loops standing free inside
//! it with no room in them (courtyards, open through floors and roofs).

use super::util::*;
use super::walls::Wall;
use crate::geom::graph::{Face, Graph, WELD};
use crate::geom::{self, P2};
use crate::project::Project;

/// The walls a level's plan of rooms sees: those its computation height cuts.
pub fn level_walls(pr: &Project, level: u64) -> Vec<Wall> {
    let z = elev(pr, level) + computation_height(pr, level);
    Wall::all(pr).into_iter().filter(|w| w.spans(pr, z)).collect()
}

/// The graph of the walls' centre lines, with which wall each line is.
pub fn wall_graph(walls: &[Wall]) -> (Graph, Vec<u64>) {
    let mut segs = Vec::new();
    let mut src = Vec::new();
    for (w, pieces) in walls.iter().zip(super::walls::joined_centres(walls)) {
        for s in pieces {
            segs.push(s);
            src.push(w.id);
        }
    }
    (Graph::build(&segs, WELD), src)
}

/// The outline of the level's walls along their centre lines and the free-standing loops inside
/// it with no room in them, as a floor takes them: the outline counter-clockwise, as the outside
/// of the largest part is traced and turned round; each loop clockwise from its lowest corner.
pub struct Outline {
    pub boundary: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
    /// The part (graph component) and face the outline is.
    pub graph: Graph,
    pub faces: Vec<Face>,
    pub outer: usize,
}

/// Rooms' points on a level.
pub fn room_points(pr: &Project, level: u64) -> Vec<P2> {
    pr.elements
        .values()
        .filter(|e| cat(e) == "room" && level_of(pr, e) == Some(level))
        .filter_map(|e| pt(e, "point"))
        .collect()
}

pub fn level_outline(pr: &Project, level: u64) -> Option<Outline> {
    let walls = level_walls(pr, level);
    let (g, _) = wall_graph(&walls);
    let faces = g.faces();
    if !faces.iter().any(|f| f.area > 0.0) {
        return None;
    }
    // the outside of the largest part
    let mut outer: Option<usize> = None;
    for (i, f) in faces.iter().enumerate() {
        if f.area < 0.0 && outer.map(|o| -f.area > -faces[o].area).unwrap_or(true) {
            outer = Some(i);
        }
    }
    let outer = outer?;
    let ring = g.pts(&faces[outer].ring);
    let boundary: Vec<P2> = ring.iter().rev().copied().collect();
    let parts = g.parts();
    let main_part = parts[faces[outer].ring[0]];
    let rooms = room_points(pr, level);
    let mut holes = Vec::new();
    // each other part standing free inside the outline: the outside of a part inside it
    let mut taken: Vec<Vec<P2>> = Vec::new();
    for (i, f) in faces.iter().enumerate() {
        if i == outer || f.area >= 0.0 {
            continue;
        }
        let part = parts[f.ring[0]];
        if part == main_part {
            continue;
        }
        let pts = g.pts(&f.ring);
        if !pts.iter().all(|p| geom::inside(&boundary, *p)) {
            continue;
        }
        // inside another loop taken already: an island in a courtyard
        if taken.iter().any(|t| geom::inside_raw(t, pts[0])) {
            continue;
        }
        let region: Vec<P2> = pts.iter().rev().copied().collect();
        if rooms.iter().any(|r| geom::inside(&region, *r)) {
            continue;
        }
        taken.push(pts.clone());
        holes.push(geom::start_lowest(&drop_collinear(&pts)));
    }
    Some(Outline { boundary, holes, graph: g, faces, outer })
}

/// Drops the corners that lie on the line through their neighbours (spikes too), each judged by
/// the ring as it was.
pub fn drop_collinear(ring: &[P2]) -> Vec<P2> {
    let n = ring.len();
    if n < 3 {
        return ring.to_vec();
    }
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let a = ring[(i + n - 1) % n];
        let b = ring[i];
        let c = ring[(i + 1) % n];
        let u = geom::sub(b, a);
        let v = geom::sub(c, b);
        let cr = geom::cross(u, v);
        let scale = geom::len(u) * geom::len(v);
        if cr.abs() <= 1e-9 * scale.max(1e-300) {
            continue;
        }
        out.push(b);
    }
    out
}
