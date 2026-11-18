//! Rooms and room separation lines: a room's boundary found from the walls (those that bound
//! rooms, where the level's computation height cuts them) and the separation lines round its
//! point, at their centre lines and at the walls' faces; islands subtracted; one room to a space.

use super::util::*;
use super::walls::Wall;
use crate::commands::params::{self, R};
use crate::geom::graph::{Graph, WELD};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const ROOM_ORDER: &[&str] = &[
    "level",
    "point",
    "name",
    "number",
    "colour",
    "params",
    "base_offset",
    "top_level",
    "limit_offset",
    "frozen",
    "kept",
];

/// A region: its outer ring (counter-clockwise) and its holes (clockwise).
#[derive(Clone, Debug, PartialEq)]
pub struct Region {
    pub outer: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
}

impl Region {
    pub fn area(&self) -> f64 {
        let mut a = geom::area(&self.outer).abs();
        for h in &self.holes {
            a -= geom::area(h).abs();
        }
        a
    }
    pub fn perimeter(&self) -> f64 {
        let mut p = geom::perimeter(&self.outer);
        for h in &self.holes {
            p += geom::perimeter(h);
        }
        p
    }
    pub fn to_value(&self) -> Value {
        jobj! {"outer" => ring_v(&self.outer), "holes" => rings_v(&self.holes)}
    }
    pub fn from_value(v: &Value) -> Option<Region> {
        Some(Region { outer: pts(v, "outer")?, holes: rings(v, "holes") })
    }
}

/// A room's space both ways it is measured.
#[derive(Clone, Debug, PartialEq)]
pub struct Space {
    pub centre: Region,
    pub finish: Region,
    /// Whether the room's point lies inside the region at the faces (a frozen room keeps that
    /// region only then).
    pub finish_round: bool,
}

/// The lines that bound a level's rooms, in the order of the elements they come from: each with
/// how far its faces are from it (half a wall's thickness; a separation line has none).
pub struct Lines {
    pub segs: Vec<(P2, P2)>,
    pub half: Vec<f64>,
    pub src: Vec<u64>,
}

pub fn bounding_lines(pr: &Project, level: u64) -> Lines {
    lines_of(pr, level, true)
}

/// The lines round a level's spaces: rooms' (walls that bound rooms, and separation lines), or
/// every wall's (what a ceiling runs out to).
pub fn lines_of(pr: &Project, level: u64, rooms: bool) -> Lines {
    let z = elev(pr, level) + computation_height(pr, level);
    let mut out = Lines { segs: Vec::new(), half: Vec::new(), src: Vec::new() };
    let walls: Vec<Wall> = Wall::all(pr).into_iter().filter(|w| (w.room_bounding || !rooms) && w.spans(pr, z)).collect();
    let centres = super::walls::joined_centres(&walls);
    // the walls' lines first, then the room separation lines, then the columns' outlines
    let pass = |e: &Value| match cat(e) {
        "wall" => 0,
        "roomseparator" => 1,
        _ => 2,
    };
    for (id, e) in (0..3).flat_map(|k| pr.elements.iter().filter(move |(_, e)| pass(e) == k)) {
        match cat(e) {
            "wall" => {
                let Some(k) = walls.iter().position(|w| w.id == *id) else { continue };
                for s in &centres[k] {
                    out.segs.push(*s);
                    out.half.push(walls[k].thickness / 2.0);
                    out.src.push(*id);
                }
            }
            "roomseparator" => {
                if !rooms || level_of(pr, e) != Some(level) {
                    continue;
                }
                let (Some(mut a), Some(mut b)) = (pt(e, "start"), pt(e, "end")) else { continue };
                // an end drawn to a wall's face (or within a millimetre of it) runs on to its centre
                // line there
                let (a0, b0) = (a, b);
                for end in [&mut a, &mut b] {
                    'walls: for (k, w) in walls.iter().enumerate() {
                        for (c0, c1) in &centres[k] {
                            if geom::seg_dist(*c0, *c1, *end) <= w.thickness / 2.0 + 1.0 {
                                let par = geom::cross(geom::unit(geom::sub(b0, a0)), geom::unit(geom::sub(*c1, *c0))).abs() < 1e-9;
                                if !par {
                                    if let Some(q) = super::walls::line_meet(a0, b0, *c0, *c1) {
                                        *end = q;
                                    }
                                }
                                break 'walls;
                            }
                        }
                    }
                }
                out.segs.push((a, b));
                out.half.push(0.0);
                out.src.push(*id);
            }
            "column" | "structuralcolumn" => {
                if !rooms || flag(e, "room_bounding") == Some(false) {
                    continue;
                }
                let Some(ring) = column_outline(pr, e) else { continue };
                if !column_spans(pr, e, z) {
                    continue;
                }
                let n = ring.len();
                for i in 0..n {
                    out.segs.push((ring[i], ring[(i + 1) % n]));
                    out.half.push(0.0);
                    out.src.push(*id);
                }
            }
            _ => {}
        }
    }
    out
}

