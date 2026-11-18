//! Roofs: by footprint (the straight skeleton of their outline and courtyards, gables, a
//! slope per edge), by extrusion, dormers and joins, written as closed faceted Breps; and the
//! walls attached to them.

use super::geom::*;
use super::step::{gid, refs, st};
use super::Ex;
use crate::json::Value;

fn ring_of(v: Option<&Value>) -> Vec<V2> {
    let mut out = Vec::new();
    if let Some(a) = v.and_then(|x| x.as_arr()) {
        for p in a {
            if let Some(q) = p.as_arr() {
                if q.len() >= 2 {
                    out.push(v2(q[0].as_f64().unwrap_or(0.0), q[1].as_f64().unwrap_or(0.0)));
                }
            }
        }
    }
    out
}

/// A piece of a roof: a ring in plan, the height of its underside at each corner and how
/// much higher its top is (plumb).
#[derive(Clone, Debug)]
pub struct Piece {
    pub ring: Vec<V2>,
    pub z: Vec<f64>,
    pub thick: f64,
    pub plane: Plane,
}

/// The plane of a piece's underside: the height over its level at a point in plan.
#[derive(Clone, Copy, Debug)]
pub enum Plane {
    /// Rising from an eave: `(dd - (nx x + ny y)) - lev`.
    Eave { nx: f64, ny: f64, dd: f64, lev: f64 },
    /// Level.
    Flat { z: f64 },
    /// Along a line from `a` in `d`: `z0 + ((p - a)·d - x0) * k`.
    Along { a: V2, d: V2, x0: f64, z0: f64, k: f64 },
    /// Any plane: `z0 + kx x + ky y`.
    General { z0: f64, kx: f64, ky: f64 },
}

impl Plane {
    pub fn z(&self, p: V2) -> f64 {
        match *self {
            Plane::Eave { nx, ny, dd, lev } => (dd - (nx * p.x + ny * p.y)) - lev,
            Plane::Flat { z } => z,
            Plane::Along { a, d, x0, z0, k } => z0 + ((p - a).dot(d) - x0) * k,
            Plane::General { z0, kx, ky } => z0 + kx * p.x + ky * p.y,
        }
    }
    /// The height over another reference, given the plane's level's elevation.
    pub fn z_over(&self, p: V2, own_lev: f64, reference: f64) -> f64 {
        match *self {
            Plane::Eave { nx, ny, dd, .. } => (dd - (nx * p.x + ny * p.y)) - reference,
            _ => self.z(p) + own_lev - reference,
        }
    }
}

/// A ring clipped to a convex ring (counter-clockwise), one edge of it after another.
pub fn clip_ring(ring: &[V2], clip: &[V2]) -> Vec<V2> {
    let mut out = ring.to_vec();
    let n = clip.len();
    for i in 0..n {
        if out.is_empty() {
            break;
        }
        let a = clip[i];
        let b = clip[(i + 1) % n];
        let d = b - a;
        let inside = |p: V2| d.cross(p - a) >= -1e-9;
        let input = std::mem::take(&mut out);
        let m = input.len();
        let mut s = input[m - 1];
        for &e in &input {
            let ein = inside(e);
            let sin = inside(s);
            if ein {
                if !sin {
                    if let Some(x) = line_cross(s, e - s, a, d) {
                        out.push(x);
                    }
                }
                out.push(e);
            } else if sin {
                if let Some(x) = line_cross(s, e - s, a, d) {
                    out.push(x);
                }
            }
            s = e;
        }
    }
    out
}

/// The part of a ring to the left of the line through `a` along `d` (or to its right),
/// points on the line kept, as Sutherland and Hodgman clip.
pub fn half_ring(ring: &[V2], a: V2, d: V2, keep_left: bool) -> Vec<V2> {
    let n = ring.len();
    let mut out = Vec::with_capacity(n + 2);
    if n == 0 {
        return out;
    }
    let sides: Vec<f64> = ring.iter().map(|p| d.x * (p.y - a.y) - d.y * (p.x - a.x)).collect();
    let inside = |v: f64| if keep_left { v >= 0.0 } else { v <= 0.0 };
    for i in 0..n {
        let si = (i + n - 1) % n;
        let (s, e) = (ring[si], ring[i]);
        let (ss, se) = (sides[si], sides[i]);
        let cut = || {
            let t = se / (se - ss);
            e + (s - e) * t
        };
        if inside(se) {
            if !inside(ss) {
                out.push(cut());
            }
            out.push(e);
        } else if inside(ss) {
            out.push(cut());
        }
    }
    out
}

