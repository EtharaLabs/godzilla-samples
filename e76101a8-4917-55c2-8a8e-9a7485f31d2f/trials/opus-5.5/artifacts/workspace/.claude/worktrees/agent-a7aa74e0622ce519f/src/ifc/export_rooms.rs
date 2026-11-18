//! Rooms as IFC spaces: the boundary the walls and separation lines around their point give
//! them (at the centre lines and at the faces), swept up their height, with their quantities.

use super::geom::*;
use super::step::{gid, real, refs, st};
use super::Ex;
use crate::json::Value;

/// A line that bounds rooms, with what it comes from (for the order the boundary starts in).
#[derive(Clone, Debug)]
pub struct Bound {
    pub a: V2,
    pub b: V2,
    pub key: (u64, usize),
}

const EPS: f64 = 1e-6;

/// The pieces of the lines, split where they meet one another: (a, b, key, piece index).
fn split(lines: &[Bound]) -> Vec<(V2, V2, (u64, usize), usize)> {
    let mut out = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        let d = l.b - l.a;
        let len2 = d.length_squared();
        if len2 < EPS * EPS {
            continue;
        }
        let mut ts: Vec<f64> = vec![0.0, 1.0];
        for (j, m) in lines.iter().enumerate() {
            if i == j {
                continue;
            }
            let e = m.b - m.a;
            let den = d.cross(e);
            if den.abs() > 1e-12 {
                let t = (m.a - l.a).cross(e) / den;
                let s = (m.a - l.a).cross(d) / den;
                if t > -1e-9 && t < 1.0 + 1e-9 && s > -1e-9 && s < 1.0 + 1e-9 {
                    ts.push(t.clamp(0.0, 1.0));
                }
            } else {
                // along it: its ends that lie on this one
                for p in [m.a, m.b] {
                    let v = p - l.a;
                    if v.cross(d).abs() / len2.sqrt() < 1e-6 {
                        let t = v.dot(d) / len2;
                        if t > 0.0 && t < 1.0 {
                            ts.push(t);
                        }
                    }
                }
            }
        }
        ts.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let mut pts: Vec<V2> = Vec::new();
        for t in ts {
            let p = if t == 0.0 {
                l.a
            } else if t == 1.0 {
                l.b
            } else {
                l.a + d * t
            };
            if pts.last().map(|q: &V2| q.distance(p) < 1e-6).unwrap_or(false) {
                continue;
            }
            pts.push(p);
        }
        for k in 0..pts.len().saturating_sub(1) {
            out.push((pts[k], pts[k + 1], l.key, k));
        }
    }
    out
}

/// The vertices of an arrangement, welded.
fn weld(pts: &mut Vec<V2>, p: V2) -> usize {
    for (i, q) in pts.iter().enumerate() {
        if q.distance(p) < 1e-6 {
            return i;
        }
    }
    pts.push(p);
    pts.len() - 1
}

/// The ring of the smallest face of the lines' arrangement that holds the point,
/// counter-clockwise, starting at the piece of the first line (by key) along it.
pub fn face_at(lines: &[Bound], p: V2) -> Option<Vec<V2>> {
    face_with_islands(lines, p).map(|(r, _)| r)
}