/// A column's outline in plan: its type's `width` along its angle by its `depth`, or a circle
/// `width` across.
pub fn column_outline(pr: &Project, e: &Value) -> Option<Vec<P2>> {
    let at = pt(e, "at")?;
    let key = if cat(e) == "structuralcolumn" { "structural_column" } else { "column" };
    let name = type_name(pr, e)?;
    let t = type_def(pr, key, &name)?;
    let w = numd(t, "width", 400.0);
    let dp = numd(t, "depth", w);
    if flag(t, "round") == Some(true) {
        // a round column bounds rooms as a 24-gon
        let r = w / 2.0;
        return Some(
            (0..24)
                .map(|i| {
                    let a = (15.0 * i as f64).to_radians();
                    [at[0] + r * a.cos(), at[1] + r * a.sin()]
                })
                .collect(),
        );
    }
    let ang = numd(e, "angle", 0.0).to_radians();
    let u = [ang.cos(), ang.sin()];
    let n = geom::left(u);
    let c = |su: f64, sn: f64| geom::add(at, geom::add(geom::scale(u, su * w / 2.0), geom::scale(n, sn * dp / 2.0)));
    Some(vec![c(-1.0, -1.0), c(1.0, -1.0), c(1.0, 1.0), c(-1.0, 1.0)])
}

/// Whether a column stands through height z: from its level and base offset up to its top level
/// (or its height).
fn column_spans(pr: &Project, e: &Value, z: f64) -> bool {
    let base = level_of(pr, e).map(|l| elev(pr, l)).unwrap_or(0.0) + numd(e, "base_offset", 0.0);
    let top = match e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level")) {
        Some(t) => elev(pr, t) + numd(e, "top_offset", 0.0),
        None => base + numd(e, "height", 3000.0),
    };
    base <= z && z < top
}

/// How far the faces are from each edge of a traced ring.
fn edge_offsets(g: &Graph, lines: &Lines, ring: &[usize]) -> Vec<f64> {
    let n = ring.len();
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let a = ring[i];
        let b = ring[(i + 1) % n];
        let k = g.edges.iter().position(|&(u, v)| (u == a && v == b) || (u == b && v == a));
        let mut h = k.map(|k| lines.half[g.src[k]]).unwrap_or(0.0);
        // lines lying along one another: the thickest one's face bounds
        let (pa, pb) = (g.verts[a], g.verts[b]);
        for (s, (q0, q1)) in lines.segs.iter().enumerate() {
            if lines.half[s] > h && geom::seg_dist(*q0, *q1, pa) <= 1e-6 && geom::seg_dist(*q0, *q1, pb) <= 1e-6 {
                h = lines.half[s];
            }
        }
        out.push(h);
    }
    out
}

/// The space round a point on a level: the smallest region the lines enclose it in, less the
/// islands standing free inside it; None where nothing encloses it.
pub fn space_at(pr: &Project, level: u64, q: P2) -> Option<Space> {
    space_in(pr, level, q, true)
}

