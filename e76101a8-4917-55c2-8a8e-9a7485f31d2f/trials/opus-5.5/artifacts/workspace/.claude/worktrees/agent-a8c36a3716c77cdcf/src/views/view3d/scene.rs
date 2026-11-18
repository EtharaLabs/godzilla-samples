//! A stand-in for the model's geometry, as the 3D views and the spots read it (ARCH and STRUCTURE
//! own the real thing): each built element as pieces standing over outlines in plan, with the
//! height of their tops and bottoms over a point. `model_box` is what a section box is fitted
//! round; `top_at` and `slope_at` what a spot elevation or a spot slope reads.

use super::super::common::*;
use super::super::model as vm;
use crate::json::Value;
use crate::project::Project;
use std::collections::HashMap;

pub type P2 = [f64; 2];
pub type P3 = [f64; 3];

// ---------------------------------------------------------------- polygons

/// Whether a point is inside a polygon, as the original tests it (a crossing count: a point on a
/// west or south edge is in, on an east or north one out).
pub fn inside(poly: &[P2], p: P2) -> bool {
    let n = poly.len();
    if n < 3 {
        return false;
    }
    let mut c = false;
    let mut j = n - 1;
    for i in 0..n {
        let a = poly[i];
        let b = poly[j];
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
            if p[0] < x {
                c = !c;
            }
        }
        j = i;
    }
    c
}

/// Twice the signed area (positive counter-clockwise).
pub fn area2(poly: &[P2]) -> f64 {
    let n = poly.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = poly[i];
        let b = poly[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s
}

/// Inside an outline and out of its holes.
pub fn in_region(outline: &[P2], holes: &[Vec<P2>], p: P2) -> bool {
    inside(outline, p) && !holes.iter().any(|h| inside(h, p))
}

fn pts(v: Option<&Value>) -> Vec<P2> {
    v.and_then(|x| x.as_arr())
        .map(|a| a.iter().filter_map(|q| {
            let q = q.as_arr()?;
            Some([q.first()?.as_f64()?, q.get(1)?.as_f64()?])
        }).collect())
        .unwrap_or_default()
}

fn loops(v: Option<&Value>) -> Vec<Vec<P2>> {
    v.and_then(|x| x.as_arr()).map(|a| a.iter().map(|l| pts(Some(l))).filter(|l| l.len() >= 3).collect()).unwrap_or_default()
}

fn rot(p: P2, a: f64) -> P2 {
    let (s, c) = a.sin_cos();
    [p[0] * c - p[1] * s, p[0] * s + p[1] * c]
}

// ---------------------------------------------------------------- what the elements are

fn lib_type<'a>(pr: &'a Project, e: &Value, path: &[&str]) -> Option<&'a Value> {
    let name = lib_ref_name(pr, e, "type")?;
    let mut v = pr.section("types")?.get(path[0])?;
    for k in &path[1..] {
        v = v.get(k)?;
    }
    v.get(&name)
}

fn level_z(pr: &Project, e: &Value, k: &str) -> Option<f64> {
    let id = ref_id(pr, e, k)?;
    f_of(pr.el(id)?, "elevation")
}

fn base_z(pr: &Project, e: &Value) -> f64 {
    level_z(pr, e, "level").unwrap_or(0.0)
}

/// The heights a wall, a column or a mass spans: its base over its level and its top at its top
/// level (with `top_offset`) or `height` over its base.
pub fn base_top(pr: &Project, e: &Value) -> (f64, f64) {
    let base = base_z(pr, e) + f_of(e, "base_offset").unwrap_or(0.0);
    let top = match level_z(pr, e, "top_level") {
        Some(t) => t + f_of(e, "top_offset").unwrap_or(0.0),
        None => base + f_of(e, "height").unwrap_or(3000.0),
    };
    (base, top)
}

/// The categories a run is (a section swept along a line between two heights).
pub const RUNS: &[&str] = &[
    "beam",
    "pipe",
    "duct",
    "conduit",
    "cabletray",
    "wire",
    "downconductor",
    "groundconductor",
    "cable",
    "stripfooting",
];

/// What a spot elevation reads the top of.
pub fn spot_reads(c: &str) -> bool {
    matches!(
        c,
        "wall" | "floor" | "roof" | "stair" | "ramp" | "column" | "structuralcolumn" | "footing" | "railing" | "mass" | "component"
    ) || RUNS.contains(&c)
}

// ---------------------------------------------------------------- pieces

/// The height of a surface over a point.
#[derive(Clone, Debug)]
pub enum Height {
    Flat(f64),
    /// z = z0 + g · (p - o)
    Plane { o: P2, z0: f64, g: P2 },
    /// A shaped top: triangles in plan, each corner at its height.
    Tris(Vec<[P3; 3]>),
    /// A round run's upper (`up`) or lower surface: its section a 24-gon square to its axis.
    Tube(Tube, bool),
}

/// A round run: the plan point its axis starts at, its direction and length, its centre's height
/// at its start and its rise per mm, its radius.
#[derive(Clone, Copy, Debug)]
pub struct Tube {
    pub o: P2,
    pub u: P2,
    pub len: f64,
    pub end: P2,
    pub zc: f64,
    pub g: f64,
    pub r: f64,
}

/// How many sides a round section or a round post is drawn with.
pub const ROUND_SIDES: usize = 24;

/// How high a 24-gon of radius `r` (a corner at 0°) stands over its centre `y` across it.
fn upper_24(r: f64, y: f64) -> Option<f64> {
    if y.abs() > r {
        return None;
    }
    let n = ROUND_SIDES;
    let pts: Vec<P2> = (0..=n / 2)
        .map(|i| {
            let t = (i as f64 / n as f64) * std::f64::consts::TAU;
            [r * t.cos(), r * t.sin()]
        })
        .collect();
    for w in pts.windows(2) {
        let (a, b) = (w[0], w[1]);
        let (lo, hi) = (a[0].min(b[0]), a[0].max(b[0]));
        if y >= lo && y <= hi && hi > lo {
            return Some(a[1] + (b[1] - a[1]) * (y - a[0]) / (b[0] - a[0]));
        }
    }
    Some(0.0)
}

impl Tube {
    fn k(&self) -> f64 {
        (1.0 + self.g * self.g).sqrt()
    }
    fn at(&self, p: P2, up: bool) -> f64 {
        let v = vm::sub(p, self.o);
        let along = vm::dot(v, self.u);
        let across = vm::cross(self.u, v);
        let h = upper_24(self.r, across).unwrap_or(0.0) * self.k();
        let c = self.zc + self.g * along;
        if up {
            c + h
        } else {
            c - h
        }
    }
    /// The corners of its two end sections.
    fn corners(&self) -> Vec<P3> {
        let k = self.k();
        let lat = [-self.u[1], self.u[0], 0.0];
        let up = [-self.g * self.u[0] / k, -self.g * self.u[1] / k, 1.0 / k];
        let mut out = Vec::new();
        for (end, zc) in [(self.o, self.zc), (self.end, self.zc + self.g * self.len)] {
            for i in 0..ROUND_SIDES {
                let t = (i as f64 / ROUND_SIDES as f64) * std::f64::consts::TAU;
                let (c, s) = (t.cos() * self.r, t.sin() * self.r);
                out.push([end[0] + lat[0] * c + up[0] * s, end[1] + lat[1] * c + up[1] * s, zc + up[2] * s]);
            }
        }
        out
    }
}

impl Height {
    pub fn at(&self, p: P2) -> f64 {
        match self {
            Height::Flat(z) => *z,
            Height::Plane { o, z0, g } => z0 + g[0] * (p[0] - o[0]) + g[1] * (p[1] - o[1]),
            Height::Tris(ts) => tris_at(ts, p).map(|(z, _)| z).unwrap_or_else(|| {
                ts.iter().flat_map(|t| t.iter().map(|q| q[2])).fold(f64::NEG_INFINITY, f64::max)
            }),
            Height::Tube(t, up) => t.at(p, *up),
        }
    }
    /// How it rises over a point: its gradient (none where it is flat everywhere).
    pub fn gradient(&self, p: P2) -> P2 {
        match self {
            Height::Flat(_) => [0.0, 0.0],
            Height::Plane { g, .. } => *g,
            Height::Tris(ts) => tris_at(ts, p).map(|(_, g)| g).unwrap_or([0.0, 0.0]),
            Height::Tube(t, _) => [t.u[0] * t.g, t.u[1] * t.g],
        }
    }
}