/// The part of a ring where `f` is at least 0 (`keep_pos`) or at most 0, each corner kept
/// where it is in it and a point put where an edge from it crosses out or in (corners on the
/// line on both sides).
pub fn half_fwd(ring: &[V2], f: &dyn Fn(V2) -> f64, keep_pos: bool) -> Vec<V2> {
    let n = ring.len();
    let mut out = Vec::with_capacity(n + 2);
    let sides: Vec<f64> = ring.iter().map(|p| f(*p)).collect();
    let inside = |v: f64| if keep_pos { v >= 0.0 } else { v <= 0.0 };
    for i in 0..n {
        let j = (i + 1) % n;
        let (p, q) = (ring[i], ring[j]);
        let (sp, sq) = (sides[i], sides[j]);
        if inside(sp) {
            out.push(p);
        }
        if inside(sp) != inside(sq) {
            let t = sp / (sp - sq);
            out.push(p + (q - p) * t);
        }
    }
    out
}

/// As `cut_by_pieces`, splitting the forward way (`half_fwd`): how a roof that runs into
/// another is cut by its pieces.
pub fn cut_by_pieces_fwd(ring: &[V2], pieces: &[&[V2]]) -> Vec<(Option<usize>, Vec<V2>)> {
    let ok = |r: &Vec<V2>| r.len() >= 3 && signed_area(r).abs() > 1e-6;
    let mut parts = Vec::new();
    let mut left = vec![ring.to_vec()];
    for (i, piece) in pieces.iter().enumerate() {
        let mut next = Vec::new();
        for r in left {
            let mut rest = r;
            let m = piece.len();
            for k in 0..m {
                let a = piece[k];
                let d = piece[(k + 1) % m] - a;
                if d.x == 0.0 && d.y == 0.0 {
                    // a corner twice: no edge
                    continue;
                }
                let side = |p: V2| d.x * (p.y - a.y) - d.y * (p.x - a.x);
                let out = half_fwd(&rest, &side, false);
                let inn = half_fwd(&rest, &side, true);
                if ok(&out) {
                    next.push(out);
                }
                rest = inn;
                if !ok(&rest) {
                    break;
                }
            }
            if ok(&rest) {
                parts.push((Some(i), rest));
            }
        }
        left = next;
    }
    parts.extend(left.into_iter().map(|r| (None, r)));
    parts
}

/// The part of a ring where `f` is at most 0 (a linear function in plan), as Sutherland and
/// Hodgman clip.
pub fn half_ring_by(ring: &[V2], f: &dyn Fn(V2) -> f64) -> Vec<V2> {
    let n = ring.len();
    let mut out = Vec::with_capacity(n + 2);
    if n == 0 {
        return out;
    }
    let sides: Vec<f64> = ring.iter().map(|p| f(*p)).collect();
    let inside = |v: f64| v <= 0.0;
    for i in 0..n {
        let si = (i + n - 1) % n;
        let (s, e) = (ring[si], ring[i]);
        let (ss, se) = (sides[si], sides[i]);
        let cut = || {
            let t = se / (se - ss);
            e + (s - e) * t
        };
        if inside(se) {
            if !inside(ss) {
                out.push(cut());
            }
            out.push(e);
        } else if inside(ss) {
            out.push(cut());
        }
    }
    out
}

/// A ring cut by convex pieces one after another, each taking what is left inside it: the
/// parts, each with its piece's number. What lies outside each piece's edges goes on to the
/// pieces after it, and what no piece takes comes last, with none.
pub fn cut_by_pieces(ring: &[V2], pieces: &[&[V2]]) -> Vec<(Option<usize>, Vec<V2>)> {
    let ok = |r: &Vec<V2>| r.len() >= 3 && signed_area(r).abs() > 1e-6;
    let mut parts = Vec::new();
    let mut left = vec![ring.to_vec()];
    for (i, piece) in pieces.iter().enumerate() {
        let mut next = Vec::new();
        for r in left {
            let mut rest = r;
            let m = piece.len();
            for k in 0..m {
                let a = piece[k];
                let d = piece[(k + 1) % m] - a;
                if d.x == 0.0 && d.y == 0.0 {
                    // a corner twice: no edge
                    continue;
                }
                let out = half_ring(&rest, a, d, false);
                let inn = half_ring(&rest, a, d, true);
                if ok(&out) {
                    next.push(out);
                }
                rest = inn;
                if !ok(&rest) {
                    break;
                }
            }
            if ok(&rest) {
                parts.push((Some(i), rest));
            }
        }
        left = next;
    }
    parts.extend(left.into_iter().map(|r| (None, r)));
    parts
}

