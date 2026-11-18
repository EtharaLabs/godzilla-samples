//! Floors as slabs (level, sloped, shaped), ceilings as coverings, shafts as openings through
//! what they reach, masses as proxies.

use super::geom::*;
use super::step::{gid, real, refs, st};
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

fn json_ring(r: &[V2]) -> String {
    let mut s = String::from("[");
    for (i, p) in r.iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        s.push('[');
        s.push_str(&crate::json::fmt_f64(p.x));
        s.push(',');
        s.push_str(&crate::json::fmt_f64(p.y));
        s.push(']');
    }
    s.push(']');
    s
}

/// Strips a lofted mass's twisted side is cut into up its height.
pub const STRIPS: usize = 16;

/// A floor's, a ceiling's or a roof's holes.
pub fn rings_of(v: Option<&Value>) -> Vec<Vec<V2>> {
    let mut out = Vec::new();
    if let Some(a) = v.and_then(|x| x.as_arr()) {
        for r in a {
            let ring = ring_of(Some(r));
            if ring.len() >= 3 {
                out.push(ring);
            }
        }
    }
    out
}

/// The plane of a sloped floor's top: rising `slope` degrees from the arrow's tail, where it is
/// at `z0`, toward its head.
#[derive(Clone, Copy, Debug)]
pub struct Slope {
    pub tail: V2,
    pub dir: V2,
    pub tan: f64,
    pub z0: f64,
    pub cos: f64,
}

impl Slope {
    pub fn z(&self, p: V2) -> f64 {
        self.z0 + (p - self.tail).dot(self.dir) * self.tan
    }

    /// The plane of its underside in the building's heights, `tv` (its plumb thickness) under
    /// its top, on a level at `lev`: what its corners' heights are taken from.
    pub fn underside(&self, lev: f64, tv: f64) -> Under {
        let nx = -self.dir.x * self.tan;
        let ny = -self.dir.y * self.tan;
        let dd = nx * self.tail.x + ny * self.tail.y + lev + (self.z0 - tv);
        Under { nx, ny, dd, lev }
    }
}

/// A sloped floor's underside: `(dd - (nx x + ny y)) - lev` over its level.
#[derive(Clone, Copy, Debug)]
pub struct Under {
    pub nx: f64,
    pub ny: f64,
    pub dd: f64,
    pub lev: f64,
}

impl Under {
    pub fn z(&self, p: V2) -> f64 {
        (self.dd - (self.nx * p.x + self.ny * p.y)) - self.lev
    }
}

pub fn slope_of(e: &Value, z0: f64) -> Option<Slope> {
    let s = e.get("slope").and_then(|v| v.as_f64()).unwrap_or(0.0);
    if s == 0.0 {
        return None;
    }
    let arrow = ring_of(e.get("arrow"));
    if arrow.len() < 2 {
        return None;
    }
    let d = arrow[1] - arrow[0];
    if d.length() < 1e-9 {
        return None;
    }
    let r = s.to_radians();
    Some(Slope { tail: arrow[0], dir: d.normalize(), tan: r.tan(), z0, cos: r.cos() })
}