/// The space round a point among a level's rooms' lines, or among all its walls.
pub fn space_in(pr: &Project, level: u64, q: P2, rooms: bool) -> Option<Space> {
    let lines = lines_of(pr, level, rooms);
    let g = Graph::build(&lines.segs, WELD);
    let faces = g.faces();
    let mut best: Option<usize> = None;
    for (i, f) in faces.iter().enumerate() {
        if f.area <= 0.0 {
            continue;
        }
        let ring = g.pts(&f.ring);
        if geom::inside_raw(&ring, q) && best.map(|b| f.area < faces[b].area).unwrap_or(true) {
            best = Some(i);
        }
    }
    let bi = best?;
    let outer_ring = g.pts(&faces[bi].ring);
    let parts = g.parts();
    let part = parts[faces[bi].ring[0]];
    // islands: the outsides of other parts inside the face, not inside another island or a
    // smaller face round the point
    let mut islands: Vec<usize> = Vec::new();
    for (i, f) in faces.iter().enumerate() {
        if f.area > 0.0 || parts[f.ring[0]] == part {
            continue;
        }
        let pts = g.pts(&f.ring);
        if !pts.iter().all(|p| geom::inside_raw(&outer_ring, *p) || on_ring(&outer_ring, *p)) {
            continue;
        }
        // inside an island already taken, or the point inside it
        if islands.iter().any(|k| faces[*k].area < 0.0 && geom::inside_raw(&g.pts(&faces[*k].ring), pts[0])) {
            continue;
        }
        if f.area < 0.0 && geom::inside(&pts, q) {
            continue;
        }
        islands.push(i);
    }
    // each island by its outline (its outside turned round); one of no area (a wall standing
    // free) has a hole only at the faces
    let island_ring = |k: usize| -> Vec<usize> { faces[k].ring.iter().rev().copied().collect() };
    let centre = Region {
        outer: outer_ring.clone(),
        holes: islands.iter().filter(|k| faces[**k].area < 0.0).map(|k| g.pts(&island_ring(*k))).collect(),
    };
    // at the faces: a column on the boundary is cut out of the region the walls' faces bound
    let is_col = |k: usize| matches!(pr.category(lines.src[k]), Some("column") | Some("structuralcolumn"));
    let ring_cols: Vec<u64> = {
        let r = &faces[bi].ring;
        let m = r.len();
        let mut out: Vec<u64> = Vec::new();
        for i in 0..m {
            let (a, b) = (r[i], r[(i + 1) % m]);
            if let Some(k) = g.edges.iter().position(|&(u, v)| (u == a && v == b) || (u == b && v == a)) {
                let s = g.src[k];
                if is_col(s) && !out.contains(&lines.src[s]) {
                    out.push(lines.src[s]);
                }
            }
        }
        out
    };
    let fo = if ring_cols.is_empty() {
        let moved = geom::offset::offset_ring(&outer_ring, &edge_offsets(&g, &lines, &faces[bi].ring));
        let moved = if moved.len() == outer_ring.len() { as_faces_trace(&g, &lines, &faces[bi].ring, moved) } else { moved };
        untangle(moved, q)
    } else {
        cut_columns(&lines, &ring_cols, q).unwrap_or_else(|| geom::offset::offset_ring(&outer_ring, &edge_offsets(&g, &lines, &faces[bi].ring)))
    };
    let fh: Vec<Vec<P2>> = islands
        .iter()
        .map(|k| {
            let r = island_ring(*k);
            let ds: Vec<f64> = edge_offsets(&g, &lines, &r).iter().map(|x| -x).collect();
            geom::offset::offset_ring(&g.pts(&r), &ds)
        })
        .collect();
    let finish = Region { outer: fo, holes: fh };
    let finish_round = geom::inside(&finish.outer, q) && !finish.holes.iter().any(|h| geom::inside(h, q) || on_ring(h, q));
    Some(Space { centre, finish, finish_round })
}