/// A face less the openings that reach it, as convex pieces (as a sloped floor is).
pub fn less_openings(ring: &[V2], openings: &[Vec<V2>]) -> Vec<Vec<V2>> {
    super::slabs::convex_pieces(ring, openings)
}

/// What a roof by footprint is made of.
pub struct RoofGeom {
    pub pieces: Vec<Piece>,
    pub predefined: &'static str,
}

impl<'a> Ex<'a> {
    /// The roof type's thickness.
    fn roof_thickness(&self, e: &Value) -> f64 {
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
        super::walls::type_data(self.pr, "roof", tg).and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(300.0)
    }

    /// A roof by footprint: its faces, each a piece over its ring.
    /// A roof's pieces; one that runs into another (a dormer's) ends where its top meets that
    /// one's: its pieces cut by the other's one after another, each part over one of them
    /// cut back to where the two tops meet, the parts over none of them (over its opening)
    /// kept whole.
    pub fn roof_geom(&self, e: &Value) -> RoofGeom {
        let mut g = self.roof_geom_own(e);
        let pr = self.pr;
        let Some(hid) = e.get("join").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).and_then(|h| pr.find_guid(h)) else {
            return g;
        };
        let Some(he) = pr.el(hid) else { return g };
        let host = self.roof_geom_own(he);
        let lev = self.level_elev(e.get("level").and_then(|v| v.as_str()).unwrap_or(""));
        let hlev = self.level_elev(he.get("level").and_then(|v| v.as_str()).unwrap_or(""));
        let rings: Vec<&[V2]> = host.pieces.iter().map(|p| p.ring.as_slice()).collect();
        let ok = |r: &Vec<V2>| r.len() >= 3 && signed_area(r).abs() > 1e-6;
        let mut out = Vec::new();
        for p in std::mem::take(&mut g.pieces) {
            for (hi, part) in cut_by_pieces_fwd(&p.ring, &rings) {
                let part = match hi {
                    Some(i) => {
                        let h = &host.pieces[i];
                        let f = |q: V2| (h.plane.z_over(q, hlev, 0.0) + h.thick) - (p.plane.z_over(q, lev, 0.0) + p.thick);
                        let c = half_fwd(&part, &f, false);
                        if !ok(&c) {
                            continue;
                        }
                        c
                    }
                    None => part,
                };
                let z: Vec<f64> = part.iter().map(|q| p.plane.z(*q)).collect();
                out.push(Piece { ring: part, z, thick: p.thick, plane: p.plane });
            }
        }
        g.pieces = out;
        g
    }

    fn roof_geom_own(&self, e: &Value) -> RoofGeom {
        let thick = self.roof_thickness(e);
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let lev = self.level_elev(level);
        let offset = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let slope = e.get("slope").and_then(|v| v.as_f64()).unwrap_or(30.0);
        let overhang = e.get("overhang").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let mut outline = ring_of(e.get("boundary"));
        let mut courtyards: Vec<Vec<V2>> = Vec::new();
        if let Some(cs) = e.get("courtyards").and_then(|c| c.as_arr()) {
            for c in cs {
                let r = ring_of(Some(c));
                if r.len() >= 3 {
                    courtyards.push(r);
                }
            }
        }
        // the outline counter-clockwise and the courtyards clockwise, each edge keeping the
        // number it has as drawn (edge i from point i to the next)
        let mut given_of: Vec<usize> = Vec::new();
        let n0 = outline.len();
        if signed_area(&outline) < 0.0 {
            outline.reverse();
            given_of.extend((0..n0).map(|k| (2 * n0 - 2 - k) % n0));
        } else {
            given_of.extend(0..n0);
        }
        let mut base_k = n0;
        for c in courtyards.iter_mut() {
            let n = c.len();
            if signed_area(c) > 0.0 {
                c.reverse();
                given_of.extend((0..n).map(|k| base_k + (2 * n - 2 - k) % n));
            } else {
                given_of.extend((0..n).map(|k| base_k + k));
            }
            base_k += n;
        }
        if let Some(x) = e.get("extrusion") {
            // a profile drawn along a line, swept across to its left
            let line = ring_of(x.get("line"));
            let prof = ring_of(x.get("profile"));
            let from = x.get("from").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let to = x.get("to").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let mut pieces = Vec::new();
            let openings = super::slabs::rings_of(e.get("openings"));
            if line.len() >= 2 && prof.len() >= 2 {
                let a = line[0];
                let d = (line[1] - line[0]).normalize();
                let n = d.perp();
                for k in 0..prof.len() - 1 {
                    let (p0, p1) = (prof[k], prof[k + 1]);
                    let ring = vec![a + d * p0.x + n * from, a + d * p1.x + n * from, a + d * p1.x + n * to, a + d * p0.x + n * to];
                    let seg = p1 - p0;
                    let cos = (seg.x.abs() / seg.length()).max(1e-9);
                    let k = if seg.x.abs() > 1e-12 { seg.y / seg.x } else { 0.0 };
                    let plane = Plane::Along { a, d, x0: p0.x, z0: offset + p0.y, k };
                    if openings.is_empty() {
                        let z = vec![offset + p0.y, offset + p1.y, offset + p1.y, offset + p0.y];
                        pieces.push(Piece { ring, z, thick: thick / cos, plane });
                    } else {
                        for part in less_openings(&ring, &openings) {
                            let z: Vec<f64> = part.iter().map(|p| plane.z(*p)).collect();
                            pieces.push(Piece { ring: part, z, thick: thick / cos, plane });
                        }
                    }
                }
            }
            let predefined = match prof.len() {
                2 => "SHED_ROOF",
                3 => "GABLE_ROOF",
                _ => "FREEFORM",
            };
            return RoofGeom { pieces, predefined };
        }
        let n_out = outline.len();
        let n_all = n_out + courtyards.iter().map(|c| c.len()).sum::<usize>();
        if slope.abs() < 1e-9 {
            // flat: in convex pieces round its courtyards and openings, if it has any
            let mut holes = courtyards.clone();
            holes.extend(super::slabs::rings_of(e.get("openings")));
            let pieces = super::slabs::convex_pieces(&outline, &holes)
                .into_iter()
                .map(|ring| Piece { z: vec![offset; ring.len()], ring, thick, plane: Plane::Flat { z: offset } })
                .collect();
            return RoofGeom { pieces, predefined: "FLAT_ROOF" };
        }
        // each edge's slope, and its gables
        let mut gables: Vec<usize> = e
            .get("gables")
            .and_then(|g| g.as_arr())
            .map(|a| a.iter().filter_map(|x| x.as_u64().map(|u| u as usize)).collect())
            .unwrap_or_default();
        if e.get("gable").and_then(|g| g.as_bool()).unwrap_or(false) && n_out == 4 {
            let l0 = outline[0].distance(outline[1]);
            let l1 = outline[1].distance(outline[2]);
            if l1 <= l0 {
                gables.extend([1, 3]);
            } else {
                gables.extend([0, 2]);
            }
        }
        // in the skeleton's numbering
        let gables: Vec<usize> = (0..n_all).filter(|k| gables.contains(&given_of[*k])).collect();
        let slopes: Vec<f64> = (0..n_all)
            .map(|i| {
                let s = e
                    .get("slopes")
                    .and_then(|a| a.as_arr())
                    .and_then(|a| a.get(given_of[i]))
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0);
                if s == 0.0 {
                    slope
                } else {
                    s
                }
            })
            .collect();
        let tans: Vec<f64> = slopes.iter().map(|s| s.to_radians().tan()).collect();
        let tan_min = tans
            .iter()
            .enumerate()
            .filter(|(i, _)| !gables.contains(i))
            .map(|(_, t)| *t)
            .fold(f64::INFINITY, f64::min);
        let tan_min = if tan_min.is_finite() { tan_min } else { slope.to_radians().tan() };
        let speeds: Vec<f64> = (0..n_all).map(|i| if gables.contains(&i) { 0.0 } else { tan_min / tans[i] }).collect();
        let mut rings = vec![outline.clone()];
        rings.extend(courtyards.iter().cloned());
        let faces = super::skeleton::faces(&rings, &speeds);
        // the eaves stay level, the base `overhang` in from them lowered by the slope
        let base = offset - overhang * slope.to_radians().tan();
        let openings = super::slabs::rings_of(e.get("openings"));
        let mut pieces = Vec::new();
        for (i, f) in faces.iter().enumerate() {
            let Some(f) = f else { continue };
            let ring: Vec<V2> = f.iter().map(|n| n.p).collect();
            // each corner on the plane of the face, in the building's heights: rising from its
            // eave at its slope
            let a = ring[0];
            let d = (ring[1] - ring[0]).normalize();
            let nrm = d.perp();
            let (nx, ny) = (-nrm.x * tans[i], -nrm.y * tans[i]);
            let dd = nx * a.x + ny * a.y + (lev + base);
            let cos = slopes[i].to_radians().cos();
            let plane = Plane::Eave { nx, ny, dd, lev };
            for part in less_openings(&ring, &openings) {
                let z: Vec<f64> = part.iter().map(|p| plane.z(*p)).collect();
                pieces.push(Piece { ring: part, z, thick: thick / cos, plane });
            }
        }
        let predefined = if gables.is_empty() { "HIP_ROOF" } else { "GABLE_ROOF" };
        RoofGeom { pieces, predefined }
    }

    pub fn write_roof(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let geom = self.roof_geom(e);
        let mut breps = Vec::new();
        let shaped = self.shaped_roof(e);
        if let Some((s, top, bottom)) = &shaped {
            breps.push(self.shaped_brep(s, top, bottom));
        }
        for p in geom.pieces.iter().filter(|_| shaped.is_none()) {
            let zb = p.z.clone();
            let ring = p.ring.clone();
            let th = p.thick;
            let b: Vec<usize> = ring.iter().zip(zb.iter()).map(|(q, z)| self.st.point3(q.x, q.y, *z)).collect();
            let t: Vec<usize> = ring.iter().zip(zb.iter()).map(|(q, z)| self.st.point3(q.x, q.y, *z + th)).collect();
            breps.push(self.shell_between(&b, &t));
        }
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',({}))", self.body, refs(&breps)));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let name = st(&tname);
        let product = self.add(format!(
            "IFCROOF('{}',$,{},$,{},#{},#{},'{}',.{}.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            name,
            name,
            place,
            shape,
            id,
            geom.predefined
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, Some("Pset_RoofCommon"), false);
        self.contain(&level, product);
        let flat = geom.predefined == "FLAT_ROOF";
        let tail = if flat { "$,$,$,$,$,$,.FLAT_ROOF." } else { "$,$,$,$,$,$,.NOTDEFINED." };
        self.typed("IFCROOFTYPE", &tname, tail, product);
        if let Some(layers) = super::walls::type_data(pr, "roof", &tg).and_then(|t| t.get("layers")).and_then(|l| l.as_arr()).cloned() {
            if !layers.is_empty() {
                self.layer_usages.push(super::LayerUse {
                    kind: super::LayerKind::Roof,
                    type_key: format!("roof:{}", tg),
                    type_name: tname.clone(),
                    layers,
                    offset: 0.0,
                    product,
                });
            }
        }
        self.cuttable.push((id, product, place, 0.0));
    }

    /// A flat roof with a shape: its surface, and the heights of its top and its underside at
    /// each corner (the underside the top less its thickness, or level at its offset when a
    /// layer of its type is variable).
    pub fn shaped_roof(&self, e: &Value) -> Option<(super::shaped::Shaped, Vec<f64>, Vec<f64>)> {
        let slope = e.get("slope").and_then(|v| v.as_f64()).unwrap_or(30.0);
        if slope.abs() >= 1e-9 || e.get("extrusion").is_some() || !super::shaped::has_shape(e) {
            return None;
        }
        let thick = self.roof_thickness(e);
        let offset = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let variable = self.variable_type("roof", tg);
        let outline = ring_of(e.get("boundary"));
        let mut holes = super::slabs::rings_of(e.get("courtyards"));
        holes.extend(super::slabs::rings_of(e.get("openings")));
        let (points, lines) = super::shaped::shape_of(e);
        let s = super::shaped::build(&outline, &holes, &points, &lines);
        let bottom: Vec<f64> = s.z.iter().map(|z| if variable { offset } else { offset + z }).collect();
        let top: Vec<f64> = s.z.iter().map(|z| offset + thick + z).collect();
        Some((s, top, bottom))
    }

    /// A closed faceted Brep between two rings of points written already: the bottom (turned
    /// down), the top, and a side for each edge.
    pub fn shell_between(&mut self, b: &[usize], t: &[usize]) -> usize {
        let n = b.len();
        let mut faces = Vec::new();
        let rb: Vec<usize> = b.iter().rev().cloned().collect();
        faces.push(self.face(&rb));
        faces.push(self.face(t));
        for i in 0..n {
            let j = (i + 1) % n;
            faces.push(self.face(&[b[i], b[j], t[j], t[i]]));
        }
        let shell = self.add(format!("IFCCLOSEDSHELL(({}))", refs(&faces)));
        self.add(format!("IFCFACETEDBREP(#{})", shell))
    }
}