/// As `face_at`, with the islands standing free inside it (lines joined to none of its own):
/// each the outline round it, from the piece of its first line, turned counter-clockwise.
pub fn face_with_islands(lines: &[Bound], p: V2) -> Option<(Vec<V2>, Vec<Vec<V2>>)> {
    let pieces = split(lines);
    let mut verts: Vec<V2> = Vec::new();
    // half-edges: (from, to, key, piece)
    let mut hes: Vec<(usize, usize, (u64, usize), usize)> = Vec::new();
    for (a, b, key, k) in &pieces {
        let ia = weld(&mut verts, *a);
        let ib = weld(&mut verts, *b);
        if ia == ib {
            continue;
        }
        if hes.iter().any(|h| (h.0 == ia && h.1 == ib) || (h.0 == ib && h.1 == ia)) {
            continue;
        }
        hes.push((ia, ib, *key, *k));
        hes.push((ib, ia, *key, *k));
    }
    let n = hes.len();
    // around each vertex, its outgoing half-edges by angle
    let mut out_of: Vec<Vec<usize>> = vec![Vec::new(); verts.len()];
    for (i, h) in hes.iter().enumerate() {
        out_of[h.0].push(i);
    }
    let ang = |i: usize| {
        let h = hes[i];
        let d = verts[h.1] - verts[h.0];
        d.y.atan2(d.x)
    };
    for v in out_of.iter_mut() {
        v.sort_by(|a, b| ang(*a).partial_cmp(&ang(*b)).unwrap_or(std::cmp::Ordering::Equal));
    }
    let twin = |i: usize| i ^ 1;
    let next = |i: usize| -> usize {
        let t = twin(i);
        let v = hes[i].1;
        let list = &out_of[v];
        let k = list.iter().position(|x| *x == t).unwrap();
        list[(k + list.len() - 1) % list.len()]
    };
    let mut seen = vec![false; n];
    let mut best: Option<(f64, Vec<usize>)> = None;
    let mut outers: Vec<Vec<usize>> = Vec::new();
    for s in 0..n {
        if seen[s] {
            continue;
        }
        let mut cyc = Vec::new();
        let mut e = s;
        loop {
            seen[e] = true;
            cyc.push(e);
            e = next(e);
            if e == s || cyc.len() > n {
                break;
            }
        }
        let ring: Vec<V2> = cyc.iter().map(|e| verts[hes[*e].0]).collect();
        let a = signed_area(&ring);
        if a < -1e-6 {
            outers.push(cyc);
            continue;
        }
        if a <= 1e-6 {
            continue;
        }
        if !point_in(p, &ring) {
            continue;
        }
        if best.as_ref().map(|b| a < b.0).unwrap_or(true) {
            best = Some((a, cyc));
        }
    }
    let (_, cyc) = best?;
    // the lines' groups, joined where they meet
    let mut group: Vec<usize> = (0..verts.len()).collect();
    fn root(g: &mut Vec<usize>, mut i: usize) -> usize {
        while g[i] != i {
            g[i] = g[g[i]];
            i = g[i];
        }
        i
    }
    for h in &hes {
        let (ra, rb) = (root(&mut group, h.0), root(&mut group, h.1));
        if ra != rb {
            group[ra] = rb;
        }
    }
    // start at the piece of the first line along it
    let first = |c: &Vec<usize>| (0..c.len()).min_by_key(|i| (hes[c[*i]].2, hes[c[*i]].3)).unwrap();
    let walk = |c: &Vec<usize>, k: usize| -> Vec<V2> { (0..c.len()).map(|i| verts[hes[c[(k + i) % c.len()]].0]).collect() };
    let k = first(&cyc);
    let ring = walk(&cyc, k);
    let own = root(&mut group, hes[cyc[0]].0);
    let mut islands = Vec::new();
    for o in &outers {
        let g = root(&mut group, hes[o[0]].0);
        if g == own {
            continue;
        }
        let pts: Vec<V2> = o.iter().map(|e| verts[hes[*e].0]).collect();
        if !pts.iter().all(|q| point_in(*q, &ring)) || point_in(p, &pts) {
            continue;
        }
        let mut r = walk(o, first(o));
        r.reverse();
        islands.push(r);
    }
    Some((ring, islands))
}

pub fn point_in(p: V2, ring: &[V2]) -> bool {
    let n = ring.len();
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (ring[i], ring[j]);
        if (a.y > p.y) != (b.y > p.y) {
            let x = a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y);
            if p.x < x {
                inside = !inside;
            }
        }
        j = i;
    }
    inside
}