/// The outline at the faces round a point with the columns on its boundary cut out: the faces of
/// the walls round it as if the columns weren't there, less the columns.
fn cut_columns(lines: &Lines, cols: &[u64], q: P2) -> Option<Vec<P2>> {
    let keep: Vec<usize> = (0..lines.segs.len()).filter(|k| !cols.contains(&lines.src[*k])).collect();
    let sub = Lines {
        segs: keep.iter().map(|k| lines.segs[*k]).collect(),
        half: keep.iter().map(|k| lines.half[*k]).collect(),
        src: keep.iter().map(|k| lines.src[*k]).collect(),
    };
    let g = Graph::build(&sub.segs, WELD);
    let faces = g.faces();
    let mut best: Option<usize> = None;
    for (i, f) in faces.iter().enumerate() {
        if f.area <= 0.0 {
            continue;
        }
        if geom::inside_raw(&g.pts(&f.ring), q) && best.map(|b| f.area < faces[b].area).unwrap_or(true) {
            best = Some(i);
        }
    }
    let bi = best?;
    let fo = geom::offset::offset_ring(&g.pts(&faces[bi].ring), &edge_offsets(&g, &sub, &faces[bi].ring));
    let n = fo.len();
    let mut segs: Vec<(P2, P2)> = (0..n).map(|i| (fo[i], fo[(i + 1) % n])).collect();
    for c in cols {
        let ks: Vec<usize> = (0..lines.segs.len()).filter(|k| lines.src[*k] == *c).collect();
        segs.extend(ks.iter().map(|k| lines.segs[*k]));
    }
    let g2 = Graph::build(&segs, 1e-6);
    let f2 = g2.faces();
    let mut pick: Option<usize> = None;
    for (i, f) in f2.iter().enumerate() {
        if f.area > 0.0 && geom::inside(&g2.pts(&f.ring), q) && pick.map(|b| f.area < f2[b].area).unwrap_or(true) {
            pick = Some(i);
        }
    }
    pick.map(|i| g2.pts(&f2[i].ring))
}

/// The line each edge of a traced ring is a face of: the thickest lying along it (the first of
/// equals), by its index among the lines.
fn edge_lines(g: &Graph, lines: &Lines, ring: &[usize]) -> Vec<usize> {
    let n = ring.len();
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let (a, b) = (ring[i], ring[(i + 1) % n]);
        let k = g.edges.iter().position(|&(u, v)| (u == a && v == b) || (u == b && v == a));
        let mut s = k.map(|k| g.src[k]).unwrap_or(usize::MAX);
        let (pa, pb) = (g.verts[a], g.verts[b]);
        for (t, (q0, q1)) in lines.segs.iter().enumerate() {
            if geom::seg_dist(*q0, *q1, pa) <= 1e-6 && geom::seg_dist(*q0, *q1, pb) <= 1e-6 {
                let better = s == usize::MAX || lines.half[t] > lines.half[s] || (lines.half[t] == lines.half[s] && t < s);
                if better {
                    s = t;
                }
            }
        }
        out.push(s);
    }
    out
}

/// A ring moved out to the faces as the faces' own tracing gives it: no corner between two
/// pieces of one wall's face in line, starting where the first wall's face does.
fn as_faces_trace(g: &Graph, lines: &Lines, ring: &[usize], moved: Vec<P2>) -> Vec<P2> {
    let n = moved.len();
    let src = edge_lines(g, lines, ring);
    // corner i lies between edge i-1 and edge i
    let keep: Vec<bool> = (0..n)
        .map(|i| {
            let (prev, next) = (src[(i + n - 1) % n], src[i]);
            let a = moved[(i + n - 1) % n];
            let b = moved[i];
            let c = moved[(i + 1) % n];
            let in_line = geom::orient(a, b, c).abs() <= 1e-6 * geom::dist(a, c).max(1.0);
            !(prev == next && in_line)
        })
        .collect();
    if keep.iter().filter(|k| **k).count() < 3 {
        return moved;
    }
    // the first edge by its wall's order starts the ring
    let mut first = 0;
    for i in 0..n {
        if keep[i] && (src[i] < src[first] || !keep[first]) {
            first = i;
        }
    }
    (0..n).map(|k| (first + k) % n).filter(|i| keep[*i]).map(|i| moved[i]).collect()
}