impl<'a> Ex<'a> {
    pub fn write_floor(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let td = super::walls::type_data(pr, "floor", &tg);
        let t = td.and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(200.0);
        let offset = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let boundary = ring_of(e.get("boundary"));
        let holes = rings_of(e.get("openings"));
        let structural = e.get("structural").and_then(|v| v.as_bool()).unwrap_or(false);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let gross_area = signed_area(&boundary).abs();
        let holes_area: f64 = holes.iter().map(|h| signed_area(h).abs()).sum();
        let slope = slope_of(e, offset);
        let shape;
        let quantities: Vec<(&str, &str, f64)>;
        let shaped = slope.is_none() && super::shaped::has_shape(e);
        match slope {
            None if shaped => {
                // its top over the shape, its underside the same lower or, with a variable
                // layer, level under its offset
                let (points, lines) = super::shaped::shape_of(e);
                let variable = self.variable_type("floor", &tg);
                let heights = |s: &super::shaped::Shaped| -> (Vec<f64>, Vec<f64>) {
                    let top: Vec<f64> = s.z.iter().map(|z| offset + z).collect();
                    let bottom: Vec<f64> = if variable { vec![offset - t; top.len()] } else { top.iter().map(|z| z - t).collect() };
                    (top, bottom)
                };
                let s = super::shaped::build(&boundary, &holes, &points, &lines);
                let (top, bottom) = heights(&s);
                let brep = self.shaped_brep(&s, &top, &bottom);
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',(#{}))", self.body, brep));
                shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                let net = s.volume(&top, &bottom);
                let whole = super::shaped::build(&boundary, &[], &points, &lines);
                let (wt, wb) = heights(&whole);
                let gross = whole.volume(&wt, &wb);
                quantities = vec![("L", "Width", t), ("V", "GrossVolume", gross / 1e9), ("V", "NetVolume", net / 1e9)];
            }
            None => {
                let outer = self.closed_polyline(&boundary);
                let prof = if holes.is_empty() {
                    self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", outer))
                } else {
                    let inner: Vec<usize> = holes.iter().map(|h| self.closed_polyline(h)).collect();
                    self.add(format!("IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,#{},({}))", outer, refs(&inner)))
                };
                let p = self.st.point3(0.0, 0.0, offset - t);
                let pos = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p));
                let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(t)));
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
                shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                let net = gross_area - holes_area;
                quantities = vec![
                    ("L", "Width", t),
                    ("L", "Perimeter", perimeter(&boundary)),
                    ("A", "GrossArea", gross_area / 1e6),
                    ("A", "NetArea", net / 1e6),
                    ("V", "GrossVolume", gross_area * t / 1e9),
                    ("V", "NetVolume", net * t / 1e9),
                ];
            }
            Some(sl) => {
                // plumb it is its thickness over the cosine of its slope
                let tv = t / sl.cos;
                let under = sl.underside(self.level_elev(&level), tv);
                let breps = self.sloped_breps(&boundary, &holes, &under, tv);
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',({}))", self.body, refs(&breps)));
                shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                let net = gross_area - holes_area;
                quantities = vec![("L", "Width", tv), ("V", "GrossVolume", gross_area * tv / 1e9), ("V", "NetVolume", net * tv / 1e9)];
            }
        }
        let name = st(&tname);
        let product = self.add(format!(
            "IFCSLAB('{}',$,{},$,{},#{},#{},'{}',.FLOOR.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            name,
            name,
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, Some("Pset_SlabCommon"), structural);
        self.quantities("Qto_SlabBaseQuantities", product, &quantities);
        self.contain(&level, product);
        self.typed("IFCSLABTYPE", &tname, "$,$,$,$,$,$,.FLOOR.", product);
        if let Some(layers) = td.and_then(|t| t.get("layers")).and_then(|l| l.as_arr()).cloned() {
            if !layers.is_empty() {
                self.layer_usages.push(super::LayerUse {
                    kind: super::LayerKind::Slab,
                    type_key: format!("floor:{}", tg),
                    type_name: tname.clone(),
                    layers,
                    offset,
                    product,
                });
            }
        }
        self.cuttable.push((id, product, place, 0.0));
    }

    /// A sloped slab: closed shells between its top plane and the same plane `tv` lower, its
    /// sides plumb.
    fn sloped_breps(&mut self, boundary: &[V2], holes: &[Vec<V2>], under: &Under, tv: f64) -> Vec<usize> {
        let pieces = convex_pieces(boundary, holes);
        pieces.iter().map(|ring| self.prism_brep(ring, &|p| under.z(p), &|p| under.z(p) + tv)).collect()
    }

    /// A closed faceted Brep over a ring in plan, between two heights at each corner: its
    /// bottom (turned down), its top, and a side for each edge.
    pub fn prism_brep(&mut self, ring: &[V2], bottom: &dyn Fn(V2) -> f64, top: &dyn Fn(V2) -> f64) -> usize {
        let n = ring.len();
        let b: Vec<usize> = ring.iter().map(|p| self.st.point3(p.x, p.y, bottom(*p))).collect();
        let t: Vec<usize> = ring.iter().map(|p| self.st.point3(p.x, p.y, top(*p))).collect();
        let mut faces = Vec::new();
        let rb: Vec<usize> = b.iter().rev().cloned().collect();
        faces.push(self.face(&rb));
        faces.push(self.face(&t));
        for i in 0..n {
            let j = (i + 1) % n;
            faces.push(self.face(&[b[i], b[j], t[j], t[i]]));
        }
        let shell = self.add(format!("IFCCLOSEDSHELL(({}))", refs(&faces)));
        self.add(format!("IFCFACETEDBREP(#{})", shell))
    }

    /// `IFCPOLYLOOP`, `IFCFACEOUTERBOUND` and `IFCFACE` over points written already.
    pub fn face(&mut self, pts: &[usize]) -> usize {
        let l = self.add(format!("IFCPOLYLOOP(({}))", refs(pts)));
        let b = self.add(format!("IFCFACEOUTERBOUND(#{},.T.)", l));
        self.add(format!("IFCFACE((#{}))", b))
    }

    pub fn write_ceiling(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let td = super::walls::type_data(pr, "ceiling", &tg);
        let t = td.and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(20.0);
        let offset = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(2600.0);
        let boundary = ring_of(e.get("boundary"));
        let holes = rings_of(e.get("openings"));
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let outer = self.closed_polyline(&boundary);
        let prof = if holes.is_empty() {
            self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", outer))
        } else {
            let inner: Vec<usize> = holes.iter().map(|h| self.closed_polyline(h)).collect();
            self.add(format!("IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,#{},({}))", outer, refs(&inner)))
        };
        let p = self.st.point3(0.0, 0.0, offset);
        let pos = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p));
        let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(t)));
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let name = st(&tname);
        let product = self.add(format!(
            "IFCCOVERING('{}',$,{},$,{},#{},#{},'{}',.CEILING.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            name,
            name,
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, Some("Pset_CoveringCommon"), false);
        self.contain(&level, product);
        self.typed("IFCCOVERINGTYPE", &tname, "$,$,$,$,$,$,.CEILING.", product);
        if let Some(layers) = td.and_then(|t| t.get("layers")).and_then(|l| l.as_arr()).cloned() {
            if !layers.is_empty() {
                self.layer_usages.push(super::LayerUse {
                    kind: super::LayerKind::Covering,
                    type_key: format!("ceiling:{}", tg),
                    type_name: tname.clone(),
                    layers,
                    offset: 0.0,
                    product,
                });
            }
        }
        self.cuttable.push((id, product, place, 0.0));
    }

    /// Each shaft's opening through each floor, ceiling and roof its span reaches into and its
    /// outline overlaps, placed in that element's axes.
    pub fn write_shafts(&mut self) {
        let pr = self.pr;
        let shafts: Vec<u64> = pr.ids_of("shaft");
        for sid in shafts {
            let se = pr.el(sid).unwrap();
            let ring = ring_of(se.get("boundary"));
            let (base, top) = self.span_of(se);
            let hosts = self.cuttable.clone();
            for (hid, hprod, hplace, _) in hosts {
                let he = pr.el(hid).unwrap();
                let Some((z0, z1, outline)) = self.host_extent(hid, he) else { continue };
                if !(base < z1 && top > z0) {
                    continue;
                }
                if !rings_overlap(&ring, &outline) {
                    continue;
                }
                let hz = self.level_elev(he.get("level").and_then(|v| v.as_str()).unwrap_or(""));
                let oplace = self.placement(hplace, v3(0.0, 0.0, base - hz), None);
                let poly = self.closed_polyline(&ring);
                let prof = self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", poly));
                let solid =
                    self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, self.origin, self.up, real(top - base)));
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
                let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                let g = self.fresh();
                let op = self.add(format!(
                    "IFCOPENINGELEMENT('{}',$,'Shaft',$,$,#{},#{},'{}',.OPENING.)",
                    g, oplace, shape, sid
                ));
                let g = self.fresh();
                self.add(format!("IFCRELVOIDSELEMENT('{}',$,$,$,#{},#{})", g, hprod, op));
            }
        }
    }

    /// The heights a floor, ceiling or roof spans, and its outline in plan.
    pub fn host_span(&self, id: u64, e: &Value) -> Option<(f64, f64, Vec<V2>)> {
        self.host_extent(id, e)
    }

    fn host_extent(&self, id: u64, e: &Value) -> Option<(f64, f64, Vec<V2>)> {
        let pr = self.pr;
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let lev = self.level_elev(level);
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let boundary = ring_of(e.get("boundary"));
        match cat {
            "floor" => {
                let t = super::walls::type_data(pr, "floor", tg).and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(200.0);
                let off = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
                match slope_of(e, off) {
                    None => Some((lev + off - t, lev + off, boundary)),
                    Some(sl) => {
                        let tv = t / sl.cos;
                        let zs: Vec<f64> = boundary.iter().map(|p| sl.z(*p)).collect();
                        let lo = zs.iter().cloned().fold(f64::INFINITY, f64::min);
                        let hi = zs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
                        Some((lev + lo - tv, lev + hi, boundary))
                    }
                }
            }
            "ceiling" => {
                let t = super::walls::type_data(pr, "ceiling", tg).and_then(|t| t.get("thickness")).and_then(|v| v.as_f64()).unwrap_or(20.0);
                let off = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(2600.0);
                Some((lev + off, lev + off + t, boundary))
            }
            _ => {
                let _ = id;
                self.roof_extent(id, e)
            }
        }
    }

    /// The bottom and the top of something standing on a level: from its base offset over the
    /// level up to its top level (and offset) or its height.
    pub fn span_of(&self, e: &Value) -> (f64, f64) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        let base = self.level_elev(level) + e.get("base_offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let top = self.wall_top(e, base);
        (base, top)
    }

    pub fn write_mass(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let lev = self.level_elev(&level);
        let (base, top) = self.span_of(e);
        let base_offset = base - lev;
        let boundary = ring_of(e.get("boundary"));
        let top_ring = ring_of(e.get("top"));
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        let lofted = !top_ring.is_empty() && top_ring.len() == boundary.len() && top_ring != boundary;
        let name = e.get("name").and_then(|v| v.as_str()).unwrap_or("Mass").to_string();
        let shape;
        let mut loft_json = None;
        if !lofted {
            let poly = self.closed_polyline(&boundary);
            let prof = self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", poly));
            let pos = if base_offset != 0.0 {
                let p = self.st.point3(0.0, 0.0, base_offset);
                self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p))
            } else {
                self.origin
            };
            let solid =
                self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(top - base)));
            let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
            shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        } else {
            // the footprint and its top, counter-clockwise
            let mut b = boundary.clone();
            let mut t = top_ring.clone();
            if signed_area(&b) < 0.0 {
                b.reverse();
                t.reverse();
            }
            let zb = base_offset;
            let zt = top - lev;
            let mesh = loft_mesh(&b, &t, zb, zt);
            let fs = self.face_set_plain(&mesh.0, &mesh.1);
            let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Tessellation',(#{}))", self.body, fs));
            shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
            loft_json = Some(format!("{{\"bottom\":{},\"top\":{}}}", json_ring(&b), json_ring(&t)));
        }
        let product = self.add(format!(
            "IFCBUILDINGELEMENTPROXY('{}',$,{},$,'Mass',#{},#{},'{}',.USERDEFINED.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            st(&name),
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, None, false);
        if let Some(j) = loft_json {
            let p = self.add(format!("IFCPROPERTYSINGLEVALUE('Loft',$,IFCTEXT({}),$)", st(&j)));
            let g = self.fresh();
            let ps = self.add(format!("IFCPROPERTYSET('{}',$,'BIMCraft_Mass',$,(#{}))", g, p));
            let g = self.fresh();
            self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, ps));
        }
        self.contain(&level, product);
    }

    /// A closed face set of points and triangles, unstyled.
    pub fn face_set_plain(&mut self, pts: &[V3], tris: &[[usize; 3]]) -> usize {
        let mut s = String::new();
        for (i, p) in pts.iter().enumerate() {
            if i > 0 {
                s.push(',');
            }
            s.push_str(&format!("({},{},{})", real(p.x), real(p.y), real(p.z)));
        }
        let list = self.add(format!("IFCCARTESIANPOINTLIST3D(({}))", s));
        let mut t = String::new();
        for (i, x) in tris.iter().enumerate() {
            if i > 0 {
                t.push(',');
            }
            t.push_str(&format!("({},{},{})", x[0] + 1, x[1] + 1, x[2] + 1));
        }
        self.add(format!("IFCTRIANGULATEDFACESET(#{},$,.T.,({}),$)", list, t))
    }
}

