//! Structure and MEP: columns, structural columns and footings; runs (beams, strip footings,
//! pipes, ducts, conduits, cable trays, wires, conductors, cabling) along their own axes, with
//! their systems; reinforcing bars aggregated to their hosts.

use super::geom::*;
use super::step::{gid, real, refs, st};
use super::{Ex, TypeExtra};
use crate::json::Value;
use std::collections::BTreeMap;

/// A run category's IFC class, predefined type, and its type object's class.
pub fn run_class(cat: &str) -> (&'static str, &'static str, &'static str) {
    match cat {
        "beam" => ("IFCBEAM", "BEAM", "IFCBEAMTYPE"),
        "stripfooting" => ("IFCFOOTING", "STRIP_FOOTING", ""),
        "pipe" => ("IFCPIPESEGMENT", "RIGIDSEGMENT", "IFCPIPESEGMENTTYPE"),
        "duct" => ("IFCDUCTSEGMENT", "RIGIDSEGMENT", "IFCDUCTSEGMENTTYPE"),
        "conduit" => ("IFCCABLECARRIERSEGMENT", "CONDUITSEGMENT", "IFCCABLECARRIERSEGMENTTYPE"),
        "cabletray" => ("IFCCABLECARRIERSEGMENT", "CABLETRAYSEGMENT", "IFCCABLECARRIERSEGMENTTYPE"),
        "wire" | "cable" => ("IFCCABLESEGMENT", "CABLESEGMENT", "IFCCABLESEGMENTTYPE"),
        _ => ("IFCCABLESEGMENT", "CONDUCTORSEGMENT", "IFCCABLESEGMENTTYPE"),
    }
}

/// A section: width across by depth deep, or round.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Section {
    pub width: f64,
    pub depth: f64,
    pub round: bool,
}

impl Section {
    fn key(&self) -> String {
        format!("{}|{}|{}", self.width, self.depth, self.round)
    }
    fn area(&self) -> f64 {
        if self.round {
            std::f64::consts::PI * (self.width / 2.0) * (self.width / 2.0)
        } else {
            self.width * self.depth
        }
    }
    fn perimeter(&self) -> f64 {
        if self.round {
            std::f64::consts::PI * self.width
        } else {
            2.0 * (self.width + self.depth)
        }
    }
}

fn section_of(t: Option<&Value>) -> Section {
    let w = t.and_then(|t| t.get("width")).and_then(|v| v.as_f64()).unwrap_or(200.0);
    let d = t.and_then(|t| t.get("depth")).and_then(|v| v.as_f64()).unwrap_or(w);
    let round = t.and_then(|t| t.get("round")).and_then(|v| v.as_bool()).unwrap_or(false);
    Section { width: w, depth: d, round }
}

impl<'a> Ex<'a> {
    /// The profile of a section, written once and shared by every body and type of it.
    fn section_profile(&mut self, s: Section) -> usize {
        let key = s.key();
        if let Some(p) = self.profiles.get(&key) {
            return *p;
        }
        let p = self.new_profile(s);
        self.profiles.insert(key, p);
        p
    }

    fn new_profile(&mut self, s: Section) -> usize {
        let c = self.st.point2(0.0, 0.0);
        let a = self.add(format!("IFCAXIS2PLACEMENT2D(#{},$)", c));
        let p = if s.round {
            self.add(format!("IFCCIRCLEPROFILEDEF(.AREA.,$,#{},{})", a, real(s.width / 2.0)))
        } else {
            self.add(format!("IFCRECTANGLEPROFILEDEF(.AREA.,$,#{},{},{})", a, real(s.width), real(s.depth)))
        };
        p
    }

    /// Notes an occurrence of a type that carries its section as a material profile set.
    fn profiled_type(&mut self, class: &str, name: &str, tail: &str, product: usize, material: Option<String>, profile: usize, cardinal: i32) {
        let key = (class.to_string(), format!("{}\u{0}{}", name, profile));
        let t = self.types.entry(key).or_default();
        if t.tail.is_empty() {
            t.tail = tail.to_string();
            t.name = Some(name.to_string());
        }
        t.occ.push(product);
        if t.after.is_empty() {
            t.after.push(TypeExtra::Profile { material, profile, usages: BTreeMap::new() });
        }
        if let Some(TypeExtra::Profile { usages, .. }) = t.after.first_mut() {
            usages.entry(cardinal).or_default().push(product);
        }
    }