/// A ring moved out to the faces that runs across itself cut back to the region round the point.
fn untangle(ring: Vec<P2>, q: P2) -> Vec<P2> {
    let n = ring.len();
    let mut crosses = false;
    'outer: for i in 0..n {
        for j in i + 2..n {
            if i == 0 && j == n - 1 {
                continue;
            }
            let (a0, a1, b0, b1) = (ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n]);
            let o1 = geom::orient(a0, a1, b0);
            let o2 = geom::orient(a0, a1, b1);
            let o3 = geom::orient(b0, b1, a0);
            let o4 = geom::orient(b0, b1, a1);
            if ((o1 > 0.0 && o2 < 0.0) || (o1 < 0.0 && o2 > 0.0)) && ((o3 > 0.0 && o4 < 0.0) || (o3 < 0.0 && o4 > 0.0)) {
                crosses = true;
                break 'outer;
            }
        }
    }
    if !crosses {
        return ring;
    }
    let segs: Vec<(P2, P2)> = (0..n).map(|i| (ring[i], ring[(i + 1) % n])).collect();
    let g = Graph::build(&segs, 1e-6);
    let faces = g.faces();
    let mut best: Option<(bool, f64, usize)> = None;
    for (i, f) in faces.iter().enumerate() {
        if f.area <= 0.0 {
            continue;
        }
        let pts = g.pts(&f.ring);
        let round = geom::inside(&pts, q);
        let better = match best {
            None => true,
            Some((r, a, _)) => (round && !r) || (round == r && f.area > a),
        };
        if better {
            best = Some((round, f.area, i));
        }
    }
    match best {
        Some((_, _, i)) => g.pts(&faces[i].ring),
        None => ring,
    }
}

fn on_ring(r: &[P2], p: P2) -> bool {
    let n = r.len();
    (0..n).any(|i| geom::seg_dist(r[i], r[(i + 1) % n], p) < 1e-9)
}

/// A room's own space as the model finds it now: its kept boundary when frozen, else the space
/// round its point (None: unbounded), and None too where an earlier room has that space.
pub fn room_space(pr: &Project, id: u64) -> Option<Space> {
    let e = pr.el(id)?;
    if flag(e, "frozen") == Some(true) {
        if let Some(k) = e.get("kept") {
            let c = k.get("centre").and_then(Region::from_value)?;
            let f = k.get("finish").and_then(Region::from_value).unwrap_or_else(|| c.clone());
            let round = k.get("finish").is_some();
            return Some(Space { centre: c, finish: f, finish_round: round });
        }
    }
    let level = level_of(pr, e)?;
    let q = pt(e, "point")?;
    let sp = space_at(pr, level, q)?;
    if redundant_with(pr, id, level, &sp).is_some() {
        return None;
    }
    Some(sp)
}

/// The earlier room (lower id) that has this space already.
pub fn redundant_with(pr: &Project, id: u64, level: u64, sp: &Space) -> Option<u64> {
    // a room whose point lies outside this space's box can't be in it
    let (mut lo, mut hi): (P2, P2) = ([f64::MAX; 2], [f64::MIN; 2]);
    for p in &sp.centre.outer {
        lo = [lo[0].min(p[0]), lo[1].min(p[1])];
        hi = [hi[0].max(p[0]), hi[1].max(p[1])];
    }
    for (oid, o) in &pr.elements {
        if *oid >= id || cat(o) != "room" || level_of(pr, o) != Some(level) {
            continue;
        }
        let other = if flag(o, "frozen") == Some(true) {
            o.get("kept").and_then(|k| k.get("centre")).and_then(Region::from_value)
        } else {
            let Some(oq) = pt(o, "point") else { continue };
            if oq[0] < lo[0] - 1.0 || oq[0] > hi[0] + 1.0 || oq[1] < lo[1] - 1.0 || oq[1] > hi[1] + 1.0 {
                continue;
            }
            space_at(pr, level, oq).map(|s| s.centre)
        };
        if let Some(oc) = other {
            if same_region(&oc, &sp.centre) {
                // the other must itself hold it (not be redundant with a third)
                return Some(*oid);
            }
        }
    }
    None
}

