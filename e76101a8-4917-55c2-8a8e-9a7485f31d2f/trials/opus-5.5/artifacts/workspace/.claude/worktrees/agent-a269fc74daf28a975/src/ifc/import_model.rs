//! An IFC file read for import: its entities, its units, and the relationships between its
//! objects looked up both ways.

use super::step::{Entity, StepFile, P};
use std::collections::BTreeMap;

pub struct Model {
    pub f: StepFile,
    /// Millimetres per length unit of the file.
    pub scale: f64,
    /// Radians per plane angle unit of the file.
    pub angle: f64,
    /// The schema, in upper case (`IFC4`, `IFC2X3`…).
    pub schema: String,
    /// element → the spatial structure element that contains it
    pub contained_in: BTreeMap<u64, u64>,
    /// structure → its contained elements, in the file's order
    pub contains: BTreeMap<u64, Vec<u64>>,
    /// child → parent (IfcRelAggregates)
    pub parent: BTreeMap<u64, u64>,
    /// parent → children (IfcRelAggregates), in the file's order
    pub children: BTreeMap<u64, Vec<u64>>,
    /// parent → nested children (IfcRelNests)
    pub nested: BTreeMap<u64, Vec<u64>>,
    /// element → its openings (IfcRelVoidsElement)
    pub openings: BTreeMap<u64, Vec<u64>>,
    /// opening → the element it voids
    pub voided: BTreeMap<u64, u64>,
    /// opening → what fills it (IfcRelFillsElement)
    pub filled_by: BTreeMap<u64, u64>,
    /// door or window → the opening it fills
    pub fills: BTreeMap<u64, u64>,
    /// object → its type (IfcRelDefinesByType; IfcRelDefinesByType in IFC2x3 too)
    pub type_of: BTreeMap<u64, u64>,
    /// object or type → its material (IfcRelAssociatesMaterial)
    pub material_of: BTreeMap<u64, u64>,
    /// object → its property definitions (IfcRelDefinesByProperties), in the file's order
    pub props: BTreeMap<u64, Vec<u64>>,
    /// object → the groups (systems) it is assigned to
    pub groups: BTreeMap<u64, Vec<u64>>,
    /// The entities by class name, in id order.
    pub by_class: BTreeMap<String, Vec<u64>>,
    /// representation item → the styled item that styles it
    pub styled: BTreeMap<u64, u64>,
}

impl Model {
    pub fn get(&self, id: u64) -> Option<&Entity> {
        self.f.entities.get(&id)
    }
    pub fn class(&self, id: u64) -> &str {
        self.get(id).map(|e| e.name.as_str()).unwrap_or("")
    }
    pub fn of(&self, class: &str) -> &[u64] {
        self.by_class.get(class).map(|v| v.as_slice()).unwrap_or(&[])
    }
    pub fn is_ifc4(&self) -> bool {
        !self.schema.starts_with("IFC2X")
    }