impl<'a> Ex<'a> {
    /// The walls that bound a level's rooms: those standing at its computation height.
    fn room_walls(&self, level: &str) -> Vec<usize> {
        let lev = self.level_elev(level);
        let at = lev + 1200.0;
        let mut out = Vec::new();
        for (i, w) in self.walls.iter().enumerate() {
            let Some(e) = self.pr.el(w.id) else { continue };
            if e.get("room_bounding").and_then(|v| v.as_bool()) == Some(false) {
                continue;
            }
            let base = self.level_elev(&w.level) + e.get("base_offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let top = self.wall_top(e, base);
            if base <= at && top >= at {
                out.push(i);
            }
        }
        out
    }

    /// The centre line of each bounding wall, run on or back to meet the others at joins.
    fn centre_lines(&self, idx: &[usize]) -> Vec<Bound> {
        let walls: Vec<super::walls::Wall> = idx.iter().map(|i| self.walls[*i].clone()).collect();
        let mut out = Vec::new();
        for (k, w) in walls.iter().enumerate() {
            let off = (w.left - w.right) / 2.0;
            let pts = w.offset_points(off);
            let mut a = pts[0];
            let mut b = *pts.last().unwrap();
            if !w.is_arc() {
                let d = (w.end - w.start).normalize();
                a = super::walls::centre_end(&walls, k, false, a, d);
                b = super::walls::centre_end(&walls, k, true, b, d);
                out.push(Bound { a, b, key: (w.id, 0) });
            } else {
                for i in 0..pts.len() - 1 {
                    out.push(Bound { a: pts[i], b: pts[i + 1], key: (w.id, i) });
                }
            }
        }
        out
    }

    /// The face lines of each bounding wall: its outline's edges.
    fn face_lines(&self, idx: &[usize]) -> Vec<Bound> {
        let mut out = Vec::new();
        for i in idx {
            let w = &self.walls[*i];
            let Some(o) = self.wall_outlines.get(&w.id) else { continue };
            for k in 0..o.len() {
                out.push(Bound { a: o[k], b: o[(k + 1) % o.len()], key: (w.id, k) });
            }
        }
        out
    }

    fn separators(&self, level: &str) -> Vec<Bound> {
        let mut out = Vec::new();
        for (id, e) in &self.pr.elements {
            if e.get("category").and_then(|c| c.as_str()) != Some("roomseparator") {
                continue;
            }
            if e.get("level").and_then(|v| v.as_str()) != Some(level) {
                continue;
            }
            let a = super::walls::pt(e.get("start"));
            let b = super::walls::pt(e.get("end"));
            out.push(Bound { a, b, key: (*id, 0) });
        }
        out
    }

    /// A room's outline at the walls' centre lines and at their faces; none where nothing
    /// encloses it or another room (placed first) has its space.
    pub fn room_rings(&self, id: u64, e: &Value) -> Option<(Vec<V2>, Vec<V2>)> {
        self.room_rings_islands(id, e).map(|(g, n, _, _)| (g, n.unwrap_or_default()))
    }

    /// As `room_rings`, with the islands inside each (at the centre lines and at the faces);
    /// no ring at the faces where the point stands in a wall there.
    pub fn room_rings_islands(&self, id: u64, e: &Value) -> Option<(Vec<V2>, Option<Vec<V2>>, Vec<Vec<V2>>, Vec<Vec<V2>>)> {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let p = super::walls::pt(e.get("point"));
        let idx = self.room_walls(level);
        let seps = self.separators(level);
        let mut gl = self.centre_lines(&idx);
        gl.extend(seps.iter().cloned());
        let (gross, gross_islands) = face_with_islands(&gl, p)?;
        // two rooms can't share a space: the one placed first keeps it
        for (oid, oe) in &self.pr.elements {
            if *oid >= id || oe.get("category").and_then(|c| c.as_str()) != Some("room") {
                continue;
            }
            if oe.get("level").and_then(|v| v.as_str()) != Some(level) {
                continue;
            }
            let q = super::walls::pt(oe.get("point"));
            if point_in(q, &gross) {
                if let Some(og) = face_at(&gl, q) {
                    if og == gross {
                        return None;
                    }
                }
            }
        }
        let mut fl = self.face_lines(&idx);
        fl.extend(seps);
        // none at the faces where the point stands in a wall
        let in_wall = idx.iter().any(|i| self.wall_outlines.get(&self.walls[*i].id).map_or(false, |o| point_in(p, o)));
        let (net, net_islands) = match face_with_islands(&fl, p).filter(|_| !in_wall) {
            Some((r, i)) => (Some(r), i),
            None => (None, Vec::new()),
        };
        Some((gross, net, gross_islands, net_islands))
    }

    /// The footprints of the columns on a level, by element id: a rectangle turned as the
    /// column is, from its corner ahead and to the left round counter-clockwise; a round one
    /// in 24 chords from 30°.
    pub fn column_footprints(&self, level: &str) -> Vec<Vec<V2>> {
        let pr = self.pr;
        let mut out = Vec::new();
        for (_, e) in &pr.elements {
            let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
            if cat != "column" && cat != "structuralcolumn" {
                continue;
            }
            if e.get("level").and_then(|v| v.as_str()).unwrap_or("") != level {
                continue;
            }
            let key = if cat == "column" { "column" } else { "structural_column" };
            let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
            let td = super::walls::type_data(pr, key, tg);
            let w = td.and_then(|t| t.get("width")).and_then(|v| v.as_f64()).unwrap_or(200.0);
            let d = td.and_then(|t| t.get("depth")).and_then(|v| v.as_f64()).unwrap_or(w);
            let round = td.and_then(|t| t.get("round")).and_then(|v| v.as_bool()).unwrap_or(false);
            let c = super::walls::pt(e.get("at"));
            if round {
                let r = w / 2.0;
                let ring: Vec<V2> = (0..24)
                    .map(|k| {
                        let a = ((k + 2) as f64 * 15.0).to_radians();
                        c + v2(a.cos(), a.sin()) * r
                    })
                    .collect();
                out.push(ring);
            } else {
                let a = e.get("angle").and_then(|v| v.as_f64()).unwrap_or(0.0).to_radians();
                let (sn, cs) = a.sin_cos();
                let rot = |x: f64, y: f64| c + v2(x * cs - y * sn, x * sn + y * cs);
                let (hx, hy) = (w / 2.0, d / 2.0);
                out.push(vec![rot(hx, hy), rot(-hx, hy), rot(-hx, -hy), rot(hx, -hy)]);
            }
        }
        out
    }

    pub fn write_room(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let lev = self.level_elev(&level);
        let base_offset = e.get("base_offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let base = lev + base_offset;
        let top = match e.get("top_level").and_then(|v| v.as_str()) {
            Some(tl) if self.storey_of(tl).is_some() => {
                self.level_elev(tl) + e.get("limit_offset").and_then(|v| v.as_f64()).unwrap_or(0.0)
            }
            _ => match e.get("limit_offset").and_then(|v| v.as_f64()) {
                Some(o) => lev + o,
                None => base + 2500.0,
            },
        };
        let height = top - base;
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        let number = e.get("number").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let name = e.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let found = self.room_rings_islands(id, e);
        let finish = self.pr.get("room_area").and_then(|v| v.as_str()) == Some("finish");
        // the columns standing inside it, left out of it, and the islands of walls in it
        let columns = self.column_footprints(&level);
        let inside = |ring: &[V2]| -> Vec<Vec<V2>> {
            columns.iter().filter(|c| c.iter().all(|p| point_in(*p, ring))).cloned().collect()
        };
        let (gross_holes, net_holes) = match &found {
            Some((g, n, gi, ni)) => {
                let mut gh = gi.clone();
                gh.extend(inside(g));
                let mut nh = ni.clone();
                if let Some(n) = n {
                    nh.extend(inside(n));
                }
                (gh, nh)
            }
            None => (Vec::new(), Vec::new()),
        };
        let has_net = matches!(&found, Some((_, Some(_), _, _)));
        let rings = found.map(|(g, n, _, _)| {
            let n = n.unwrap_or_else(|| g.clone());
            (g, n)
        });
        let shape = match &rings {
            None => None,
            Some((gross, net)) => {
                let ring = if finish { net } else { gross };
                let holes = if finish { &net_holes } else { &gross_holes };
                let poly = self.closed_polyline(ring);
                let prof = if holes.is_empty() {
                    self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", poly))
                } else {
                    let hs: Vec<usize> = holes.iter().map(|h| self.closed_polyline(h)).collect();
                    self.add(format!("IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,#{},({}))", poly, refs(&hs)))
                };
                let style = match e.get("colour").and_then(|c| c.as_arr()) {
                    Some(c) if c.len() >= 3 => {
                        let f = |i: usize| c[i].as_f64().unwrap_or(0.0) / 255.0;
                        let rgb = self.add(format!("IFCCOLOURRGB($,{},{},{})", real(f(0)), real(f(1)), real(f(2))));
                        let sh = self.add(format!("IFCSURFACESTYLESHADING(#{},$)", rgb));
                        Some(self.add(format!("IFCSURFACESTYLE($,.BOTH.,(#{}))", sh)))
                    }
                    _ => None,
                };
                let pos = if base_offset != 0.0 {
                    let p = self.st.point3(0.0, 0.0, base_offset);
                    self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p))
                } else {
                    self.origin
                };
                let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(height)));
                if let Some(s) = style {
                    self.add(format!("IFCSTYLEDITEM(#{},(#{}),$)", solid, s));
                }
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
                Some(self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep)))
            }
        };
        let product = self.add(format!(
            "IFCSPACE('{}',$,{},$,$,#{},{},{},.ELEMENT.,.SPACE.,$)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            st(&number),
            place,
            shape.map(|s| format!("#{}", s)).unwrap_or_else(|| "$".into()),
            st(&name)
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, None, false);
        if let Some((gross, net)) = rings.as_ref().filter(|_| has_net) {
            let less = |a: f64, hs: &[Vec<V2>]| hs.iter().fold(a, |a, h| a - signed_area(h).abs());
            let more = |p: f64, hs: &[Vec<V2>]| hs.iter().fold(p, |p, h| p + perimeter(h));
            let ga = less(signed_area(gross).abs(), &gross_holes);
            let na = less(signed_area(net).abs(), &net_holes);
            self.quantities(
                "Qto_SpaceBaseQuantities",
                product,
                &[
                    ("L", "Height", height),
                    ("L", "GrossPerimeter", more(perimeter(gross), &gross_holes)),
                    ("L", "NetPerimeter", more(perimeter(net), &net_holes)),
                    ("A", "GrossFloorArea", ga / 1e6),
                    ("A", "NetFloorArea", na / 1e6),
                    ("V", "GrossVolume", ga * height / 1e9),
                    ("V", "NetVolume", na * height / 1e9),
                ],
            );
        }
        self.spaces.entry(level).or_default().push(product);
    }
}

impl<'a> Ex<'a> {
    /// A room separation line: an `IfcVirtualElement` with an axis on its storey.
    pub fn write_separator(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let a = super::walls::pt(e.get("start"));
        let b = super::walls::pt(e.get("end"));
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        let poly = self.open_polyline(&[a, b]);
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Axis','Curve2D',(#{}))", self.axis, poly));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let product = self.add(format!(
            "IFCVIRTUALELEMENT('{}',$,'Room Separation Line',$,'RoomSeparation',#{},#{},'{}')",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, None, false);
        self.contain(&level, product);
    }
}