/// The triangle of a triangulated top a point lies in.
fn tri_under(ts: &[[P3; 3]], p: P2) -> Option<[P3; 3]> {
    ts.iter()
        .find(|t| {
            let (a, b, c) = (t[0], t[1], t[2]);
            let det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
            if det == 0.0 {
                return false;
            }
            let l1 = ((b[0] - p[0]) * (c[1] - p[1]) - (c[0] - p[0]) * (b[1] - p[1])) / det;
            let l2 = ((c[0] - p[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (c[1] - p[1])) / det;
            l1 >= -1e-9 && l2 >= -1e-9 && 1.0 - l1 - l2 >= -1e-9
        })
        .copied()
}

/// The height and gradient of a triangulated top over a point (none off it): the highest of the
/// triangles over it.
fn tris_at(ts: &[[P3; 3]], p: P2) -> Option<(f64, P2)> {
    let mut best: Option<(f64, P2)> = None;
    for t in ts {
        let (a, b, c) = (t[0], t[1], t[2]);
        let det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
        if det == 0.0 {
            continue;
        }
        let l1 = ((b[0] - p[0]) * (c[1] - p[1]) - (c[0] - p[0]) * (b[1] - p[1])) / det;
        let l2 = ((c[0] - p[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (c[1] - p[1])) / det;
        let l3 = 1.0 - l1 - l2;
        let eps = -1e-9;
        if l1 >= eps && l2 >= eps && l3 >= eps {
            let z = l1 * a[2] + l2 * b[2] + l3 * c[2];
            // the plane's gradient
            let gx = ((b[2] - a[2]) * (c[1] - a[1]) - (c[2] - a[2]) * (b[1] - a[1])) / det;
            let gy = ((c[2] - a[2]) * (b[0] - a[0]) - (b[2] - a[2]) * (c[0] - a[0])) / det;
            if best.map_or(true, |(bz, _)| z > bz) {
                best = Some((z, [gx, gy]));
            }
        }
    }
    best
}

/// A Delaunay triangulation of points (Bowyer and Watson's).
fn delaunay(pts: &[P2]) -> Vec<[usize; 3]> {
    let n = pts.len();
    if n < 3 {
        return Vec::new();
    }
    let (mut lo, mut hi) = (pts[0], pts[0]);
    for q in pts {
        lo = [lo[0].min(q[0]), lo[1].min(q[1])];
        hi = [hi[0].max(q[0]), hi[1].max(q[1])];
    }
    let d = (hi[0] - lo[0]).max(hi[1] - lo[1]).max(1.0) * 20.0;
    let m = vm::mid(lo, hi);
    let mut all: Vec<P2> = pts.to_vec();
    all.push([m[0] - d, m[1] - d]);
    all.push([m[0] + d, m[1] - d]);
    all.push([m[0], m[1] + d]);
    let mut tris: Vec<[usize; 3]> = vec![[n, n + 1, n + 2]];
    let circ = |t: &[usize; 3], q: P2, all: &Vec<P2>| -> bool {
        let (a, b, c) = (all[t[0]], all[t[1]], all[t[2]]);
        let (ax, ay) = (a[0] - q[0], a[1] - q[1]);
        let (bx, by) = (b[0] - q[0], b[1] - q[1]);
        let (cx, cy) = (c[0] - q[0], c[1] - q[1]);
        let det = (ax * ax + ay * ay) * (bx * cy - cx * by) - (bx * bx + by * by) * (ax * cy - cx * ay)
            + (cx * cx + cy * cy) * (ax * by - bx * ay);
        let orient = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
        if orient > 0.0 {
            det > 1e-9
        } else {
            det < -1e-9
        }
    };
    for i in 0..n {
        let q = all[i];
        let bad: Vec<usize> = (0..tris.len()).filter(|k| circ(&tris[*k], q, &all)).collect();
        let mut edges: Vec<(usize, usize)> = Vec::new();
        for &k in &bad {
            let t = tris[k];
            for (a, b) in [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])] {
                if let Some(pos) = edges.iter().position(|e| (e.0 == b && e.1 == a) || (e.0 == a && e.1 == b)) {
                    edges.remove(pos);
                } else {
                    edges.push((a, b));
                }
            }
        }
        let mut keep: Vec<[usize; 3]> = tris.iter().enumerate().filter(|(k, _)| !bad.contains(k)).map(|(_, t)| *t).collect();
        for (a, b) in edges {
            keep.push([a, b, i]);
        }
        tris = keep;
    }
    tris.into_iter().filter(|t| t.iter().all(|v| *v < n)).collect()
}

/// A prism of the model: an outline (less its holes) between a bottom and a top.
#[derive(Clone, Debug)]
pub struct Piece {
    pub outline: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
    pub bottom: Height,
    pub top: Height,
}

impl Piece {
    fn flat(outline: Vec<P2>, bottom: f64, top: f64) -> Piece {
        Piece { outline, holes: Vec::new(), bottom: Height::Flat(bottom), top: Height::Flat(top) }
    }
    fn contains(&self, p: P2) -> bool {
        in_region(&self.outline, &self.holes, p)
    }
}

/// A box in space being grown.
#[derive(Clone, Copy, Debug)]
pub struct Bounds {
    pub lo: P3,
    pub hi: P3,
    pub any: bool,
}

impl Default for Bounds {
    fn default() -> Bounds {
        Bounds { lo: [0.0; 3], hi: [0.0; 3], any: false }
    }
}

impl Bounds {
    pub fn add(&mut self, p: P3) {
        if !p.iter().all(|x| x.is_finite()) {
            return;
        }
        if !self.any {
            self.lo = p;
            self.hi = p;
            self.any = true;
            return;
        }
        for i in 0..3 {
            self.lo[i] = self.lo[i].min(p[i]);
            self.hi[i] = self.hi[i].max(p[i]);
        }
    }
    fn add_piece(&mut self, pc: &Piece) {
        if let Height::Tube(t, _) = &pc.top {
            for q in t.corners() {
                self.add(q);
            }
            return;
        }
        for h in [&pc.bottom, &pc.top] {
            if let Height::Tris(ts) = h {
                for t in ts {
                    for q in t {
                        self.add(*q);
                    }
                }
            }
        }
        for q in &pc.outline {
            if !matches!(pc.bottom, Height::Tris(_)) {
                self.add([q[0], q[1], pc.bottom.at(*q)]);
            }
            if !matches!(pc.top, Height::Tris(_)) {
                self.add([q[0], q[1], pc.top.at(*q)]);
            }
        }
    }
}

// ---------------------------------------------------------------- walls

/// A wall's footprint (its faces joined at its corners) and its heights.
#[derive(Clone, Debug)]
pub struct WallGeo {
    pub outline: Vec<P2>,
    pub base: f64,
    pub top: f64,
    /// What its top follows (a roof's or a floor's underside) and its base (a floor's top).
    pub attach_top: Option<u64>,
    pub attach_base: Option<u64>,
}

impl WallGeo {
    /// Its top over a point of it: its own, or the underside of what it is attached to there.
    fn top_at(&self, pr: &Project, p: P2) -> f64 {
        self.attach_top.and_then(|r| under_at(pr, r, p)).unwrap_or(self.top)
    }
    /// Its base over a point of it: its own, or the top of what it stands attached to there.
    fn base_at(&self, pr: &Project, p: P2) -> f64 {
        self.attach_base.and_then(|f| top_of_at(pr, f, p)).unwrap_or(self.base)
    }
}

/// Two walls meet in a corner they are mitred at only if they turn enough: the cosine of the
/// angle between them at most this.
const MITRE_COS: f64 = 0.6;
/// Ends this close (mm) are one corner.
const JOIN_GAP: f64 = 1.0;

/// The centre and radius of the arc from `a` to `b` turning `deg` degrees counter-clockwise, as
/// the original works them out (the centre off the chord's middle by half the chord over the
/// tangent of half the turn).
pub fn arc_circle(a: P2, b: P2, deg: f64) -> Option<(P2, f64)> {
    let t = deg.to_radians();
    let c = vm::dist(a, b);
    if c == 0.0 || t == 0.0 {
        return None;
    }
    let r = c / (2.0 * (t / 2.0).sin().abs());
    let m = vm::mid(a, b);
    let h = (c / 2.0) / (t / 2.0).tan();
    let n = vm::left_normal(a, b);
    Some(([m[0] + n[0] * h, m[1] + n[1] * h], r))
}

/// How many straight pieces an arc of a wall is drawn with: each strays at most a millimetre from
/// the arc on its centre line.
pub fn arc_segments(radius: f64, sweep_deg: f64) -> usize {
    if radius <= 1.0 {
        return 1;
    }
    let step = 2.0 * (1.0 - 1.0 / radius).acos();
    let n = (sweep_deg.abs().to_radians() / step).ceil();
    if n.is_finite() && n >= 1.0 {
        (n as usize).min(10_000)
    } else {
        1
    }
}

/// A face of a wall: its points from the wall's start to its end, and the direction it leaves
/// each end in (into the wall).
#[derive(Clone, Debug)]
struct Face {
    pts: Vec<P2>,
}

impl Face {
    fn start_dir(&self) -> P2 {
        vm::unit(vm::sub(self.pts[1], self.pts[0]))
    }
    fn end_dir(&self) -> P2 {
        let n = self.pts.len();
        vm::unit(vm::sub(self.pts[n - 1], self.pts[n - 2]))
    }
}

fn face_of(line: &vm::WallLine, n: usize) -> Face {
    Face { pts: line.points(n) }
}

/// Where two lines (each a point and a direction) cross.
fn cross_lines(p: P2, d: P2, q: P2, e: P2) -> Option<P2> {
    let den = vm::cross(d, e);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = vm::cross(vm::sub(q, p), e) / den;
    Some([p[0] + d[0] * t, p[1] + d[1] * t])
}

struct WallPrep {
    id: u64,
    level: String,
    loc: vm::WallLine,
    left: Face,
    right: Face,
}

/// Every wall's footprint, joined at its corners as the original joins them.
pub fn walls(pr: &Project) -> HashMap<u64, WallGeo> {
    let mut preps: Vec<WallPrep> = Vec::new();
    for (id, e) in &pr.elements {
        if cat(e) != "wall" {
            continue;
        }
        let loc = vm::location_line(e);
        if vm::dist(loc.start, loc.end) <= 0.0 {
            continue;
        }
        let t = vm::wall_thickness(pr, e);
        let off = vm::centre_offset(pr, e);
        let (left, right) = if loc.is_arc() {
            // the faces are arcs about the location line's centre, its points at even steps of the turn
            let Some((c, r)) = arc_circle(loc.start, loc.end, loc.arc) else { continue };
            let ccw = loc.arc > 0.0;
            // left of a counter-clockwise arc is toward its centre
            let rc = if ccw { r - off } else { r + off };
            let n = arc_segments(rc, loc.arc);
            let (rl, rr) = if ccw { (rc - t / 2.0, rc + t / 2.0) } else { (rc + t / 2.0, rc - t / 2.0) };
            let a0 = (loc.start[1] - c[1]).atan2(loc.start[0] - c[0]);
            let sweep = loc.arc.to_radians();
            let ring = |rad: f64| -> Face {
                Face {
                    pts: (0..=n)
                        .map(|i| {
                            let a = a0 + sweep * (i as f64 / n as f64);
                            [c[0] + rad * a.cos(), c[1] + rad * a.sin()]
                        })
                        .collect(),
                }
            };
            (ring(rl), ring(rr))
        } else {
            let centre = vm::centre_line(pr, e);
            (face_of(&centre.offset(t / 2.0), 1), face_of(&centre.offset(-t / 2.0), 1))
        };
        preps.push(WallPrep { id: *id, level: s_of(e, "level").unwrap_or("").to_string(), loc, left, right });
    }
    // ends meeting: (wall index, which end: false start / true end), found through a grid
    let mut ends: Vec<(usize, bool, P2)> = Vec::new();
    for (i, w) in preps.iter().enumerate() {
        ends.push((i, false, w.loc.start));
        ends.push((i, true, w.loc.end));
    }
    let cell = |p: P2| ((p[0] / 4.0).floor() as i64, (p[1] / 4.0).floor() as i64);
    let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
    for (k, (_, _, p)) in ends.iter().enumerate() {
        grid.entry(cell(*p)).or_default().push(k);
    }
    let near_ends = |k: usize| -> Vec<usize> {
        let (wi, _, pa) = ends[k];
        let (cx, cy) = cell(pa);
        let mut out = Vec::new();
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(v) = grid.get(&(cx + dx, cy + dy)) {
                    for &b in v {
                        let (wj, _, pb) = ends[b];
                        if wj != wi && preps[wj].level == preps[wi].level && vm::dist(pa, pb) <= JOIN_GAP {
                            out.push(b);
                        }
                    }
                }
            }
        }
        out.sort();
        out
    };
    // the cut each end gets: (left point, right point)
    let mut cuts: HashMap<(usize, bool), (P2, P2)> = HashMap::new();
    let end_faces = |w: &WallPrep, at_end: bool| -> ((P2, P2), (P2, P2)) {
        if at_end {
            ((*w.left.pts.last().unwrap(), w.left.end_dir()), (*w.right.pts.last().unwrap(), w.right.end_dir()))
        } else {
            ((w.left.pts[0], w.left.start_dir()), (w.right.pts[0], w.right.start_dir()))
        }
    };
    for a in 0..ends.len() {
        let (wi, we, pa) = ends[a];
        let others = near_ends(a);
        let wa = &preps[wi];
        if others.is_empty() {
            // an end on another wall's line, short of its ends: cut back to that wall's face
            let away = if we { vm::mul(wa.left.end_dir(), -1.0) } else { wa.left.start_dir() };
            for wb in preps.iter() {
                if wb.id == wa.id || wb.level != wa.level || wb.loc.is_arc() {
                    continue;
                }
                let (s0, s1) = (wb.loc.start, wb.loc.end);
                let len = vm::dist(s0, s1);
                let u = vm::unit(vm::sub(s1, s0));
                let along = vm::dot(vm::sub(pa, s0), u);
                // the end within the other wall's thickness, between its faces
                let dl = vm::cross(u, vm::sub(pa, wb.left.pts[0]));
                let dr = vm::cross(u, vm::sub(pa, wb.right.pts[0]));
                if dl > JOIN_GAP || dr < -JOIN_GAP || along <= JOIN_GAP || along >= len - JOIN_GAP {
                    continue;
                }
                let n = [-u[1], u[0]];
                let face = if vm::dot(away, n) > 0.0 { &wb.left } else { &wb.right };
                let fp = face.pts[0];
                let (a_l, a_r) = end_faces(wa, we);
                if let (Some(pl), Some(prr)) = (cross_lines(a_l.0, a_l.1, fp, u), cross_lines(a_r.0, a_r.1, fp, u)) {
                    cuts.insert((wi, we), (pl, prr));
                }
                break;
            }
            continue;
        }
        if others.len() != 1 {
            continue;
        }
        let (wj, wje, _) = ends[others[0]];
        let wb = &preps[wj];
        // the directions away from the corner along each wall's faces
        let da = if we { vm::mul(wa.left.end_dir(), -1.0) } else { wa.left.start_dir() };
        let db = if wje { vm::mul(wb.left.end_dir(), -1.0) } else { wb.left.start_dir() };
        if vm::dot(da, db) > MITRE_COS {
            continue;
        }
        // the faces at the corner: a's left runs on into b's left where one ends as the other
        // starts, into its right where both end (or both start) there
        let (a_l, a_r) = end_faces(wa, we);
        let (b_l, b_r) = end_faces(wb, wje);
        let same = we != wje;
        let (b_for_l, b_for_r) = if same { (b_l, b_r) } else { (b_r, b_l) };
        let pl = cross_lines(a_l.0, a_l.1, b_for_l.0, b_for_l.1);
        let prr = cross_lines(a_r.0, a_r.1, b_for_r.0, b_for_r.1);
        if let (Some(pl), Some(prr)) = (pl, prr) {
            cuts.insert((wi, we), (pl, prr));
        }
    }
    let mut out = HashMap::new();
    for (i, w) in preps.iter().enumerate() {
        let e = pr.el(w.id).unwrap();
        let mut left = w.left.pts.clone();
        let mut right = w.right.pts.clone();
        if let Some((l, r)) = cuts.get(&(i, false)) {
            left[0] = *l;
            right[0] = *r;
        }
        if let Some((l, r)) = cuts.get(&(i, true)) {
            *left.last_mut().unwrap() = *l;
            *right.last_mut().unwrap() = *r;
        }
        let mut outline = left;
        right.reverse();
        outline.extend(right);
        let (base, top) = base_top(pr, e);
        out.insert(w.id, WallGeo { outline, base, top, attach_top: None, attach_base: None });
    }
    out
}