/// A lofted mass's skin: its top's triangles, its bottom's (turned down), and each side, flat
/// in two triangles where its twin edges are parallel, else in strips up its height.
pub fn loft_mesh(b: &[V2], t: &[V2], zb: f64, zt: f64) -> (Vec<V3>, Vec<[usize; 3]>) {
    let mut pts: Vec<V3> = Vec::new();
    let mut tris: Vec<[usize; 3]> = Vec::new();
    let put = |pts: &mut Vec<V3>, p: V3| -> usize {
        if let Some(i) = pts.iter().position(|q| *q == p) {
            return i;
        }
        pts.push(p);
        pts.len() - 1
    };
    let top_tris = super::family::ear_clip(t);
    for x in &top_tris {
        let a = put(&mut pts, v3(t[x[0]].x, t[x[0]].y, zt));
        let bb = put(&mut pts, v3(t[x[1]].x, t[x[1]].y, zt));
        let c = put(&mut pts, v3(t[x[2]].x, t[x[2]].y, zt));
        tris.push([a, bb, c]);
    }
    let bot_tris = super::family::ear_clip(b);
    for x in &bot_tris {
        let a = put(&mut pts, v3(b[x[0]].x, b[x[0]].y, zb));
        let c = put(&mut pts, v3(b[x[2]].x, b[x[2]].y, zb));
        let bb = put(&mut pts, v3(b[x[1]].x, b[x[1]].y, zb));
        tris.push([a, c, bb]);
    }
    let n = b.len();
    for i in 0..n {
        let j = (i + 1) % n;
        let eb = b[j] - b[i];
        let et = t[j] - t[i];
        let parallel = eb.cross(et).abs() <= 1e-9 * eb.length() * et.length().max(1e-12) && eb.dot(et) > 0.0;
        let k = if parallel { 1 } else { STRIPS };
        let at = |p: V2, q: V2, s: usize| -> V3 {
            if s == 0 {
                return v3(p.x, p.y, zb);
            }
            if s == k {
                return v3(q.x, q.y, zt);
            }
            let f = s as f64 / k as f64;
            let r = p + (q - p) * f;
            v3(r.x, r.y, zb + (zt - zb) * f)
        };
        for s in 0..k {
            let l0 = put(&mut pts, at(b[i], t[i], s));
            let r0 = put(&mut pts, at(b[j], t[j], s));
            let r1 = put(&mut pts, at(b[j], t[j], s + 1));
            let l1 = put(&mut pts, at(b[i], t[i], s + 1));
            tris.push([l0, r0, r1]);
            tris.push([l0, r1, l1]);
        }
    }
    (pts, tris)
}