fn same_region(a: &Region, b: &Region) -> bool {
    if a.outer.len() != b.outer.len() {
        return false;
    }
    let pa = geom::area(&a.outer);
    let pb = geom::area(&b.outer);
    if (pa - pb).abs() > 1e-6 * pa.abs().max(1.0) {
        return false;
    }
    // the same corners
    a.outer.iter().all(|p| b.outer.iter().any(|q| geom::dist(*p, *q) < 1e-6))
}

/// Whether rooms are measured at the walls' faces.
pub fn at_finish(pr: &Project) -> bool {
    crate::styles::settings::room_area_of(pr) == "finish"
}

/// A room's area in mm² as the project measures rooms (0 when unbounded).
pub fn room_area(pr: &Project, id: u64) -> f64 {
    match room_space(pr, id) {
        Some(sp) => {
            if at_finish(pr) {
                sp.finish.area()
            } else {
                sp.centre.area()
            }
        }
        None => 0.0,
    }
}

/// The ceiling's outline round a point: the space's at the walls' faces, starting at its lowest
/// corner, and its islands as openings.
pub fn region_at_faces(pr: &Project, level: u64, q: P2) -> Option<(Vec<P2>, Vec<Vec<P2>>)> {
    // a point inside a wall: the wall's own footprint between its faces
    let z = elev(pr, level) + computation_height(pr, level);
    let walls: Vec<Wall> = Wall::all(pr).into_iter().filter(|w| w.spans(pr, z)).collect();
    for i in 0..walls.len() {
        if let Some(f) = super::walls::footprint(&walls, i) {
            if geom::inside_raw(&f, q) {
                return Some((super::roofs::round3(&f), Vec::new()));
            }
        }
    }
    let sp = space_in(pr, level, q, false)?;
    let outer = super::roofs::round3(&super::outline::drop_collinear(&sp.finish.outer));
    let holes = sp
        .finish
        .holes
        .iter()
        .map(|h| super::roofs::round3(&geom::start_lowest(&geom::cw(&super::outline::drop_collinear(h)))))
        .collect();
    Some((outer, holes))
}

pub fn room_word(lang: &str) -> &'static str {
    match lang {
        "pt" => "Ambiente",
        "es" => "Habitación",
        "sv" => "Rum",
        "cs" => "Místnost",
        "fr" => "Pièce",
        "nl" => "Ruimte",
        "de" => "Raum",
        "it" => "Zona",
        _ => "Room",
    }
}

/// The next room number: on in the series most rooms' numbers are in, else the next plain one.
pub fn next_number(pr: &Project) -> String {
    super::openings::next_series(pr, "room", "number")
}