// ---------------------------------------------------------------- floors and ceilings

fn floor_top(pr: &Project, e: &Value) -> (Height, f64) {
    let base = base_z(pr, e) + f_of(e, "offset").unwrap_or(0.0);
    let slope = f_of(e, "slope").unwrap_or(0.0);
    let arrow = pts(e.get("arrow"));
    if slope != 0.0 && arrow.len() == 2 && vm::dist(arrow[0], arrow[1]) > 0.0 {
        let d = vm::sub(arrow[1], arrow[0]);
        let l = vm::norm(d);
        let u = [d[0] / l, d[1] / l];
        let t = slope.to_radians().tan();
        (Height::Plane { o: arrow[0], z0: base, g: [u[0] * t, u[1] * t] }, slope)
    } else {
        (Height::Flat(base), 0.0)
    }
}

fn floor_piece(pr: &Project, e: &Value) -> Option<Piece> {
    let outline = pts(e.get("boundary"));
    if outline.len() < 3 {
        return None;
    }
    let holes = loops(e.get("openings"));
    let th = lib_type(pr, e, &["floor"]).and_then(|t| f_of(t, "thickness")).unwrap_or(200.0);
    let (top, slope) = floor_top(pr, e);
    let plumb = th / slope.to_radians().cos();
    if let (Height::Flat(z), Some(ts)) = (&top, shaped(e, &outline, &holes)) {
        // a shaped top: its triangles lifted by its points, its type's thickness plumb under them
        let tops: Vec<[P3; 3]> = ts.iter().map(|t| t.map(|q| [q[0], q[1], z + q[2]])).collect();
        let bottoms: Vec<[P3; 3]> = tops.iter().map(|t| t.map(|q| [q[0], q[1], q[2] - th])).collect();
        return Some(Piece { outline, holes, bottom: Height::Tris(bottoms), top: Height::Tris(tops) });
    }
    let bottom = match &top {
        Height::Flat(z) => Height::Flat(z - plumb),
        Height::Plane { o, z0, g } => Height::Plane { o: *o, z0: z0 - plumb, g: *g },
        Height::Tris(_) | Height::Tube(..) => top.clone(),
    };
    Some(Piece { outline, holes, bottom, top })
}

/// A floor's shaped top: its outline, its openings' corners and its points triangulated, each
/// corner at the height its point gives it over the top (a corner with none at 0).
fn shaped(e: &Value, outline: &[P2], holes: &[Vec<P2>]) -> Option<Vec<[P3; 3]>> {
    let ps = e.get("shape")?.get("points")?.as_arr()?;
    let marks: Vec<(P2, f64)> = ps.iter().filter_map(|q| Some((pt_of(q, "at")?, f_of(q, "z")?))).collect();
    if marks.is_empty() {
        return None;
    }
    let mut pts: Vec<P2> = Vec::new();
    for q in outline.iter().chain(holes.iter().flatten()) {
        if !pts.iter().any(|x| vm::dist(*x, *q) < 1e-6) {
            pts.push(*q);
        }
    }
    for (q, _) in &marks {
        if !pts.iter().any(|x| vm::dist(*x, *q) < 1e-6) {
            pts.push(*q);
        }
    }
    let z_of = |q: P2| marks.iter().find(|(m, _)| vm::dist(*m, q) < 1e-6).map(|(_, z)| *z).unwrap_or(0.0);
    let mut out = Vec::new();
    for t in delaunay(&pts) {
        let (a, b, c) = (pts[t[0]], pts[t[1]], pts[t[2]]);
        let g = [(a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0];
        if !in_region(outline, holes, g) {
            continue;
        }
        let ccw = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]) > 0.0;
        let (b, c) = if ccw { (b, c) } else { (c, b) };
        out.push([[a[0], a[1], z_of(a)], [b[0], b[1], z_of(b)], [c[0], c[1], z_of(c)]]);
    }
    (!out.is_empty()).then_some(out)
}


fn ceiling_piece(pr: &Project, e: &Value) -> Option<Piece> {
    let outline = pts(e.get("boundary"));
    if outline.len() < 3 {
        return None;
    }
    let th = lib_type(pr, e, &["ceiling"]).and_then(|t| f_of(t, "thickness")).unwrap_or(20.0);
    let under = base_z(pr, e) + f_of(e, "offset").unwrap_or(2600.0);
    Some(Piece { outline, holes: loops(e.get("openings")), bottom: Height::Flat(under), top: Height::Flat(under + th) })
}

// ---------------------------------------------------------------- roofs

/// An edge of a roof by footprint: its ends, its inward unit normal, its slope in degrees (none:
/// a gable, upright) and the edges before and after it round its ring.
#[derive(Clone, Debug)]
pub struct RoofEdge {
    pub a: P2,
    pub b: P2,
    pub n: P2,
    pub slope: Option<f64>,
    pub prev: usize,
    pub next: usize,
}

/// A roof by footprint: its outline and courtyards, and each edge's slope.
#[derive(Clone, Debug)]
pub struct RoofGeo {
    pub outline: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
    pub edges: Vec<RoofEdge>,
    pub base: f64,
    pub overhang: f64,
    pub slope: f64,
    pub thickness: f64,
}

fn roof_geo(pr: &Project, e: &Value) -> Option<RoofGeo> {
    let outline = pts(e.get("boundary"));
    if outline.len() < 3 {
        return None;
    }
    let holes = loops(e.get("courtyards"));
    let slope = f_of(e, "slope").unwrap_or(0.0);
    let overhang = f_of(e, "overhang").unwrap_or(0.0);
    let base = base_z(pr, e) + f_of(e, "offset").unwrap_or(0.0);
    let thickness = lib_type(pr, e, &["roof"]).and_then(|t| f_of(t, "thickness")).unwrap_or(300.0);
    let mut gables: Vec<usize> = e
        .get("gables")
        .and_then(|g| g.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_f64()).map(|x| x as usize).collect())
        .unwrap_or_default();
    if e.get("gable").and_then(|g| g.as_bool()) == Some(true) && outline.len() == 4 {
        let l: Vec<f64> = (0..4).map(|i| vm::dist(outline[i], outline[(i + 1) % 4])).collect();
        if l[0] + l[2] <= l[1] + l[3] {
            gables.extend([0, 2]);
        } else {
            gables.extend([1, 3]);
        }
    }
    let slopes: Vec<f64> = e
        .get("slopes")
        .and_then(|s| s.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_f64()).collect())
        .unwrap_or_default();
    let mut edges: Vec<RoofEdge> = Vec::new();
    let mut rings: Vec<(&Vec<P2>, bool)> = vec![(&outline, false)];
    for h in &holes {
        rings.push((h, true));
    }
    for (poly, hole) in rings {
        let ccw = area2(poly) > 0.0;
        // the roof lies left of an outline running counter-clockwise and of a courtyard running
        // clockwise: a ring the other way round is walked back (its edges keep their numbers)
        let forward = ccw != hole;
        let n = poly.len();
        let first = edges.len();
        for i in 0..n {
            let k = first + i;
            let a = poly[i];
            let b = poly[(i + 1) % n];
            let inward = if forward { vm::left_normal(a, b) } else { vm::left_normal(b, a) };
            let s = if gables.contains(&k) {
                None
            } else {
                let own = slopes.get(k).cloned().unwrap_or(0.0);
                Some(if own == 0.0 { slope } else { own })
            };
            let prev = first + (i + n - 1) % n;
            let next = first + (i + 1) % n;
            edges.push(RoofEdge { a, b, n: inward, slope: s, prev, next });
        }
    }
    Some(RoofGeo { outline, holes, edges, base, overhang, slope, thickness })
}