#[allow(dead_code)]
fn unused() {
    let _ = refs(&[]);
}

/// A floor's outline less its holes as convex pieces: the outline (cut into triangles where it
/// is not convex) split round each hole (cut into triangles where it is not convex, turned
/// counter-clockwise).
pub fn convex_pieces(boundary: &[V2], holes: &[Vec<V2>]) -> Vec<Vec<V2>> {
    let mut hs: Vec<Vec<V2>> = Vec::new();
    for h in holes.iter().filter(|h| h.len() >= 3) {
        let mut h = h.clone();
        if signed_area(&h) < 0.0 {
            h.reverse();
        }
        if is_convex(&h) {
            hs.push(h);
        } else {
            hs.extend(ear_clip(&h));
        }
    }
    if hs.is_empty() {
        return vec![boundary.to_vec()];
    }
    let regions = if is_convex(boundary) { vec![boundary.to_vec()] } else { ear_clip(boundary) };
    let mut out = Vec::new();
    for r in regions {
        let within: Vec<&[V2]> = hs.iter().filter(|h| boxes_meet(h, &r)).map(|h| h.as_slice()).collect();
        split_round_holes(r, &within, &mut out);
    }
    out
}

/// Whether a ring turns one way only (straight corners allowed).
fn is_convex(ring: &[V2]) -> bool {
    let n = ring.len();
    let (mut pos, mut neg) = (false, false);
    for i in 0..n {
        let (a, b, c) = (ring[i], ring[(i + 1) % n], ring[(i + 2) % n]);
        let z = (b - a).cross(c - b);
        if z > 0.0 {
            pos = true;
        } else if z < 0.0 {
            neg = true;
        }
    }
    !(pos && neg)
}