pub fn cmd_room(s: &mut Session, p: &Value) -> R<Value> {
    let c = "room";
    let point = params::req_point(p, c, "point")?;
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let name = params::opt_text(p, c, "name")?;
    let number = params::opt_text(p, c, "number")?;
    let frozen = params::opt_bool(p, c, "frozen")?;
    let base_offset = params::opt_num(p, c, "base_offset")?;
    let limit_offset = params::opt_num(p, c, "limit_offset")?;
    let top_level = match params::get(p, "top_level") {
        Some(v) => Some(crate::model::resolve_level(pr, c, "top_level", v)?),
        None => None,
    };
    let name = match name {
        Some(n) => n,
        None => room_word(&pr.language()).to_string(),
    };
    let number = number.unwrap_or_else(|| next_number(pr));
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "level" => level_guid(pr, level),
        "point" => pv(point),
        "name" => name,
        "number" => number.clone(),
    };
    if let Some(b) = base_offset {
        e.set("base_offset", Value::f(b));
    }
    let (top, limit) = match (top_level, limit_offset) {
        (Some(t), l) => (Some(t), Some(l.unwrap_or(0.0))),
        (None, Some(l)) => (None, Some(l)),
        (None, None) => match crate::model::level_above(pr, level) {
            Some(a) => (Some(a), Some(-300.0)),
            None => (None, None),
        },
    };
    if let Some(t) = top {
        e.set("top_level", Value::Str(level_guid(pr, t)));
    }
    if let Some(l) = limit {
        e.set("limit_offset", Value::f(l));
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    let pr = &s.project;
    let sp = space_at(pr, level, point);
    let mut warning = None;
    let mut area = 0.0;
    match &sp {
        None => {
            warning = Some(format!(
                "{} isn't enclosed by walls or room separation lines on {}: the room is placed unbounded, a 1000 mm square, until they close round it",
                dp(point),
                level_name(pr, level)
            ));
        }
        Some(space) => match redundant_with(pr, id, level, space) {
            Some(other) => {
                warning = Some(format!(
                    "room {} is already in this space; two rooms can't share one, so this one is placed unbounded: move it, delete one of them, or part them with a room separation line",
                    other
                ));
            }
            None => {
                area = if at_finish(pr) { space.finish.area() } else { space.centre.area() };
            }
        },
    }
    if frozen == Some(true) {
        let bounded = warning.is_none();
        let e = s.project.el_mut(id).unwrap();
        e.set("frozen", Value::Bool(true));
        if bounded {
            let space = sp.unwrap();
            let mut kept = jobj! {"centre" => space.centre.to_value()};
            if space.finish_round {
                kept.set("finish", space.finish.to_value());
            }
            e.set("kept", kept);
        }
    }
    let mut out = jobj! {"area_m2" => m2(area), "id" => id, "number" => number};
    if let Some(w) = warning {
        out.set("warning", Value::Str(w));
    }
    Ok(out)
}

pub fn cmd_separator(s: &mut Session, p: &Value) -> R<Value> {
    let c = "room_separator";
    let points: Vec<P2> = match params::get(p, "points") {
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                match params::point_of(x) {
                    Some(q) => out.push(q),
                    None => return Err(format!("{}: `points`: {} is not a point [x, y] in mm", c, x.to_compact())),
                }
            }
            out
        }
        _ => return Err(format!("{}: `points` [[x, y], …] is required", c)),
    };
    if points.len() < 2 {
        return Err(format!("{}: `points` needs at least 2 points", c));
    }
    let closed = params::opt_bool(p, c, "closed")?.unwrap_or(false);
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let mut segs: Vec<(P2, P2)> = points.windows(2).map(|w| (w[0], w[1])).collect();
    if closed {
        segs.push((points[points.len() - 1], points[0]));
    }
    let mut ids = Vec::new();
    for (a, b) in segs {
        let pr = &s.project;
        let mut e = jobj! {
            "guid" => crate::rand::guid(),
            "category" => "roomseparator",
            "level" => level_guid(pr, level),
            "start" => pv(a),
            "end" => pv(b),
        };
        crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
        let id = s.project.alloc_id();
        s.project.elements.insert(id, e);
        ids.push(id);
    }
    Ok(jobj! {"ids" => ids})
}

// ---------------------------------------------------------------- the rules

pub fn check_room(pr: &Project, id: u64, e: &Value) -> R<()> {
    let level = level_of(pr, e);
    let lev = level.map(|l| elev(pr, l)).unwrap_or(0.0);
    let base = numd(e, "base_offset", 0.0);
    let top_level = e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level"));
    let limit = numd(e, "limit_offset", if top_level.is_none() && e.get("limit_offset").is_none() { 2500.0 } else { 0.0 });
    let upper = top_level.map(|t| elev(pr, t)).unwrap_or(lev);
    if !(upper + limit > lev + base) {
        return Err(format!(
            "room {}: the room's top (its upper limit {} + limit offset {}) must be above its bottom (its level {} + base offset {}); raise the limit offset or lower the base offset",
            id,
            d(upper),
            d(limit),
            d(lev),
            d(base)
        ));
    }
    if flag(e, "frozen") == Some(true) && e.get("kept").is_none() {
        return Err(format!(
            "room {}: the room is frozen but unbounded (not enclosed, or in a space another room has); a room is frozen with the boundary it has, so give it one first (walls or room separation lines round it, the other room deleted or parted from it), or leave it unfrozen",
            id
        ));
    }
    Ok(())
}