    pub fn new(f: StepFile, schema: String) -> Model {
        let mut m = Model {
            f,
            scale: 1.0,
            angle: 1.0,
            schema,
            contained_in: BTreeMap::new(),
            contains: BTreeMap::new(),
            parent: BTreeMap::new(),
            children: BTreeMap::new(),
            nested: BTreeMap::new(),
            openings: BTreeMap::new(),
            voided: BTreeMap::new(),
            filled_by: BTreeMap::new(),
            fills: BTreeMap::new(),
            type_of: BTreeMap::new(),
            material_of: BTreeMap::new(),
            props: BTreeMap::new(),
            groups: BTreeMap::new(),
            by_class: BTreeMap::new(),
            styled: BTreeMap::new(),
        };
        for (id, e) in &m.f.entities {
            m.by_class.entry(e.name.clone()).or_default().push(*id);
        }
        for (id, e) in &m.f.entities {
            let _ = id;
            match e.name.as_str() {
                "IFCRELCONTAINEDINSPATIALSTRUCTURE" => {
                    if let Some(s) = e.p(5).r() {
                        for el in e.p(4).refs() {
                            m.contained_in.entry(el).or_insert(s);
                            m.contains.entry(s).or_default().push(el);
                        }
                    }
                }
                "IFCRELAGGREGATES" => {
                    if let Some(p) = e.p(4).r() {
                        for c in e.p(5).refs() {
                            m.parent.entry(c).or_insert(p);
                            m.children.entry(p).or_default().push(c);
                        }
                    }
                }
                "IFCRELNESTS" => {
                    if let Some(p) = e.p(4).r() {
                        for c in e.p(5).refs() {
                            m.nested.entry(p).or_default().push(c);
                        }
                    }
                }
                "IFCRELVOIDSELEMENT" => {
                    if let (Some(h), Some(o)) = (e.p(4).r(), e.p(5).r()) {
                        m.openings.entry(h).or_default().push(o);
                        m.voided.entry(o).or_insert(h);
                    }
                }
                "IFCRELFILLSELEMENT" => {
                    if let (Some(o), Some(d)) = (e.p(4).r(), e.p(5).r()) {
                        m.filled_by.entry(o).or_insert(d);
                        m.fills.entry(d).or_insert(o);
                    }
                }
                "IFCRELDEFINESBYTYPE" => {
                    if let Some(t) = e.p(5).r() {
                        for o in e.p(4).refs() {
                            m.type_of.entry(o).or_insert(t);
                        }
                    }
                }
                "IFCRELASSOCIATESMATERIAL" => {
                    if let Some(mat) = e.p(5).r() {
                        for o in e.p(4).refs() {
                            m.material_of.entry(o).or_insert(mat);
                        }
                    }
                }
                "IFCRELDEFINESBYPROPERTIES" => {
                    if let Some(pd) = e.p(5).r() {
                        for o in e.p(4).refs() {
                            m.props.entry(o).or_default().push(pd);
                        }
                    }
                }
                "IFCSTYLEDITEM" => {
                    if let Some(it) = e.p(0).r() {
                        m.styled.entry(it).or_insert(*id);
                    }
                }
                "IFCRELASSIGNSTOGROUP" => {
                    if let Some(g) = e.p(6).r() {
                        for o in e.p(4).refs() {
                            m.groups.entry(o).or_default().push(g);
                        }
                    }
                }
                _ => {}
            }
        }
        // IFC2x3 types may be named by IfcRelDefinesByType only; IFC4 too. Types in IfcRelDefinesByProperties
        // are not types.
        m
    }

    /// Reads the project's units: the length unit (to millimetres) and the plane angle unit.
    pub fn read_units(&mut self, project: u64) {
        let ua = self.get(project).and_then(|e| e.p(8).r());
        let mut scale = None;
        let mut angle = None;
        if let Some(ua) = ua.and_then(|u| self.get(u)) {
            for u in ua.p(0).refs() {
                if let Some((kind, f)) = self.unit_factor(u, 0) {
                    match kind.as_str() {
                        "LENGTHUNIT" if scale.is_none() => scale = Some(f * 1000.0),
                        "PLANEANGLEUNIT" if angle.is_none() => angle = Some(f),
                        _ => {}
                    }
                }
            }
        }
        self.scale = scale.unwrap_or(1.0);
        self.angle = angle.unwrap_or(1.0);
    }

    /// A unit's kind and its factor to the SI unit (metres, radians).
    pub fn unit_factor(&self, id: u64, depth: usize) -> Option<(String, f64)> {
        if depth > 8 {
            return None;
        }
        let e = self.get(id)?;
        match e.name.as_str() {
            "IFCSIUNIT" => {
                let kind = e.p(1).enm()?.to_string();
                let prefix = match e.p(2).enm() {
                    None => 1.0,
                    Some(p) => prefix_factor(p),
                };
                Some((kind, prefix))
            }
            "IFCCONVERSIONBASEDUNIT" | "IFCCONVERSIONBASEDUNITWITHOFFSET" => {
                let kind = e.p(1).enm()?.to_string();
                let mwu = self.get(e.p(3).r()?)?;
                let v = mwu.p(0).num()?;
                let (_, f) = self.unit_factor(mwu.p(1).r()?, depth + 1)?;
                Some((kind, v * f))
            }
            _ => None,
        }
    }

    /// A root object's Name (attribute 2), if it is a string.
    pub fn name(&self, id: u64) -> Option<String> {
        self.get(id).and_then(|e| e.p(2).str()).map(|s| s.to_string())
    }

    /// The object type (attribute 4) of an object.
    pub fn object_type(&self, id: u64) -> Option<String> {
        self.get(id).and_then(|e| e.p(4).str()).map(|s| s.to_string())
    }