impl RoofGeo {
    fn flat(&self) -> bool {
        self.slope == 0.0 || self.edges.iter().all(|e| e.slope.is_none())
    }
    /// How far a point lies in from an edge's line.
    fn d(&self, i: usize, p: P2) -> f64 {
        let e = &self.edges[i];
        vm::dot(vm::sub(p, e.a), e.n)
    }
    /// How high an edge's slope stands over a point (rising from its eave).
    fn rise(&self, i: usize, p: P2) -> Option<f64> {
        let s = self.edges[i].slope?;
        Some(self.d(i, p) * s.to_radians().tan())
    }
    /// Whether a point lies in the reach of an edge's slope: inward of it, and on its side of the
    /// lines where it meets the slopes before and after it (where it meets a gable, of the gable).
    fn reaches(&self, i: usize, p: P2) -> bool {
        let e = &self.edges[i];
        let scale = vm::dist(e.a, e.b).max(1.0);
        let eps = 1e-9 * scale;
        if self.d(i, p) < -eps {
            return false;
        }
        let Some(hp) = self.rise(i, p) else { return false };
        for (v, other, f) in [(e.a, e.b, e.prev), (e.b, e.a, e.next)] {
            if f == i {
                continue;
            }
            match self.rise(f, p) {
                None => {
                    if self.d(f, p) < -eps {
                        return false;
                    }
                }
                Some(fp) => {
                    // which side of where the two meet the edge itself lies, by a point of it near the corner
                    let m = vm::add(v, vm::mul(vm::sub(other, v), 1e-3));
                    let sm = self.rise(i, m).unwrap() - self.rise(f, m).unwrap();
                    if sm == 0.0 {
                        continue;
                    }
                    if (hp - fp) * sm.signum() < -eps {
                        return false;
                    }
                }
            }
        }
        true
    }
    /// The sloped edge whose slope the point lies under, and its distance in.
    fn face_at(&self, p: P2) -> Option<(usize, f64)> {
        let mut best: Option<(usize, f64)> = None;
        for i in 0..self.edges.len() {
            if self.edges[i].slope.is_none() || !self.reaches(i, p) {
                continue;
            }
            let h = self.rise(i, p).unwrap();
            if best.map_or(true, |(_, bh)| h < bh) {
                best = Some((i, h));
            }
        }
        if best.is_none() {
            // a point no slope reaches (as the stand-in sees it): the lowest slope over it
            for i in 0..self.edges.len() {
                let Some(h) = self.rise(i, p) else { continue };
                if self.d(i, p) < 0.0 {
                    continue;
                }
                if best.map_or(true, |(_, bh)| h < bh) {
                    best = Some((i, h));
                }
            }
        }
        best.map(|(i, _)| (i, self.d(i, p)))
    }
    /// The underside and the top over a point of it.
    pub fn heights(&self, p: P2) -> (f64, f64) {
        if self.flat() {
            return (self.base, self.base + self.thickness);
        }
        let Some((i, d)) = self.face_at(p) else { return (self.base, self.base + self.thickness) };
        let s = self.edges[i].slope.unwrap();
        self.heights_on(s, d)
    }
    fn heights_on(&self, s: f64, d: f64) -> (f64, f64) {
        let t = s.to_radians().tan();
        let h = self.thickness / s.to_radians().cos();
        if s == self.slope {
            (self.base + (d - self.overhang) * t, (self.base + h) + (d - self.overhang) * t)
        } else {
            let o = self.overhang * self.slope.to_radians().tan();
            (self.base + d * t - o, (self.base + h) + d * t - o)
        }
    }
    /// How steeply it falls at a point, and the way down in plan (none where it is level).
    pub fn slope_at(&self, p: P2) -> (f64, Option<P2>) {
        if self.flat() {
            return (0.0, None);
        }
        match self.face_at(p) {
            Some((i, _)) => {
                let e = &self.edges[i];
                let s = e.slope.unwrap();
                if s == 0.0 {
                    (0.0, None)
                } else {
                    (s.to_radians().tan(), Some([-e.n[0], -e.n[1]]))
                }
            }
            None => (0.0, None),
        }
    }
    /// Its highest top: where its slopes meet highest.
    fn max_top(&self) -> f64 {
        if self.flat() {
            return self.base + self.thickness;
        }
        let mut cands: Vec<P2> = self.outline.clone();
        for h in &self.holes {
            cands.extend(h.iter().cloned());
        }
        // where two slopes are as high, along each edge of the outline; where three are
        let sloped: Vec<(P2, P2, f64)> =
            self.edges.iter().filter_map(|e| e.slope.map(|s| (e.a, e.n, s.to_radians().tan()))).collect();
        let mut rings: Vec<&Vec<P2>> = vec![&self.outline];
        rings.extend(self.holes.iter());
        let mut nodes: Vec<(P2, f64, bool)> = Vec::new();
        for i in 0..sloped.len() {
            for j in (i + 1)..sloped.len() {
                // h_i(p) = h_j(p): (n_i t_i - n_j t_j) · p = n_i·a_i t_i - n_j·a_j t_j
                let (ai, ni, ti) = sloped[i];
                let (aj, nj, tj) = sloped[j];
                let g = [ni[0] * ti - nj[0] * tj, ni[1] * ti - nj[1] * tj];
                let c = vm::dot(ni, ai) * ti - vm::dot(nj, aj) * tj;
                for ring in &rings {
                    let n = ring.len();
                    for k in 0..n {
                        let p = ring[k];
                        let q = ring[(k + 1) % n];
                        let fp = vm::dot(g, p) - c;
                        let fq = vm::dot(g, q) - c;
                        if ((fp <= 0.0 && fq >= 0.0) || (fp >= 0.0 && fq <= 0.0)) && fp != fq {
                            let t = fp / (fp - fq);
                            cands.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
                        }
                    }
                }
                for k in (j + 1)..sloped.len() {
                    if let Some(c) = meet3([sloped[i], sloped[j], sloped[k]]) {
                        nodes.push(c);
                    }
                }
            }
        }
        let mut best = f64::NEG_INFINITY;
        for p in cands {
            if !self.covers(p) {
                continue;
            }
            best = best.max(self.top_where_they_meet(p));
        }
        // where three slopes meet: the height they meet at, worked out with the point
        for (p, value, same) in nodes {
            if !self.covers(p) {
                continue;
            }
            let Some((i, d)) = self.face_at(p) else { continue };
            let si = self.edges[i].slope.unwrap();
            // a node all of one slope (the roof's): its distance in as the three edges give it
            let top = if same && si == self.slope && (d - value).abs() <= 1e-6 {
                self.heights_on(si, value).1
            } else {
                self.top_where_they_meet(p)
            };
            best = best.max(top);
        }
        if best.is_finite() {
            best
        } else {
            self.base + self.thickness
        }
    }
    /// The top over a point where slopes meet: the highest of the tops of the slopes there, each
    /// its own thickness plumb over the underside they share.
    fn top_where_they_meet(&self, p: P2) -> f64 {
        let Some((i, d)) = self.face_at(p) else { return self.heights(p).1 };
        let si = self.edges[i].slope.unwrap();
        let env = d * si.to_radians().tan();
        let mut top = self.heights_on(si, d).1;
        for j in 0..self.edges.len() {
            let Some(sj) = self.edges[j].slope else { continue };
            if j == i || sj == si || !self.reaches(j, p) {
                continue;
            }
            let dj = self.d(j, p);
            if (dj * sj.to_radians().tan() - env).abs() <= 1e-6 {
                top = top.max(self.heights_on(sj, dj).1);
            }
        }
        top
    }
    /// A point of it, its edges too.
    fn covers(&self, p: P2) -> bool {
        let near = |poly: &Vec<P2>| {
            let n = poly.len();
            (0..n).any(|i| seg_dist(p, poly[i], poly[(i + 1) % n]) < 1e-6)
        };
        (inside(&self.outline, p) || near(&self.outline)) && !self.holes.iter().any(|h| inside(h, p) && !near(h))
    }
    fn min_under(&self) -> f64 {
        let mut lo = f64::INFINITY;
        for q in self.outline.iter().chain(self.holes.iter().flatten()) {
            lo = lo.min(self.heights(*q).0);
        }
        if lo.is_finite() {
            lo
        } else {
            self.base
        }
    }
}

/// Where three slopes (a point of each edge, its inward normal, its rise per mm in) stand as high:
/// the point and, where all three rise alike, how far in it is from each (else how high it is),
/// and whether they rise alike.
fn meet3(e: [(P2, P2, f64); 3]) -> Option<(P2, f64, bool)> {
    let same = e[0].2 == e[1].2 && e[1].2 == e[2].2;
    // each: k n·p - h = k n·a, with k the rise per mm (1 where all rise alike: h is then the distance in)
    let row = |(a, n, t): (P2, P2, f64)| {
        let k = if same { 1.0 } else { t };
        (k * n[0], k * n[1], k * vm::dot(n, a))
    };
    let (a1, b1, c1) = row(e[0]);
    let (a2, b2, c2) = row(e[1]);
    let (a3, b3, c3) = row(e[2]);
    let (p, q, r) = (a1 - a2, b1 - b2, c1 - c2);
    let (u, v, w) = (a1 - a3, b1 - b3, c1 - c3);
    let det = p * v - q * u;
    if det.abs() < 1e-12 {
        return None;
    }
    let x = (r * v - q * w) / det;
    let y = (p * w - r * u) / det;
    let h = a1 * x + b1 * y - c1;
    Some(([x, y], h, same))
}