/// Triangles of a ring by ear clipping: each time the first corner from the start that turns
/// the ring's way with no other corner in its triangle, cut off as (previous, it, next).
fn ear_clip(ring: &[V2]) -> Vec<Vec<V2>> {
    let ccw = signed_area(ring) > 0.0;
    let mut idx: Vec<usize> = (0..ring.len()).collect();
    let mut out = Vec::new();
    while idx.len() >= 3 {
        let m = idx.len();
        let mut found = None;
        for i in 0..m {
            let (ip, ic, inx) = (idx[(i + m - 1) % m], idx[i], idx[(i + 1) % m]);
            let (p, c, n) = (ring[ip], ring[ic], ring[inx]);
            let z = (c - p).cross(n - c);
            if !(if ccw { z > 0.0 } else { z < 0.0 }) {
                continue;
            }
            let blocked = idx.iter().any(|&k| k != ip && k != ic && k != inx && in_triangle(ring[k], p, c, n, ccw));
            if !blocked {
                found = Some(i);
                break;
            }
        }
        let Some(i) = found else { break };
        let (ip, ic, inx) = (idx[(i + m - 1) % m], idx[i], idx[(i + 1) % m]);
        out.push(vec![ring[ip], ring[ic], ring[inx]]);
        idx.remove(i);
    }
    out
}