    /// The property sets of an object: its own, then its type's (HasPropertySets) where it has
    /// not the same set itself. Each as (set name, [(property name, value)]).
    pub fn psets(&self, id: u64) -> Vec<(String, Vec<(String, P)>)> {
        let mut out: Vec<(String, Vec<(String, P)>)> = Vec::new();
        if let Some(defs) = self.props.get(&id) {
            for d in defs {
                if let Some(s) = self.pset(*d) {
                    out.push(s);
                }
            }
        }
        out
    }

    pub fn type_psets(&self, tid: u64) -> Vec<(String, Vec<(String, P)>)> {
        let mut out = Vec::new();
        if let Some(t) = self.get(tid) {
            for d in t.p(5).refs() {
                if let Some(s) = self.pset(d) {
                    out.push(s);
                }
            }
        }
        if let Some(defs) = self.props.get(&tid) {
            for d in defs {
                if let Some(s) = self.pset(*d) {
                    out.push(s);
                }
            }
        }
        out
    }

    /// A property set's name and its single values (and the nominal values of other kinds as
    /// they are).
    pub fn pset(&self, id: u64) -> Option<(String, Vec<(String, P)>)> {
        let e = self.get(id)?;
        if e.name != "IFCPROPERTYSET" {
            return None;
        }
        let name = e.p(2).str().unwrap_or("").to_string();
        let mut props = Vec::new();
        for p in e.p(4).refs() {
            if let Some(pe) = self.get(p) {
                if pe.name == "IFCPROPERTYSINGLEVALUE" {
                    let n = pe.p(0).str().unwrap_or("").to_string();
                    props.push((n, pe.p(2).clone()));
                }
            }
        }
        Some((name, props))
    }

    /// A property's value from the object's sets (then its type's), by set and property name.
    pub fn prop(&self, id: u64, set: &str, name: &str) -> Option<P> {
        for (s, ps) in self.psets(id) {
            if s == set {
                for (n, v) in ps {
                    if n == name {
                        return Some(v);
                    }
                }
            }
        }
        if let Some(t) = self.type_of.get(&id) {
            for (s, ps) in self.type_psets(*t) {
                if s == set {
                    for (n, v) in ps {
                        if n == name {
                            return Some(v);
                        }
                    }
                }
            }
        }
        None
    }

    /// The storey (or other spatial element) an element is in: its container, or its parent's.
    pub fn container(&self, id: u64) -> Option<u64> {
        let mut cur = id;
        for _ in 0..16 {
            if let Some(s) = self.contained_in.get(&cur) {
                return Some(*s);
            }
            match self.parent.get(&cur) {
                Some(p) => {
                    let c = self.class(*p);
                    if c == "IFCBUILDINGSTOREY" || c == "IFCBUILDING" || c == "IFCSITE" || c == "IFCPROJECT" || c == "IFCSPACE" {
                        return Some(*p);
                    }
                    cur = *p;
                }
                None => {
                    // an opening's or a filling's host
                    if let Some(h) = self.voided.get(&cur) {
                        cur = *h;
                        continue;
                    }
                    if let Some(o) = self.fills.get(&cur) {
                        cur = *o;
                        continue;
                    }
                    return None;
                }
            }
        }
        None
    }
}

pub fn prefix_factor(p: &str) -> f64 {
    match p {
        "EXA" => 1e18,
        "PETA" => 1e15,
        "TERA" => 1e12,
        "GIGA" => 1e9,
        "MEGA" => 1e6,
        "KILO" => 1e3,
        "HECTO" => 1e2,
        "DECA" => 1e1,
        "DECI" => 1e-1,
        "CENTI" => 1e-2,
        "MILLI" => 1e-3,
        "MICRO" => 1e-6,
        "NANO" => 1e-9,
        "PICO" => 1e-12,
        "FEMTO" => 1e-15,
        "ATTO" => 1e-18,
        _ => 1.0,
    }
}

const B64: &[u8; 64] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";

/// An IFC GlobalId (22 characters of IFC's base 64) as a GUID, if it is one.
pub fn guid_of_global_id(g: &str) -> Option<String> {
    if g.len() != 22 {
        return None;
    }
    let mut n: u128 = 0;
    for (i, c) in g.bytes().enumerate() {
        let v = B64.iter().position(|x| *x == c)? as u128;
        if i == 0 && v > 3 {
            return None;
        }
        n = (n << 6) | v;
    }
    let h = format!("{:032x}", n);
    Some(format!("{}-{}-{}-{}-{}", &h[0..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32]))
}