fn seg_dist(p: P2, a: P2, b: P2) -> f64 {
    let d = vm::sub(b, a);
    let l2 = vm::dot(d, d);
    if l2 == 0.0 {
        return vm::dist(p, a);
    }
    let t = (vm::dot(vm::sub(p, a), d) / l2).clamp(0.0, 1.0);
    vm::dist(p, [a[0] + d[0] * t, a[1] + d[1] * t])
}

/// A roof by extrusion: its profile [along, up] swept across to its line's left.
fn extrusion_pieces(pr: &Project, e: &Value) -> Option<Vec<(Piece, f64)>> {
    let x = e.get("extrusion")?;
    let line = pts(x.get("line"));
    if line.len() != 2 {
        return None;
    }
    let profile = pts(x.get("profile"));
    if profile.len() < 2 {
        return None;
    }
    let from = f_of(x, "from").unwrap_or(0.0);
    let to = f_of(x, "to").unwrap_or(0.0);
    let base = base_z(pr, e) + f_of(e, "offset").unwrap_or(0.0);
    let th = lib_type(pr, e, &["roof"]).and_then(|t| f_of(t, "thickness")).unwrap_or(300.0);
    let u = vm::unit(vm::sub(line[1], line[0]));
    let n = vm::left_normal(line[0], line[1]);
    let at = |along: f64, across: f64| vm::add(vm::add(line[0], vm::mul(u, along)), vm::mul(n, across));
    let mut out = Vec::new();
    for w in profile.windows(2) {
        let (a, b) = (w[0], w[1]);
        if a[0] == b[0] {
            continue;
        }
        let (a, b) = if a[0] < b[0] { (a, b) } else { (b, a) };
        let g_along = (b[1] - a[1]) / (b[0] - a[0]);
        let slope = g_along.atan();
        let h = th / slope.cos();
        let outline = vec![at(a[0], from), at(b[0], from), at(b[0], to), at(a[0], to)];
        let o = at(a[0], from);
        let bottom = Height::Plane { o, z0: base + a[1], g: [u[0] * g_along, u[1] * g_along] };
        let top = Height::Plane { o, z0: base + a[1] + h, g: [u[0] * g_along, u[1] * g_along] };
        out.push((Piece { outline, holes: Vec::new(), bottom, top }, slope.to_degrees()));
    }
    Some(out)
}

// ---------------------------------------------------------------- columns, footings, runs

fn rect(at: P2, w: f64, d: f64, angle: f64) -> Vec<P2> {
    let a = angle.to_radians();
    let u = [a.cos(), a.sin()];
    let n = [-u[1], u[0]];
    [[-w / 2.0, -d / 2.0], [w / 2.0, -d / 2.0], [w / 2.0, d / 2.0], [-w / 2.0, d / 2.0]]
        .iter()
        .map(|q| [at[0] + u[0] * q[0] + n[0] * q[1], at[1] + u[1] * q[0] + n[1] * q[1]])
        .collect()
}

fn circle(c: P2, r: f64, n: usize) -> Vec<P2> {
    (0..n)
        .map(|i| {
            let t = (i as f64 / n as f64) * std::f64::consts::TAU;
            [c[0] + r * t.cos(), c[1] + r * t.sin()]
        })
        .collect()
}

fn post_piece(pr: &Project, e: &Value, key: &str) -> Option<Piece> {
    let at = pt_of(e, "at")?;
    let t = lib_type(pr, e, &[key]);
    let w = t.and_then(|t| f_of(t, "width")).unwrap_or(400.0);
    let d = t.and_then(|t| f_of(t, "depth")).unwrap_or(w);
    let round = t.and_then(|t| t.get("round")).and_then(|r| r.as_bool()).unwrap_or(false);
    let angle = f_of(e, "angle").unwrap_or(0.0);
    let (base, top) = base_top(pr, e);
    let outline = if round { circle(at, w / 2.0, ROUND_SIDES) } else { rect(at, w, d, angle) };
    Some(Piece::flat(outline, base, top))
}

/// A run: its plan outline, and its top and bottom over each point of it.
fn run_piece(pr: &Project, e: &Value) -> Option<Piece> {
    let c = cat(e);
    let key = match c {
        "cable" => "cable",
        x => x,
    };
    let t = lib_type(pr, e, &["runs", key]);
    let w = t.and_then(|t| f_of(t, "width")).unwrap_or(200.0);
    let d = t.and_then(|t| f_of(t, "depth")).unwrap_or(w);
    let round = t.and_then(|t| t.get("round")).and_then(|r| r.as_bool()).unwrap_or(false);
    let a = pt_of(e, "start")?;
    let b = pt_of(e, "end")?;
    let level = base_z(pr, e);
    let z0 = f_of(e, "offset").unwrap_or(0.0);
    let z1 = f_of(e, "end_offset").unwrap_or(z0);
    let justify = s_of(e, "justify").unwrap_or("centre");
    let len = vm::dist(a, b);
    // how far the line it is set out by lies below its top, and its section's depth, plumb
    let (above, depth) = if len > 0.0 {
        let g = (z1 - z0) / len;
        let dd = d * (1.0 + g * g).sqrt();
        let above = match justify {
            "top" => 0.0,
            "bottom" => dd,
            _ => dd / 2.0,
        };
        (above, dd)
    } else {
        let above = match justify {
            "top" => 0.0,
            "bottom" => d,
            _ => d / 2.0,
        };
        (above, d)
    };
    if len <= 0.0 {
        // standing upright: its section round its point, from one height to the other
        let outline = if round { circle(a, w / 2.0, ROUND_SIDES) } else { rect(a, w, w, 0.0) };
        let lo = level + z0.min(z1);
        let hi = level + z0.max(z1);
        return Some(Piece::flat(outline, lo, hi));
    }
    let u = vm::unit(vm::sub(b, a));
    let n = [-u[1], u[0]];
    let hw = w / 2.0;
    let outline = vec![vm::add(a, vm::mul(n, -hw)), vm::add(b, vm::mul(n, -hw)), vm::add(b, vm::mul(n, hw)), vm::add(a, vm::mul(n, hw))];
    let g = (z1 - z0) / len;
    if round {
        let r = w / 2.0;
        let k = (1.0 + g * g).sqrt();
        let zc = level
            + z0
            + match justify {
                "top" => -r * k,
                "bottom" => r * k,
                _ => 0.0,
            };
        let t = Tube { o: a, u, len, end: b, zc, g, r };
        return Some(Piece { outline, holes: Vec::new(), bottom: Height::Tube(t, false), top: Height::Tube(t, true) });
    }
    let top = Height::Plane { o: a, z0: level + z0 + above, g: [u[0] * g, u[1] * g] };
    let bottom = Height::Plane { o: a, z0: level + z0 + above - depth, g: [u[0] * g, u[1] * g] };
    Some(Piece { outline, holes: Vec::new(), bottom, top })
}

// ---------------------------------------------------------------- stairs and ramps

/// A flight: its plan rectangle, and its treads' heights.
#[derive(Clone, Debug)]
pub struct Flight {
    start: P2,
    dir: P2,
    width: f64,
    length: f64,
    /// height of each tread's top, from the first
    steps: Vec<f64>,
    tread: f64,
    /// a ramp: the height at its start, its rise per mm, the height at its end
    ramp: Option<(f64, f64, f64)>,
    /// the heights its pitch runs from and to (a landing's both its own)
    pitch: (f64, f64),
    /// a landing (its far side is not on it)
    landing: bool,
}

impl Flight {
    fn local(&self, p: P2) -> (f64, f64) {
        let v = vm::sub(p, self.start);
        (vm::dot(v, self.dir), vm::cross(self.dir, v))
    }
    fn outline(&self) -> Vec<P2> {
        let n = [-self.dir[1], self.dir[0]];
        let hw = self.width / 2.0;
        let a = self.start;
        let b = vm::add(a, vm::mul(self.dir, self.length));
        vec![vm::add(a, vm::mul(n, -hw)), vm::add(b, vm::mul(n, -hw)), vm::add(b, vm::mul(n, hw)), vm::add(a, vm::mul(n, hw))]
    }
    fn top_at(&self, p: P2) -> Option<f64> {
        let (along, across) = self.local(p);
        if let Some((z0, k, _)) = self.ramp {
            if !inside(&self.outline(), p) {
                return None;
            }
            return Some(z0 + along * k);
        }
        if self.landing {
            if !inside(&self.outline(), p) {
                return None;
            }
        } else if along < 0.0 || along > self.length || across.abs() > self.width / 2.0 {
            return None;
        }
        if self.steps.is_empty() {
            return None;
        }
        let i = ((along / self.tread).floor() as isize).clamp(0, self.steps.len() as isize - 1) as usize;
        Some(self.steps[i])
    }
    fn max_top(&self) -> f64 {
        match self.ramp {
            Some((_, _, z1)) => z1,
            None => self.steps.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
        }
    }
}