    pub fn write_column(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("column").to_string();
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let key = match cat.as_str() {
            "structuralcolumn" => "structural_column",
            "footing" => "footing",
            _ => "column",
        };
        let td = super::walls::type_data(pr, key, &tg);
        let sec = section_of(td);
        let at = super::walls::pt(e.get("at"));
        let angle = e.get("angle").and_then(|v| v.as_f64()).unwrap_or(0.0).to_radians();
        let lev = self.level_elev(&level);
        let (base, top) = self.span_of(e);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(at.x, at.y, base - lev), Some(v2(angle.cos(), angle.sin())));
        self.placements.insert(id, place);
        let prof = self.section_profile(sec);
        let h = top - base;
        let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, self.origin, self.up, real(h)));
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let name = st(&tname);
        let g = gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or(""));
        let (product, common, class, tail) = if cat == "footing" {
            (
                self.add(format!("IFCFOOTING('{}',$,{},$,{},#{},#{},'{}',.PAD_FOOTING.)", g, name, name, place, shape, id)),
                "Pset_FootingCommon",
                "IFCFOOTINGTYPE",
                "$,$,$,$,$,$,.PAD_FOOTING.",
            )
        } else {
            (
                self.add(format!("IFCCOLUMN('{}',$,{},$,{},#{},#{},'{}',.COLUMN.)", g, name, name, place, shape, id)),
                "Pset_ColumnCommon",
                "IFCCOLUMNTYPE",
                "$,$,$,$,$,$,.COLUMN.",
            )
        };
        self.products.insert(id, product);
        self.finish(id, e, product, Some(common), cat != "column");
        if cat != "footing" {
            self.quantities(
                "Qto_ColumnBaseQuantities",
                product,
                &[
                    ("L", "Length", h),
                    ("A", "CrossSectionArea", sec.area() / 1e6),
                    ("A", "OuterSurfaceArea", sec.perimeter() * h / 1e6),
                    ("V", "GrossVolume", sec.area() * h / 1e9),
                ],
            );
        }
        self.contain(&level, product);
        self.profiled_type(class, &tname, tail, product, None, prof, 5);
    }

    pub fn write_run(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("pipe").to_string();
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let td = pr.get("types").and_then(|t| t.get("runs")).and_then(|r| r.get(&cat)).and_then(|r| r.get(&tname));
        let sec = section_of(td);
        let a = super::walls::pt(e.get("start"));
        let b = super::walls::pt(e.get("end"));
        let off = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let end_off = e.get("end_offset").and_then(|v| v.as_f64()).unwrap_or(off);
        let justify = e.get("justify").and_then(|v| v.as_str()).unwrap_or("centre").to_string();
        // the axis: in plan from start to end, rising from one height to the other
        let flat = b - a;
        let rise = end_off - off;
        let d3 = v3(flat.x, flat.y, rise);
        let len = d3.length();
        let upright = flat.length() < 1e-9;
        let axis_dir = if len > 0.0 { d3.normalize() } else { v3(0.0, 0.0, 1.0) };
        let ref_dir = if upright { v2(1.0, 0.0) } else { flat.normalize().perp() };
        // its heights are its justify line's: the axis is half its depth (plumb) below a top
        let half = if upright {
            0.0
        } else {
            let cos = flat.length() / len;
            let dv = if sec.round { sec.width } else { sec.depth };
            dv / cos / 2.0
        };
        let z_axis = match justify.as_str() {
            "top" => off - half,
            "bottom" => off + half,
            _ => off,
        };
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(a.x, a.y, z_axis), None);
        self.placements.insert(id, place);
        // a beam's section is its type's, shared; the other runs write their own
        let prof = if cat == "beam" { self.section_profile(sec) } else { self.new_profile(sec) };
        let o = self.st.point3(0.0, 0.0, 0.0);
        let ad = self.st.dir3(axis_dir.x, axis_dir.y, axis_dir.z);
        let rd = self.st.dir3(ref_dir.x, ref_dir.y, 0.0);
        let pos = self.add(format!("IFCAXIS2PLACEMENT3D(#{},#{},#{})", o, ad, rd));
        let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(len)));
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let (class, predef, tclass) = run_class(&cat);
        let name = st(&tname);
        let g = gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or(""));
        let product = self.add(format!("{}('{}',$,{},$,{},#{},#{},'{}',.{}.)", class, g, name, name, place, shape, id, predef));
        self.products.insert(id, product);
        let structural = cat == "beam" || cat == "stripfooting";
        let common = match cat.as_str() {
            "beam" => Some("Pset_BeamCommon"),
            "stripfooting" => Some("Pset_FootingCommon"),
            _ => None,
        };
        self.finish(id, e, product, common, structural);
        if cat == "beam" {
            self.quantities(
                "Qto_BeamBaseQuantities",
                product,
                &[
                    ("L", "Length", len),
                    ("A", "CrossSectionArea", sec.area() / 1e6),
                    ("A", "OuterSurfaceArea", sec.perimeter() * len / 1e6),
                    ("V", "GrossVolume", sec.area() * len / 1e9),
                ],
            );
        }
        // the material: a beam's goes on its type's profile set, the others' on the run
        let mat_name = td.and_then(|t| t.get("material")).and_then(|m| m.as_str()).and_then(|m| self.material_name(m));
        let mut mat_ent = None;
        if cat != "beam" {
            if let Some(mn) = &mat_name {
                let (m, _) = self.material(mn);
                let gg = self.fresh();
                self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", gg, product, m));
                mat_ent = Some(m);
            }
        }
        let _ = mat_ent;
        let j = self.add(format!("IFCPROPERTYSINGLEVALUE('Justification',$,IFCTEXT({}),$)", st(&justify)));
        let c = self.add(format!("IFCPROPERTYSINGLEVALUE('Category',$,IFCTEXT({}),$)", st(&cat)));
        let gg = self.fresh();
        let ps = self.add(format!("IFCPROPERTYSET('{}',$,'BIMCraft_Run',$,(#{},#{}))", gg, j, c));
        let gg = self.fresh();
        self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", gg, product, ps));
        self.contain(&level, product);
        if let Some(sys) = e.get("system").and_then(|s| s.as_str()) {
            if !sys.is_empty() {
                self.systems.entry(sys.to_string()).or_default().push(product);
            }
        }
        if cat == "beam" {
            let cardinal = match justify.as_str() {
                "top" => 8,
                "bottom" => 2,
                _ => 5,
            };
            self.profiled_type("IFCBEAMTYPE", &tname, "$,$,$,$,$,$,.BEAM.", product, mat_name.clone(), prof, cardinal);
        } else if !tclass.is_empty() {
            self.typed(tclass, &tname, &format!("$,$,$,$,$,$,.{}.", predef), product);
        }
    }

    pub fn write_rebar(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let mut pts: Vec<V3> = Vec::new();
        if let Some(a) = e.get("path").and_then(|p| p.as_arr()) {
            for p in a {
                if let Some(q) = p.as_arr() {
                    let c = |i: usize| q.get(i).and_then(|x| x.as_f64()).unwrap_or(0.0);
                    pts.push(v3(c(0), c(1), c(2)));
                }
            }
        }
        let dia = e.get("diameter").and_then(|v| v.as_f64()).unwrap_or(10.0);
        let grade = e.get("grade").and_then(|v| v.as_str()).unwrap_or("CA-50").to_string();
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        let ids: Vec<usize> = pts.iter().map(|p| self.st.point3(p.x, p.y, p.z)).collect();
        let mut items = Vec::new();
        let mut length = 0.0;
        for i in 0..ids.len().saturating_sub(1) {
            let poly = self.add(format!("IFCPOLYLINE((#{},#{}))", ids[i], ids[i + 1]));
            items.push(self.add(format!("IFCSWEPTDISKSOLID(#{},{},$,$,$)", poly, real(dia / 2.0))));
            length += (pts[i + 1] - pts[i]).length();
        }
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','AdvancedSweptSolid',({}))", self.body, refs(&items)));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let r = dia / 2.0;
        let product = self.add(format!(
            "IFCREINFORCINGBAR('{}',$,{},$,$,#{},#{},'{}',{},{},{},{},.NOTDEFINED.,.PLAIN.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            st(&format!("Bar {}", dia)),
            place,
            shape,
            id,
            st(&grade),
            real(dia),
            real(std::f64::consts::PI * r * r),
            real(length)
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, None, false);
        match e.get("host").and_then(|h| h.as_str()).and_then(|h| self.pr.find_guid(h)) {
            Some(h) => self.rebar_hosts.entry(h).or_default().push(product),
            None => self.contain(&level, product),
        }
    }

    /// The bars on each host, aggregated to it.
    pub fn write_rebar_aggregates(&mut self) {
        let hosts = std::mem::take(&mut self.rebar_hosts);
        for (h, bars) in hosts {
            let Some(&hp) = self.products.get(&h) else { continue };
            let g = self.fresh();
            self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},({}))", g, hp, refs(&bars)));
        }
    }

    /// After the elements: each system named by runs, and the runs assigned to it.
    pub fn write_systems(&mut self) {
        let systems = std::mem::take(&mut self.systems);
        for (name, runs) in systems {
            let g = self.fresh();
            let s = self.add(format!("IFCSYSTEM('{}',$,{},$,$)", g, st(&name)));
            let g = self.fresh();
            self.add(format!("IFCRELASSIGNSTOGROUP('{}',$,$,$,({}),$,#{})", g, refs(&runs), s));
        }
    }
}