/// A surface a wall's top or base follows: over a ring in plan, a height (from the building's
/// datum, less a reference).
pub struct Follow {
    pub ring: Vec<V2>,
    pub plane: Plane,
    pub lev: f64,
    /// Added to the plane's height (a roof's or a floor's thickness, up or down).
    pub add: f64,
}

impl<'a> Ex<'a> {
    /// The surfaces of an element a wall is attached to: a roof's underside (or top) piece by
    /// piece, a floor's top (or underside).
    pub fn follow_of(&self, g: &str, underside: bool) -> Vec<Follow> {
        let pr = self.pr;
        let Some(id) = pr.find_guid(g) else { return Vec::new() };
        let Some(e) = pr.el(id) else { return Vec::new() };
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let lev = self.level_elev(level);
        match e.get("category").and_then(|c| c.as_str()) {
            Some("roof") if self.shaped_roof(e).is_some() => {
                let (s, top, bottom) = self.shaped_roof(e).unwrap();
                let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if underside && self.variable_type("roof", tg) {
                    let mut ring = ring_of(e.get("boundary"));
                    if signed_area(&ring) < 0.0 {
                        ring.reverse();
                    }
                    let off = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    return vec![Follow { ring, plane: Plane::Flat { z: off }, lev, add: 0.0 }];
                }
                let z = if underside { bottom } else { top };
                s.face_planes(&z)
                    .into_iter()
                    .map(|(ring, [z0, kx, ky])| Follow { ring, plane: Plane::General { z0, kx, ky }, lev, add: 0.0 })
                    .collect()
            }
            Some("roof") => {
                let g = self.roof_geom(e);
                g.pieces
                    .into_iter()
                    .map(|p| {
                        let mut ring = p.ring;
                        if signed_area(&ring) < 0.0 {
                            ring.reverse();
                        }
                        Follow { ring, plane: p.plane, lev, add: if underside { 0.0 } else { p.thick } }
                    })
                    .collect()
            }
            Some("floor") => {
                let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
                let t = super::walls::type_data(pr, "floor", tg).and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(200.0);
                let off = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let mut ring = ring_of(e.get("boundary"));
                if signed_area(&ring) < 0.0 {
                    ring.reverse();
                }
                let shaped = super::slabs::slope_of(e, off).is_none() && super::shaped::has_shape(e);
                if shaped && !(underside && self.variable_type("floor", tg)) {
                    let (points, lines) = super::shaped::shape_of(e);
                    let holes = super::slabs::rings_of(e.get("openings"));
                    let s = super::shaped::build(&ring, &holes, &points, &lines);
                    let z: Vec<f64> = s.z.iter().map(|z| off + z).collect();
                    return s
                        .face_planes(&z)
                        .into_iter()
                        .map(|(ring, [z0, kx, ky])| Follow {
                            ring,
                            plane: Plane::General { z0, kx, ky },
                            lev,
                            add: if underside { -t } else { 0.0 },
                        })
                        .collect();
                }
                match super::slabs::slope_of(e, off) {
                    Some(sl) => {
                        let tv = t / sl.cos;
                        let plane = Plane::Along { a: sl.tail, d: sl.dir, x0: 0.0, z0: off, k: sl.tan };
                        vec![Follow { ring, plane, lev, add: if underside { -tv } else { 0.0 } }]
                    }
                    None => vec![Follow { ring, plane: Plane::Flat { z: off }, lev, add: if underside { -t } else { 0.0 } }],
                }
            }
            _ => Vec::new(),
        }
    }