fn stair_flights(pr: &Project, e: &Value) -> Vec<Flight> {
    let ramp = cat(e) == "ramp";
    let Some(start) = pt_of(e, "start") else { return Vec::new() };
    let angle = f_of(e, "angle").unwrap_or(0.0).to_radians();
    let width = f_of(e, "width").unwrap_or(if ramp { 1200.0 } else { 1000.0 });
    let base = base_z(pr, e) + f_of(e, "base_offset").unwrap_or(0.0);
    let height = match level_z(pr, e, "top_level") {
        Some(t) => t - base_z(pr, e),
        None => f_of(e, "height").unwrap_or(3000.0),
    };
    let landings: Vec<(f64, f64)> = e
        .get("landings")
        .and_then(|l| l.as_arr())
        .map(|a| a.iter().map(|l| (f_of(l, "at").unwrap_or(0.0), f_of(l, "turn").unwrap_or(0.0))).collect())
        .unwrap_or_default();
    let mut dir = [angle.cos(), angle.sin()];
    let mut at = start;
    let mut out = Vec::new();
    if ramp {
        let k = f_of(e, "slope").unwrap_or(8.333333333333334) / 100.0;
        if k <= 0.0 {
            return out;
        }
        let mut z = 0.0;
        let mut stops: Vec<(f64, f64)> = landings.into_iter().filter(|(h, _)| *h > 0.0 && *h < height).collect();
        stops.push((height, 0.0));
        for (i, (h, turn)) in stops.iter().enumerate() {
            let rise = h - z;
            let length = rise / k;
            out.push(Flight {
                start: at,
                dir,
                width,
                length,
                steps: Vec::new(),
                tread: 0.0,
                ramp: Some((base + z, k, base + h)),
                pitch: (base + z, base + h),
                landing: false,
            });
            at = vm::add(at, vm::mul(dir, length));
            z = *h;
            if i + 1 < stops.len() {
                // a landing as long as the ramp is wide, then on as it turns
                out.push(Flight {
                    start: at,
                    dir,
                    width,
                    length: width,
                    steps: Vec::new(),
                    tread: 0.0,
                    ramp: Some((base + z, 0.0, base + z)),
                    pitch: (base + z, base + z),
                    landing: true,
                });
                let (nat, ndir) = turned(at, dir, width, *turn);
                at = nat;
                dir = ndir;
            }
        }
        return out;
    }
    let riser = f_of(e, "riser").unwrap_or(180.0);
    let tread = f_of(e, "tread").unwrap_or(280.0);
    if riser <= 0.0 || height <= 0.0 {
        return out;
    }
    let risers_f = (height / riser - 1e-9).ceil().max(1.0);
    if !risers_f.is_finite() || risers_f > 100_000.0 {
        return out;
    }
    let risers = risers_f as usize;
    let rh = height / risers as f64;
    let mut stops: Vec<(usize, f64)> =
        landings.iter().map(|(a, t)| (*a as usize, *t)).filter(|(a, _)| *a > 0 && *a < risers).collect();
    stops.sort_by_key(|s| s.0);
    stops.push((risers, 0.0));
    let mut done = 0usize;
    for (i, (upto, turn)) in stops.iter().enumerate() {
        let last = i + 1 == stops.len();
        // the treads of this flight: one for each riser climbed, but the one onto the landing or the floor above
        let n = upto - done - 1;
        let steps: Vec<f64> = (0..n).map(|k| base + (done + k + 1) as f64 * rh).collect();
        let length = n as f64 * tread;
        if n > 0 {
            let pitch = (base + done as f64 * rh, base + *upto as f64 * rh);
            out.push(Flight { start: at, dir, width, length, steps, tread, ramp: None, pitch, landing: false });
        }
        at = vm::add(at, vm::mul(dir, length));
        if !last {
            let z = base + *upto as f64 * rh;
            // a landing turning back takes both flights' widths, toward the side it turns to
            let (lat, lw) = if turn.abs() >= 180.0 {
                let side = if *turn > 0.0 { 1.0 } else { -1.0 };
                let n = [-dir[1] * side, dir[0] * side];
                (vm::add(at, vm::mul(n, width / 2.0)), width * 2.0)
            } else {
                (at, width)
            };
            out.push(Flight { start: lat, dir, width: lw, length: width, steps: vec![z], tread: width, ramp: None, pitch: (z, z), landing: true });
            let (nat, ndir) = turned(at, dir, width, *turn);
            at = nat;
            dir = ndir;
        }
        done = *upto;
    }
    out
}

/// Where the next flight starts off a landing (its near edge's middle at `at`), turned by `turn`.
fn turned(at: P2, dir: P2, width: f64, turn: f64) -> (P2, P2) {
    let centre = vm::add(at, vm::mul(dir, width / 2.0));
    if turn == 0.0 {
        return (vm::add(at, vm::mul(dir, width)), dir);
    }
    if turn.abs() >= 180.0 {
        // back beside it
        let side = if turn > 0.0 { 1.0 } else { -1.0 };
        let n = [-dir[1] * side, dir[0] * side];
        let back = vm::mul(dir, -1.0);
        let s = vm::add(vm::add(at, vm::mul(n, width)), vm::mul(back, 0.0));
        return (s, back);
    }
    let nd = rot(dir, turn.to_radians());
    (vm::add(centre, vm::mul(nd, width / 2.0)), nd)
}

// ---------------------------------------------------------------- railings, masses, rebar

fn railing_height(pr: &Project, e: &Value) -> f64 {
    lib_type(pr, e, &["railing"]).and_then(|t| f_of(t, "height")).unwrap_or(1000.0)
}

/// Half a rail's width, and half a baluster's, mm.
const RAIL: f64 = 25.0;
const BALUSTER: f64 = 10.0;

/// A railing along a path: its rail over each segment and its balusters every `spacing` from the
/// path's start, as high as its type.
fn railing_pieces(pr: &Project, e: &Value) -> Vec<Piece> {
    let h = railing_height(pr, e);
    let spacing = lib_type(pr, e, &["railing"]).and_then(|t| f_of(t, "spacing")).unwrap_or(120.0);
    let path = pts(e.get("path"));
    let mut out = Vec::new();
    if path.len() < 2 {
        return out;
    }
    let base = base_z(pr, e) + f_of(e, "base_offset").unwrap_or(0.0);
    let mut run = 0.0;
    let mut next = 0.0;
    for w in path.windows(2) {
        let len = vm::dist(w[0], w[1]);
        if len <= 0.0 {
            continue;
        }
        out.push(band(w[0], w[1], RAIL, 0.0, Height::Flat(base), Height::Flat(base + h)));
        let u = vm::unit(vm::sub(w[1], w[0]));
        while spacing > 0.0 && next < run + len && out.len() < 200_000 {
            let q = vm::add(w[0], vm::mul(u, next - run));
            out.push(Piece::flat(
                vec![[q[0] - BALUSTER, q[1] - BALUSTER], [q[0] + BALUSTER, q[1] - BALUSTER], [q[0] + BALUSTER, q[1] + BALUSTER], [q[0] - BALUSTER, q[1] + BALUSTER]],
                base,
                base + h,
            ));
            next += spacing;
        }
        run += len;
    }
    out
}

/// A railing along a stair's or a ramp's side: within it, its rail following each flight's pitch.
fn hosted_railing_pieces(pr: &Project, e: &Value) -> Vec<Piece> {
    let h = railing_height(pr, e);
    let mut out = Vec::new();
    let Some(host) = ref_id(pr, e, "host").and_then(|h| pr.el(h)) else { return out };
    let side = s_of(e, "side").unwrap_or("left");
    for f in stair_flights(pr, host) {
        let n = [-f.dir[1], f.dir[0]];
        let off = if side == "left" { f.width / 2.0 - RAIL } else { -(f.width / 2.0 - RAIL) };
        let a = vm::add(f.start, vm::mul(n, off));
        let b = vm::add(a, vm::mul(f.dir, f.length));
        let g = if f.length > 0.0 { (f.pitch.1 - f.pitch.0) / f.length } else { 0.0 };
        let top = Height::Plane { o: a, z0: f.pitch.0 + h, g: [f.dir[0] * g, f.dir[1] * g] };
        out.push(band(a, b, RAIL, 0.0, Height::Flat(f.pitch.0), top));
        // a baluster where it starts
        out.push(Piece::flat(
            vec![[a[0] - BALUSTER, a[1] - BALUSTER], [a[0] + BALUSTER, a[1] - BALUSTER], [a[0] + BALUSTER, a[1] + BALUSTER], [a[0] - BALUSTER, a[1] + BALUSTER]],
            f.pitch.0,
            f.pitch.0 + h,
        ));
    }
    out
}

/// A band `r` either side of a line, running on `ext` past its ends.
fn band(a: P2, b: P2, r: f64, ext: f64, bottom: Height, top: Height) -> Piece {
    let u = vm::unit(vm::sub(b, a));
    let n = [-u[1], u[0]];
    let a0 = vm::sub(a, vm::mul(u, ext));
    let b0 = vm::add(b, vm::mul(u, ext));
    Piece {
        outline: vec![vm::add(a0, vm::mul(n, -r)), vm::add(b0, vm::mul(n, -r)), vm::add(b0, vm::mul(n, r)), vm::add(a0, vm::mul(n, r))],
        holes: Vec::new(),
        bottom,
        top,
    }
}

fn mass_pieces(pr: &Project, e: &Value) -> Vec<Piece> {
    let outline = pts(e.get("boundary"));
    if outline.len() < 3 {
        return Vec::new();
    }
    let (base, top) = base_top(pr, e);
    let upper = pts(e.get("top"));
    let lean = pt_of(e, "lean");
    let upper = if upper.len() == outline.len() {
        upper
    } else if let Some(l) = lean {
        outline.iter().map(|q| vm::add(*q, l)).collect()
    } else {
        return vec![Piece::flat(outline, base, top)];
    };
    // lofted from its footprint to its top: the top's face and the sides between them
    let mut tris: Vec<[P3; 3]> = Vec::new();
    for t in ear_clip(&upper) {
        tris.push(t.map(|i| [upper[i][0], upper[i][1], top]));
    }
    let n = outline.len();
    for i in 0..n {
        let j = (i + 1) % n;
        let (b0, b1) = ([outline[i][0], outline[i][1], base], [outline[j][0], outline[j][1], base]);
        let (t0, t1) = ([upper[i][0], upper[i][1], top], [upper[j][0], upper[j][1], top]);
        tris.push([b0, b1, t1]);
        tris.push([b0, t1, t0]);
    }
    let surface = Height::Tris(tris);
    vec![
        Piece { outline: outline.clone(), holes: Vec::new(), bottom: Height::Flat(base), top: surface.clone() },
        Piece { outline: upper, holes: Vec::new(), bottom: Height::Flat(top), top: surface },
    ]
}

/// A simple polygon cut into triangles (by its ears), as indices of its corners.
fn ear_clip(poly: &[P2]) -> Vec<[usize; 3]> {
    let mut idx: Vec<usize> = (0..poly.len()).collect();
    if area2(poly) < 0.0 {
        idx.reverse();
    }
    let mut out = Vec::new();
    let mut guard = 0;
    while idx.len() > 3 && guard < 10_000 {
        guard += 1;
        let m = idx.len();
        let mut cut = false;
        for k in 0..m {
            let (a, b, c) = (idx[(k + m - 1) % m], idx[k], idx[(k + 1) % m]);
            let (pa, pb, pc) = (poly[a], poly[b], poly[c]);
            if vm::cross(vm::sub(pb, pa), vm::sub(pc, pb)) <= 0.0 {
                continue;
            }
            let tri = [pa, pb, pc];
            if idx.iter().any(|&q| q != a && q != b && q != c && inside(&tri, poly[q])) {
                continue;
            }
            out.push([a, b, c]);
            idx.remove(k);
            cut = true;
            break;
        }
        if !cut {
            break;
        }
    }
    if idx.len() == 3 {
        out.push([idx[0], idx[1], idx[2]]);
    }
    out
}

// ---------------------------------------------------------------- components