fn in_triangle(q: V2, a: V2, b: V2, c: V2, ccw: bool) -> bool {
    let s = |u: V2, v: V2| {
        let z = (v - u).cross(q - u);
        if ccw {
            z >= 0.0
        } else {
            z <= 0.0
        }
    };
    s(a, b) && s(b, c) && s(c, a)
}

fn boxes_meet(a: &[V2], b: &[V2]) -> bool {
    let bx = |r: &[V2]| {
        let mut lo = v2(f64::INFINITY, f64::INFINITY);
        let mut hi = v2(f64::NEG_INFINITY, f64::NEG_INFINITY);
        for p in r {
            lo = v2(lo.x.min(p.x), lo.y.min(p.y));
            hi = v2(hi.x.max(p.x), hi.y.max(p.y));
        }
        (lo, hi)
    };
    let ((alo, ahi), (blo, bhi)) = (bx(a), bx(b));
    alo.x <= bhi.x && blo.x <= ahi.x && alo.y <= bhi.y && blo.y <= ahi.y
}

/// A ring with holes in it as pieces without: the first hole's edges one after another each
/// cut off what lies outside that edge (forward Sutherland-Hodgman), each such part split in
/// turn round the holes that meet it; what is left inside the last edge is the hole.
pub fn split_round_holes(ring: Vec<V2>, holes: &[&[V2]], out: &mut Vec<Vec<V2>>) {
    let ok = |r: &Vec<V2>| r.len() >= 3 && signed_area(r).abs() > 1.0;
    let Some((h, rest)) = holes.split_first() else {
        out.push(ring);
        return;
    };
    let mut cur = ring;
    let m = h.len();
    for k in 0..m {
        let a = h[k];
        let d = h[(k + 1) % m] - a;
        if d.x == 0.0 && d.y == 0.0 {
            continue;
        }
        let side = |p: V2| d.x * (p.y - a.y) - d.y * (p.x - a.x);
        let outer = super::roofs::half_fwd(&cur, &side, false);
        let inner = super::roofs::half_fwd(&cur, &side, true);
        if ok(&outer) {
            let within: Vec<&[V2]> = rest.iter().filter(|o| boxes_meet(o, &outer)).cloned().collect();
            split_round_holes(outer, &within, out);
        }
        cur = inner;
        if !ok(&cur) {
            break;
        }
    }
}

fn point_in(p: V2, ring: &[V2]) -> bool {
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

fn segs_cross(a: V2, b: V2, c: V2, d: V2) -> bool {
    let d1 = (b - a).cross(c - a);
    let d2 = (b - a).cross(d - a);
    let d3 = (d - c).cross(a - c);
    let d4 = (d - c).cross(b - c);
    ((d1 > 0.0 && d2 < 0.0) || (d1 < 0.0 && d2 > 0.0)) && ((d3 > 0.0 && d4 < 0.0) || (d3 < 0.0 && d4 > 0.0))
}

/// Whether two rings share some area.
pub fn rings_overlap(a: &[V2], b: &[V2]) -> bool {
    if a.len() < 3 || b.len() < 3 {
        return false;
    }
    for i in 0..a.len() {
        let (p, q) = (a[i], a[(i + 1) % a.len()]);
        for j in 0..b.len() {
            if segs_cross(p, q, b[j], b[(j + 1) % b.len()]) {
                return true;
            }
        }
    }
    let centre = |r: &[V2]| {
        let mut c = v2(0.0, 0.0);
        for p in r {
            c = c + *p;
        }
        c * (1.0 / r.len() as f64)
    };
    a.iter().any(|p| point_in(*p, b)) || b.iter().any(|p| point_in(*p, a)) || point_in(centre(a), b) || point_in(centre(b), a)
}
