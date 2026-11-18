//! Lookups the readers share: types, families, materials and levels by the GUIDs elements hold,
//! the context a reading goes through (with room for each module's cache), and rounding.

use crate::json::{Map, Value};
use crate::project::Project;
use std::any::Any;
use std::cell::RefCell;
use std::collections::HashMap;

/// What a reading of the model goes through: the project, and what the modules worked out of it
/// once (each under a key of its own: `rooms`, `roofs`…), so reading many elements doesn't work
/// the same thing out again for each.
pub struct Ctx<'a> {
    pub pr: &'a Project,
    cache: RefCell<HashMap<&'static str, Box<dyn Any>>>,
}

impl<'a> Ctx<'a> {
    pub fn new(pr: &'a Project) -> Ctx<'a> {
        Ctx { pr, cache: RefCell::new(HashMap::new()) }
    }

    /// The value cached under `key`, worked out by `make` the first time (and cloned out: keep
    /// cached values cheap to clone, an `Rc` for anything big).
    pub fn cached<T: Any + Clone>(&self, key: &'static str, make: impl FnOnce() -> T) -> T {
        if let Some(v) = self.cache.borrow().get(key) {
            if let Some(t) = v.downcast_ref::<T>() {
                return t.clone();
            }
        }
        let v = make();
        self.cache.borrow_mut().insert(key, Box::new(v.clone()));
        v
    }
}

/// Rounds to hundredths, as the original rounds the lengths and areas it reports.
pub fn r2(x: f64) -> f64 {
    let v = (x * 100.0).round() / 100.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// Rounds to `n` decimals.
pub fn rn(x: f64, n: i32) -> f64 {
    let k = 10f64.powi(n);
    let v = (x * k).round() / k;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

pub fn num(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

pub fn text<'v>(e: &'v Value, k: &str) -> Option<&'v str> {
    e.get(k).and_then(|x| x.as_str())
}

pub fn point(e: &Value, k: &str) -> Option<[f64; 2]> {
    let a = e.get(k)?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn points(v: &Value) -> Vec<[f64; 2]> {
    v.as_arr()
        .map(|a| {
            a.iter()
                .filter_map(|p| {
                    let q = p.as_arr()?;
                    Some([q.first()?.as_f64()?, q.get(1)?.as_f64()?])
                })
                .collect()
        })
        .unwrap_or_default()
}

pub fn category(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}

// ---------------------------------------------------------------- elements and levels

/// The element a GUID names.
pub fn by_guid<'p>(pr: &'p Project, g: &str) -> Option<(u64, &'p Value)> {
    let id = pr.find_guid(g)?;
    Some((id, pr.el(id)?))
}

/// The element a field of `e` points at by GUID.
pub fn target<'p>(pr: &'p Project, e: &Value, k: &str) -> Option<(u64, &'p Value)> {
    by_guid(pr, text(e, k)?)
}

/// A level's elevation, by its GUID.
pub fn level_elev(pr: &Project, g: &str) -> Option<f64> {
    let (_, l) = by_guid(pr, g)?;
    num(l, "elevation")
}

/// The level above a level (by GUID), the next by elevation.
pub fn level_above(pr: &Project, g: &str) -> Option<u64> {
    let id = pr.find_guid(g)?;
    crate::model::level_above(pr, id)
}

// ---------------------------------------------------------------- types

/// Where a category's types are kept: their key in `types` (under `runs` for a run's), and the
/// library's kind for them.
pub fn type_home(cat: &str) -> Option<(&'static str, bool, &'static str)> {
    Some(match cat {
        "wall" => ("wall", false, "type:wall"),
        "floor" => ("floor", false, "type:floor"),
        "ceiling" => ("ceiling", false, "type:ceiling"),
        "roof" => ("roof", false, "type:roof"),
        "door" => ("door", false, "type:door"),
        "window" => ("window", false, "type:window"),
        "column" => ("column", false, "type:column"),
        "structuralcolumn" => ("structural_column", false, "type:structuralcolumn"),
        "footing" => ("footing", false, "type:footing"),
        "railing" => ("railing", false, "type:railing"),
        "beam" => ("beam", true, "type:beam"),
        "stripfooting" => ("stripfooting", true, "type:stripfooting"),
        "pipe" => ("pipe", true, "type:pipe"),
        "duct" => ("duct", true, "type:duct"),
        "conduit" => ("conduit", true, "type:conduit"),
        "cabletray" => ("cabletray", true, "type:cabletray"),
        "wire" => ("wire", true, "type:wire"),
        "downconductor" => ("downconductor", true, "type:downconductor"),
        "groundconductor" => ("groundconductor", true, "type:groundconductor"),
        "cable" => ("cable", true, "type:cable"),
        _ => return None,
    })
}

/// A category's types, by name.
pub fn types_of<'p>(pr: &'p Project, cat: &str) -> Option<&'p Map> {
    let (key, run, _) = type_home(cat)?;
    let t = pr.section("types")?;
    if run {
        t.get("runs")?.get(key)?.as_obj()
    } else {
        t.get(key)?.as_obj()
    }
}

/// The type a GUID names among a category's types: its name and its definition.
pub fn type_of<'p>(pr: &'p Project, cat: &str, g: &str) -> Option<(String, &'p Value)> {
    let (_, _, kind) = type_home(cat)?;
    let lid = pr.lib_find_guid(g)?;
    let le = pr.library.get(&lid)?;
    if text(le, "kind") != Some(kind) {
        return None;
    }
    let name = text(le, "name")?.to_string();
    let def = types_of(pr, cat)?.get(&name)?;
    Some((name, def))
}

/// The type of an element (by its `type` GUID) as its category keeps them.
pub fn element_type<'p>(pr: &'p Project, e: &Value) -> Option<(String, &'p Value)> {
    type_of(pr, category(e), text(e, "type")?)
}

// ---------------------------------------------------------------- families

/// A family by its GUID: its name and its definition.
pub fn family<'p>(pr: &'p Project, g: &str) -> Option<(String, &'p Value)> {
    let lid = pr.lib_find_guid(g)?;
    let le = pr.library.get(&lid)?;
    if text(le, "kind") != Some("family") {
        return None;
    }
    let name = text(le, "name")?.to_string();
    let def = pr.section("families")?.get(&name)?;
    Some((name, def))
}

/// The family and type names a family type's GUID names (its library entry is `Family: Type`).
pub fn family_type(pr: &Project, family_name: &str, g: &str) -> Option<String> {
    let lid = pr.lib_find_guid(g)?;
    let le = pr.library.get(&lid)?;
    if text(le, "kind") != Some("family-type") {
        return None;
    }
    let name = text(le, "name")?;
    name.strip_prefix(family_name)?.strip_prefix(": ").map(|s| s.to_string())
}

// ---------------------------------------------------------------- materials

/// A material's name, by its GUID.
pub fn material_name(pr: &Project, g: &str) -> Option<String> {
    let lid = pr.lib_find_guid(g)?;
    let le = pr.library.get(&lid)?;
    if text(le, "kind") != Some("material") {
        return None;
    }
    text(le, "name").map(|s| s.to_string())
}

/// A library entry's name by its GUID, of the kind given.
pub fn lib_name_of(pr: &Project, kind: &str, g: &str) -> Option<String> {
    let lid = pr.lib_find_guid(g)?;
    let le = pr.library.get(&lid)?;
    if text(le, "kind") != Some(kind) {
        return None;
    }
    text(le, "name").map(|s| s.to_string())
}