/// A family's parameters for a component: the family's values, its type's, the component's own.
fn component_params(pr: &Project, e: &Value) -> (Option<Value>, HashMap<String, f64>) {
    let mut vals = HashMap::new();
    let Some(fam_name) = lib_ref_name(pr, e, "family") else { return (None, vals) };
    let Some(fam) = pr.section("families").and_then(|f| f.get(&fam_name)).cloned() else { return (None, vals) };
    if let Some(ps) = fam.get("parameters").and_then(|p| p.as_arr()) {
        for p in ps {
            if let (Some(n), Some(v)) = (s_of(p, "name"), p.get("value").and_then(|v| v.as_f64())) {
                vals.insert(n.to_string(), v);
            }
        }
    }
    if let Some(tn) = lib_ref_name(pr, e, "type") {
        let prefix = format!("{}: ", fam_name);
        let tn = tn.strip_prefix(&prefix).map(|x| x.to_string()).unwrap_or(tn);
        if let Some(t) = fam.get("types").and_then(|t| t.get(&tn)).and_then(|t| t.as_obj()) {
            for (k, v) in t.iter() {
                if let Some(x) = v.as_f64() {
                    vals.insert(k.clone(), x);
                }
            }
        }
    }
    if let Some(own) = e.get("params").and_then(|p| p.as_obj()) {
        for (k, v) in own.iter() {
            if let Some(x) = v.as_f64() {
                vals.insert(k.clone(), x);
            }
        }
    }
    vals.entry("Wall Thickness".to_string()).or_insert(200.0);
    (Some(fam), vals)
}

fn component_pieces(pr: &Project, e: &Value) -> Vec<Piece> {
    let (Some(fam), vals) = component_params(pr, e) else { return Vec::new() };
    let Some(at) = pt_of(e, "at") else { return Vec::new() };
    let angle = f_of(e, "angle").unwrap_or(0.0).to_radians();
    let mirrored = e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false);
    let z0 = base_z(pr, e) + f_of(e, "offset").unwrap_or(0.0);
    let (su, cu) = angle.sin_cos();
    let place = |q: P2| {
        let q = if mirrored { [-q[0], q[1]] } else { q };
        [at[0] + cu * q[0] + (-su) * q[1], at[1] + su * q[0] + cu * q[1]]
    };
    let ev = |v: Option<&Value>| -> Option<f64> {
        match v? {
            Value::Num(n) => Some(n.as_f64()),
            Value::Str(s) => expr::eval(s, &vals),
            _ => None,
        }
    };
    let mut out = Vec::new();
    let Some(forms) = fam.get("forms").and_then(|f| f.as_arr()) else { return out };
    for f in forms {
        if f.get("void").and_then(|v| v.as_bool()) == Some(true) {
            continue;
        }
        if let Some(vis) = f.get("visible") {
            let shown = match vis {
                Value::Bool(b) => *b,
                Value::Str(s) => expr::eval(s, &vals).map(|x| x != 0.0).unwrap_or(true),
                _ => true,
            };
            if !shown {
                continue;
            }
        }
        let (Some(from), Some(to)) = (ev(f.get("from")), ev(f.get("to"))) else { continue };
        let (lo, hi) = (from.min(to), from.max(to));
        // the profile in its plane's coordinates
        let prof: Vec<P2> = if let Some(c) = f.get("circle") {
            let cc = c.get("centre").and_then(|x| x.as_arr());
            let cu = cc.and_then(|a| ev(a.first())).unwrap_or(0.0);
            let cv = cc.and_then(|a| ev(a.get(1))).unwrap_or(0.0);
            let Some(r) = ev(c.get("radius")) else { continue };
            circle([cu, cv], r, ROUND_SIDES)
        } else {
            let Some(a) = f.get("profile").and_then(|p| p.as_arr()) else { continue };
            let q: Vec<P2> = a
                .iter()
                .filter_map(|q| {
                    let q = q.as_arr()?;
                    Some([ev(q.first())?, ev(q.get(1))?])
                })
                .collect();
            if q.len() < 3 {
                continue;
            }
            q
        };
        match s_of(f, "plane").unwrap_or("xy") {
            "xz" => {
                // x along, z up, swept along y
                let (ulo, uhi) = span(prof.iter().map(|q| q[0]));
                let (vlo, vhi) = span(prof.iter().map(|q| q[1]));
                let outline = vec![place([ulo, lo]), place([uhi, lo]), place([uhi, hi]), place([ulo, hi])];
                out.push(Piece::flat(outline, z0 + vlo, z0 + vhi));
            }
            "yz" => {
                let (ulo, uhi) = span(prof.iter().map(|q| q[0]));
                let (vlo, vhi) = span(prof.iter().map(|q| q[1]));
                let outline = vec![place([lo, ulo]), place([hi, ulo]), place([hi, uhi]), place([lo, uhi])];
                out.push(Piece::flat(outline, z0 + vlo, z0 + vhi));
            }
            _ => {
                let outline: Vec<P2> = prof.iter().map(|q| place(*q)).collect();
                out.push(Piece::flat(outline, z0 + lo, z0 + hi));
            }
        }
    }
    out
}

fn span(it: impl Iterator<Item = f64>) -> (f64, f64) {
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    for x in it {
        lo = lo.min(x);
        hi = hi.max(x);
    }
    (lo, hi)
}

/// Arithmetic over a family's parameters: + - * /, parentheses, comparisons, min and max.
pub mod expr {
    use std::collections::HashMap;

    pub fn eval(s: &str, vals: &HashMap<String, f64>) -> Option<f64> {
        let toks = lex(s)?;
        let mut p = Parser { toks, i: 0, vals };
        let v = p.cmp()?;
        if p.i != p.toks.len() {
            return None;
        }
        Some(v)
    }

    #[derive(Clone, Debug, PartialEq)]
    enum Tok {
        Num(f64),
        Name(String),
        Op(String),
    }

    fn lex(s: &str) -> Option<Vec<Tok>> {
        let c: Vec<char> = s.chars().collect();
        let mut i = 0;
        let mut out = Vec::new();
        while i < c.len() {
            let ch = c[i];
            if ch.is_whitespace() {
                i += 1;
            } else if ch.is_ascii_digit() || ch == '.' {
                let st = i;
                while i < c.len() && (c[i].is_ascii_digit() || c[i] == '.') {
                    i += 1;
                }
                out.push(Tok::Num(c[st..i].iter().collect::<String>().parse().ok()?));
            } else if ch.is_alphabetic() || ch == '_' {
                // a name may hold spaces between its words
                let st = i;
                while i < c.len() && (c[i].is_alphanumeric() || c[i] == '_' || c[i] == ' ') {
                    i += 1;
                }
                let name: String = c[st..i].iter().collect::<String>().trim_end().to_string();
                out.push(Tok::Name(name));
            } else {
                let two: String = c[i..(i + 2).min(c.len())].iter().collect();
                if [">=", "<=", "==", "!="].contains(&two.as_str()) {
                    out.push(Tok::Op(two));
                    i += 2;
                } else {
                    out.push(Tok::Op(ch.to_string()));
                    i += 1;
                }
            }
        }
        Some(out)
    }

    struct Parser<'a> {
        toks: Vec<Tok>,
        i: usize,
        vals: &'a HashMap<String, f64>,
    }

    impl<'a> Parser<'a> {
        fn peek_op(&self) -> Option<&str> {
            match self.toks.get(self.i) {
                Some(Tok::Op(o)) => Some(o.as_str()),
                _ => None,
            }
        }
        fn cmp(&mut self) -> Option<f64> {
            let a = self.sum()?;
            if let Some(op) = self.peek_op().map(|s| s.to_string()) {
                if [">", "<", ">=", "<=", "==", "!="].contains(&op.as_str()) {
                    self.i += 1;
                    let b = self.sum()?;
                    let r = match op.as_str() {
                        ">" => a > b,
                        "<" => a < b,
                        ">=" => a >= b,
                        "<=" => a <= b,
                        "==" => a == b,
                        _ => a != b,
                    };
                    return Some(if r { 1.0 } else { 0.0 });
                }
            }
            Some(a)
        }
        fn sum(&mut self) -> Option<f64> {
            let mut a = self.prod()?;
            while let Some(op) = self.peek_op().map(|s| s.to_string()) {
                if op == "+" || op == "-" {
                    self.i += 1;
                    let b = self.prod()?;
                    a = if op == "+" { a + b } else { a - b };
                } else {
                    break;
                }
            }
            Some(a)
        }
        fn prod(&mut self) -> Option<f64> {
            let mut a = self.unary()?;
            while let Some(op) = self.peek_op().map(|s| s.to_string()) {
                if op == "*" || op == "/" {
                    self.i += 1;
                    let b = self.unary()?;
                    a = if op == "*" { a * b } else { a / b };
                } else {
                    break;
                }
            }
            Some(a)
        }
        fn unary(&mut self) -> Option<f64> {
            if self.peek_op() == Some("-") {
                self.i += 1;
                return Some(-self.unary()?);
            }
            if self.peek_op() == Some("+") {
                self.i += 1;
                return self.unary();
            }
            self.atom()
        }
        fn atom(&mut self) -> Option<f64> {
            let t = self.toks.get(self.i)?.clone();
            self.i += 1;
            match t {
                Tok::Num(x) => Some(x),
                Tok::Name(n) => {
                    if self.peek_op() == Some("(") {
                        self.i += 1;
                        let mut args = vec![self.cmp()?];
                        while self.peek_op() == Some(",") {
                            self.i += 1;
                            args.push(self.cmp()?);
                        }
                        if self.peek_op() != Some(")") {
                            return None;
                        }
                        self.i += 1;
                        return match n.to_lowercase().as_str() {
                            "min" => args.into_iter().reduce(f64::min),
                            "max" => args.into_iter().reduce(f64::max),
                            "abs" => args.first().map(|x| x.abs()),
                            _ => None,
                        };
                    }
                    self.vals.get(&n).cloned()
                }
                Tok::Op(o) if o == "(" => {
                    let v = self.cmp()?;
                    if self.peek_op() != Some(")") {
                        return None;
                    }
                    self.i += 1;
                    Some(v)
                }
                _ => None,
            }
        }
    }
}

// ---------------------------------------------------------------- the scene

/// What an element is in space, as far as the stand-in knows it.
pub enum Shape {
    Pieces(Vec<Piece>),
    Roof(RoofGeo),
    /// A stair's or a ramp's flights and landings, and the height it stands on.
    Flights(Vec<Flight>, f64),
    Wall(WallGeo),
    /// What the model builds but a spot does not read (a railing along a stair).
    Unread(Vec<Piece>),
}