    /// A wall attached to a roof or a floor: its outline (turned counter-clockwise) cut to each
    /// piece of what its top follows, each part a closed shell between its base and that piece.
    /// Points are in the wall's axes (`local`), heights over `reference`.
    pub fn attached_breps(&mut self, e: &Value, outline: &[V2], local: &dyn Fn(V2) -> V2, reference: f64, base_abs: f64, top_abs: f64) -> Option<Vec<usize>> {
        let top_g = e.get("attach_top").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).map(|s| s.to_string());
        let base_g = e.get("attach_base").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).map(|s| s.to_string());
        if top_g.is_none() && base_g.is_none() {
            return None;
        }
        let mut ring = outline.to_vec();
        ring.reverse();
        let tops = top_g.map(|g| self.follow_of(&g, true));
        let bases = base_g.map(|g| self.follow_of(&g, false));
        // the parts, each with what its top and its base follow
        // cut by what its base stands on first, then each part by what its top follows
        let mut lower: Vec<(Vec<V2>, Option<usize>)> = Vec::new();
        match &bases {
            Some(bs) => {
                let rings: Vec<&[V2]> = bs.iter().map(|f| f.ring.as_slice()).collect();
                for (j, c) in cut_by_pieces(&ring, &rings) {
                    lower.push((c, j));
                }
            }
            None => lower.push((ring.clone(), None)),
        }
        let mut parts: Vec<(Vec<V2>, Option<usize>, Option<usize>)> = Vec::new();
        for (r, b) in lower {
            match &tops {
                Some(ts) => {
                    let rings: Vec<&[V2]> = ts.iter().map(|f| f.ring.as_slice()).collect();
                    for (i, c) in cut_by_pieces(&r, &rings) {
                        parts.push((c, i, b));
                    }
                }
                None => parts.push((r, None, b)),
            }
        }
        let mut breps = Vec::new();
        for (r, t, b) in parts {
            let base_at = |p: V2| match (&bases, b) {
                (Some(bs), Some(j)) => (bs[j].plane.z_over(p, bs[j].lev, 0.0) + bs[j].add) - reference,
                _ => base_abs - reference,
            };
            let top_at = |p: V2| match (&tops, t) {
                (Some(ts), Some(i)) => (ts[i].plane.z_over(p, ts[i].lev, 0.0) + ts[i].add) - reference,
                _ => top_abs - reference,
            };
            // none of it where its top comes down to its base
            let r = if t.is_some() && b.is_some() {
                let c = half_ring_by(&r, &|p: V2| base_at(p) - top_at(p));
                if c.len() < 3 || signed_area(&c).abs() <= 1e-6 {
                    continue;
                }
                c
            } else {
                r
            };
            let zb: Vec<f64> = r.iter().map(|p| base_at(*p)).collect();
            let zt: Vec<f64> = r.iter().map(|p| top_at(*p)).collect();
            let lp: Vec<V2> = r.iter().map(|p| local(*p)).collect();
            let bi: Vec<usize> = lp.iter().zip(zb.iter()).map(|(q, z)| self.st.point3(q.x, q.y, *z)).collect();
            let ti: Vec<usize> = lp.iter().zip(zt.iter()).map(|(q, z)| self.st.point3(q.x, q.y, *z)).collect();
            breps.push(self.shell_between(&bi, &ti));
        }
        Some(breps)
    }

    /// The heights a roof spans and its footprint, for what cuts it (shafts).
    pub fn roof_extent(&self, id: u64, e: &Value) -> Option<(f64, f64, Vec<V2>)> {
        let _ = id;
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let lev = self.level_elev(level);
        let g = self.roof_geom(e);
        let mut lo = f64::INFINITY;
        let mut hi = f64::NEG_INFINITY;
        for p in &g.pieces {
            for z in &p.z {
                lo = lo.min(*z);
                hi = hi.max(*z + p.thick);
            }
        }
        if !lo.is_finite() {
            return None;
        }
        Some((lev + lo, lev + hi, ring_of(e.get("boundary"))))
    }
}