/// The shape of one element (`walls`: every wall's footprint, worked out once).
pub fn shape(pr: &Project, id: u64, walls: &HashMap<u64, WallGeo>) -> Option<Shape> {
    let e = pr.el(id)?;
    let c = cat(e);
    Some(match c {
        "wall" => {
            let mut g = walls.get(&id)?.clone();
            g.attach_top = ref_id(pr, e, "attach_top").filter(|r| matches!(cat_of(pr, *r).as_str(), "roof" | "floor"));
            g.attach_base = ref_id(pr, e, "attach_base").filter(|r| matches!(cat_of(pr, *r).as_str(), "roof" | "floor"));
            Shape::Wall(g)
        }
        "floor" => Shape::Pieces(vec![floor_piece(pr, e)?]),
        "ceiling" => Shape::Pieces(vec![ceiling_piece(pr, e)?]),
        "roof" => {
            if e.get("extrusion").map_or(false, |x| !x.is_null()) {
                Shape::Pieces(extrusion_pieces(pr, e)?.into_iter().map(|(p, _)| p).collect())
            } else {
                Shape::Roof(roof_geo(pr, e)?)
            }
        }
        "column" => Shape::Pieces(vec![post_piece(pr, e, "column")?]),
        "structuralcolumn" => Shape::Pieces(vec![post_piece(pr, e, "structural_column")?]),
        "footing" => Shape::Pieces(vec![post_piece(pr, e, "footing")?]),
        "stair" | "ramp" => Shape::Flights(stair_flights(pr, e), base_z(pr, e) + f_of(e, "base_offset").unwrap_or(0.0)),
        "railing" => {
            if pts(e.get("path")).len() >= 2 {
                Shape::Pieces(railing_pieces(pr, e))
            } else {
                Shape::Unread(hosted_railing_pieces(pr, e))
            }
        }
        "mass" => Shape::Pieces(mass_pieces(pr, e)),
        "component" => Shape::Pieces(component_pieces(pr, e)),
        "rebar" => {
            let path = e.get("path").and_then(|p| p.as_arr()).cloned().unwrap_or_default();
            let r = f_of(e, "diameter").unwrap_or(10.0) / 2.0;
            let z = base_z(pr, e);
            let mut pcs = Vec::new();
            for q in path.iter().filter_map(super::p3) {
                pcs.push(Piece::flat(
                    vec![[q[0] - r, q[1] - r], [q[0] + r, q[1] - r], [q[0] + r, q[1] + r], [q[0] - r, q[1] + r]],
                    z + q[2] - r,
                    z + q[2] + r,
                ));
            }
            Shape::Pieces(pcs)
        }
        x if RUNS.contains(&x) => Shape::Pieces(vec![run_piece(pr, e)?]),
        _ => return None,
    })
}

/// The underside of a roof over a point (none off it).
fn roof_under_at(pr: &Project, roof: u64, p: P2) -> Option<f64> {
    let g = roof_geo(pr, pr.el(roof)?)?;
    if !in_region(&g.outline, &g.holes, p) {
        return None;
    }
    Some(g.heights(p).0)
}

/// The underside of a roof or a floor over a point (none off it).
fn under_at(pr: &Project, id: u64, p: P2) -> Option<f64> {
    match cat_of(pr, id).as_str() {
        "roof" => roof_under_at(pr, id, p),
        "floor" => {
            let pc = floor_piece(pr, pr.el(id)?)?;
            if !in_region(&pc.outline, &[], p) {
                return None;
            }
            Some(pc.bottom.at(p))
        }
        _ => None,
    }
}

/// The top of a floor or a roof over a point, its openings as if closed (none off it).
fn top_of_at(pr: &Project, id: u64, p: P2) -> Option<f64> {
    match cat_of(pr, id).as_str() {
        "roof" => {
            let g = roof_geo(pr, pr.el(id)?)?;
            in_region(&g.outline, &[], p).then(|| g.heights(p).1)
        }
        "floor" => {
            let pc = floor_piece(pr, pr.el(id)?)?;
            in_region(&pc.outline, &[], p).then(|| pc.top.at(p))
        }
        _ => None,
    }
}

impl Shape {
    fn top_at(&self, pr: &Project, p: P2) -> Option<f64> {
        match self {
            Shape::Pieces(ps) => {
                let mut best: Option<f64> = None;
                for pc in ps {
                    if pc.contains(p) {
                        let z = pc.top.at(p);
                        best = Some(best.map_or(z, |b: f64| b.max(z)));
                    }
                }
                best
            }
            Shape::Roof(g) => in_region(&g.outline, &g.holes, p).then(|| g.heights(p).1),
            Shape::Flights(fs, _) => {
                let mut best: Option<f64> = None;
                for f in fs {
                    if let Some(z) = f.top_at(p) {
                        best = Some(best.map_or(z, |b: f64| b.max(z)));
                    }
                }
                best
            }
            Shape::Wall(g) => {
                if !inside(&g.outline, p) {
                    return None;
                }
                Some(g.top_at(pr, p))
            }
            Shape::Unread(_) => None,
        }
    }
    fn add_to(&self, pr: &Project, b: &mut Bounds) {
        match self {
            Shape::Pieces(ps) | Shape::Unread(ps) => ps.iter().for_each(|pc| b.add_piece(pc)),
            Shape::Roof(g) => {
                let lo = g.min_under();
                let hi = g.max_top();
                for q in g.outline.iter() {
                    b.add([q[0], q[1], lo]);
                    b.add([q[0], q[1], hi]);
                }
            }
            Shape::Flights(fs, base) => {
                for f in fs {
                    let hi = f.max_top();
                    for q in f.outline() {
                        b.add([q[0], q[1], *base]);
                        b.add([q[0], q[1], hi]);
                    }
                }
            }
            Shape::Wall(g) => {
                for q in &g.outline {
                    let base = g.base_at(pr, *q);
                    let top = g.top_at(pr, *q);
                    b.add([q[0], q[1], base]);
                    b.add([q[0], q[1], top.max(base)]);
                }
            }
        }
    }
}

/// The box round everything the model builds (none for a model with nothing built).
pub fn model_box(pr: &Project) -> Option<(P3, P3)> {
    let walls = walls(pr);
    let mut b = Bounds::default();
    for id in pr.elements.keys() {
        if let Some(s) = shape(pr, *id, &walls) {
            s.add_to(pr, &mut b);
        }
    }
    c_cloud_bounds(pr, &mut b);
    b.any.then_some((b.lo, b.hi))
}

/// Point clouds placed in the project, by the box their element keeps (if any).
fn c_cloud_bounds(pr: &Project, b: &mut Bounds) -> bool {
    let mut any = false;
    for e in pr.elements.values() {
        if cat(e) != "pointcloud" {
            continue;
        }
        let Some(name) = lib_ref_name(pr, e, "cloud") else { continue };
        let Some(scan) = crate::cloud::clouds(pr).and_then(|m| m.get(&name)) else { continue };
        let Some(points) = crate::cloud::unpack_points(scan, usize::MAX / 2) else { continue };
        let at = pt_of(e, "at").unwrap_or([0.0, 0.0]);
        let z0 = base_z(pr, e) + f_of(e, "offset").unwrap_or(0.0);
        let a = f_of(e, "angle").unwrap_or(0.0).to_radians();
        let (sn, cs) = a.sin_cos();
        // the scan's own box, its corners placed
        let mut lo = [f64::INFINITY; 3];
        let mut hi = [f64::NEG_INFINITY; 3];
        for q in &points {
            for i in 0..3 {
                lo[i] = lo[i].min(q[i] as f64);
                hi[i] = hi[i].max(q[i] as f64);
            }
        }
        if points.is_empty() {
            continue;
        }
        for x in [lo[0], hi[0]] {
            for y in [lo[1], hi[1]] {
                for z in [lo[2], hi[2]] {
                    b.add([at[0] + x * cs - y * sn, at[1] + x * sn + y * cs, z0 + z]);
                }
            }
        }
        any = true;
    }
    any
}

/// The top of an element over a plan point (none where it isn't there).
pub fn top_at(pr: &Project, id: u64, p: P2) -> Option<f64> {
    let walls = if cat_of(pr, id) == "wall" { walls(pr) } else { HashMap::new() };
    shape(pr, id, &walls)?.top_at(pr, p)
}

/// `top_at` with every wall's footprint worked out once (`walls`).
pub fn top_at_in(pr: &Project, id: u64, p: P2, walls: &HashMap<u64, WallGeo>) -> Option<f64> {
    shape(pr, id, walls)?.top_at(pr, p)
}

/// How steeply a floor's or a roof's top falls at a point (rise over run) and the way down in
/// plan (none where it is level); none off it or for anything else.
pub fn slope_at(pr: &Project, id: u64, p: P2) -> Option<(f64, Option<P2>)> {
    let e = pr.el(id)?;
    match cat(e) {
        "floor" => {
            let pc = floor_piece(pr, e)?;
            if !pc.contains(p) {
                return None;
            }
            if let Height::Tris(ts) = &pc.top {
                // the way down is the way its face's upward normal leans
                let Some(t) = tri_under(ts, p) else { return Some((0.0, None)) };
                let (a, b, c) = (t[0], t[1], t[2]);
                let u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
                let v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
                let mut n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
                if n[2] < 0.0 {
                    n = [-n[0], -n[1], -n[2]];
                }
                let k = (n[0] * n[0] + n[1] * n[1]).sqrt();
                if k == 0.0 || n[2] == 0.0 {
                    return Some((0.0, None));
                }
                return Some((k / n[2], Some([n[0] / k, n[1] / k])));
            }
            let slope = f_of(e, "slope").unwrap_or(0.0);
            let arrow = pts(e.get("arrow"));
            if slope == 0.0 || arrow.len() != 2 || vm::dist(arrow[0], arrow[1]) <= 0.0 {
                return Some((0.0, None));
            }
            let d = vm::sub(arrow[1], arrow[0]);
            let l = vm::norm(d);
            let u = [d[0] / l, d[1] / l];
            let down = if slope > 0.0 { [-u[0], -u[1]] } else { u };
            Some((slope.to_radians().tan().abs(), Some(down)))
        }
        "roof" => {
            if e.get("extrusion").map_or(false, |x| !x.is_null()) {
                let pcs = extrusion_pieces(pr, e)?;
                for (pc, _) in pcs {
                    if pc.contains(p) {
                        let g = pc.top.gradient(p);
                        let k = vm::norm(g);
                        if k == 0.0 {
                            return Some((0.0, None));
                        }
                        return Some((k, Some([-g[0] / k, -g[1] / k])));
                    }
                }
                return None;
            }
            let g = roof_geo(pr, e)?;
            if !in_region(&g.outline, &g.holes, p) {
                return None;
            }
            Some(g.slope_at(p))
        }
        _ => None,
    }
}
