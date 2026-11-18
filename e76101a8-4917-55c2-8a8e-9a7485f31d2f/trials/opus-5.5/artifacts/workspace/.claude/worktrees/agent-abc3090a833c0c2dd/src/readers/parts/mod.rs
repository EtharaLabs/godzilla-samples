//! Doors, windows, components (and their families' parameters worked out), columns, footings,
//! beams and runs, rebar, stairs, ramps and railings as `elements` shows them.
//!
//! `formula` is the family formula language; `family` works a family's parameters out for an
//! element (`family_values`, which schedules read too), a component's height and connectors;
//! `openings` places doors and windows on their walls; `columns`, `runs`, `rebar` and `stairs`
//! (stairs, ramps and the railings along them) the rest.

pub mod family;
pub mod formula;
mod columns;
mod openings;
mod rebar;
mod runs;
mod stairs;

pub use family::family_values;

use crate::json::{Map, Value};
use crate::readers::common::{self, Ctx};
use std::collections::HashMap;
use std::rc::Rc;

/// Adds the derived values of a door, window, component, column, footing, beam, run, rebar,
/// stair, ramp or railing to its view `x`.
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let cat = common::category(x).to_string();
    match cat.as_str() {
        "door" | "window" => openings::view(cx, id, x),
        "component" => family::component_view(cx, id, x),
        "column" | "structuralcolumn" | "footing" => columns::view(cx, x),
        "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" => runs::view(cx, x),
        "rebar" => rebar::view(x),
        "stair" => stairs::stair_view(cx, x),
        "ramp" => stairs::ramp_view(cx, x),
        "railing" => stairs::railing_view(cx, x),
        _ => {}
    }
    params_view(cx, id, x);
}

// ---------------------------------------------------------------- lookups by GUID

/// The project's elements and library entries by GUID, made once a reading.
pub(crate) struct Index {
    el: HashMap<String, u64>,
    lib: HashMap<String, u64>,
}

pub(crate) fn index(cx: &Ctx) -> Rc<Index> {
    cx.cached("parts.index", || {
        let pr = cx.pr;
        let mut el = HashMap::new();
        for (id, e) in &pr.elements {
            if let Some(g) = common::text(e, "guid") {
                el.entry(g.to_string()).or_insert(*id);
            }
        }
        let mut lib = HashMap::new();
        for (id, e) in &pr.library {
            if let Some(g) = common::text(e, "guid") {
                lib.entry(g.to_string()).or_insert(*id);
            }
        }
        Rc::new(Index { el, lib })
    })
}

/// The element a GUID names.
pub(crate) fn el_by_guid<'p>(cx: &Ctx<'p>, g: &str) -> Option<(u64, &'p Value)> {
    let id = *index(cx).el.get(g)?;
    Some((id, cx.pr.el(id)?))
}

/// The element a field of `e` names by GUID.
pub(crate) fn target<'p>(cx: &Ctx<'p>, e: &Value, k: &str) -> Option<(u64, &'p Value)> {
    el_by_guid(cx, common::text(e, k)?)
}

/// The library entry a GUID names (`{kind, name, guid}`).
pub(crate) fn lib_entry<'p>(cx: &Ctx<'p>, g: &str) -> Option<&'p Value> {
    let id = *index(cx).lib.get(g)?;
    cx.pr.library.get(&id)
}

/// The name of the library entry of kind `kind` a GUID names.
pub(crate) fn lib_name<'p>(cx: &Ctx<'p>, kind: &str, g: &str) -> Option<&'p str> {
    let le = lib_entry(cx, g)?;
    if common::text(le, "kind") != Some(kind) {
        return None;
    }
    common::text(le, "name")
}

/// A level's elevation, by its GUID.
pub(crate) fn level_elev(cx: &Ctx, g: &str) -> Option<f64> {
    let (_, l) = el_by_guid(cx, g)?;
    common::num(l, "elevation")
}

/// The elevation of the level a field of `e` names.
pub(crate) fn elev_of(cx: &Ctx, e: &Value, k: &str) -> Option<f64> {
    level_elev(cx, common::text(e, k)?)
}

/// The type of `e` (its `type` GUID) among its category's types: its name and definition.
pub(crate) fn element_type<'p>(cx: &Ctx<'p>, e: &Value) -> Option<(String, &'p Value)> {
    let cat = common::category(e);
    let (_, _, kind) = common::type_home(cat)?;
    let name = lib_name(cx, kind, common::text(e, "type")?)?;
    let def = common::types_of(cx.pr, cat)?.get(name)?;
    Some((name.to_string(), def))
}

/// Replaces a project type's GUID in `type` by its name, keeping the GUID in `type_guid`; the
/// type's definition back.
pub(crate) fn name_type<'p>(cx: &Ctx<'p>, x: &mut Value) -> Option<&'p Value> {
    let (name, def) = element_type(cx, x)?;
    let g = common::text(x, "type").unwrap_or("").to_string();
    x.set("type", Value::Str(name));
    x.set("type_guid", Value::Str(g));
    Some(def)
}

/// A family by its GUID: its name and its definition.
pub(crate) fn family_of<'p>(cx: &Ctx<'p>, g: &str) -> Option<(&'p str, &'p Value)> {
    let name = lib_name(cx, "family", g)?;
    let def = cx.pr.section("families")?.get(name)?;
    Some((name, def))
}

/// The name of one of a family's types, by the type's GUID (its library entry is `Family: Type`).
pub(crate) fn family_type_name<'p>(cx: &Ctx<'p>, family: &str, g: &str) -> Option<&'p str> {
    let name = lib_name(cx, "family-type", g)?;
    name.strip_prefix(family)?.strip_prefix(": ")
}

/// A material's name, by its GUID.
pub(crate) fn material_name<'p>(cx: &Ctx<'p>, g: &str) -> Option<&'p str> {
    lib_name(cx, "material", g)
}

/// Rounds to thousandths, as the original rounds the points of stairs, ramps and railings.
pub(crate) fn r3(x: f64) -> f64 {
    common::rn(x, 3)
}

pub(crate) fn pt(v: [f64; 2]) -> Value {
    Value::Arr(vec![Value::f(v[0]), Value::f(v[1])])
}

// ---------------------------------------------------------------- parameters

/// An element's `params` as `elements` shows them: by the names of the project parameters and of
/// its family's parameters their GUIDs name, a family's material parameter's value by its
/// material's name.
fn params_view(cx: &Ctx, id: u64, x: &mut Value) {
    let pr = cx.pr;
    let stored = match pr.el(id).and_then(|e| e.get("params")).and_then(|p| p.as_obj()) {
        Some(m) => m,
        None => return,
    };
    let fam = pr.el(id).and_then(|e| common::text(e, "family")).and_then(|g| family_of(cx, g));
    let mut out = Map::new();
    for (k, v) in stored.iter() {
        let (name, material) = match lib_entry(cx, k) {
            Some(le) => match common::text(le, "kind") {
                Some("parameter") => (common::text(le, "name").unwrap_or(k).to_string(), false),
                Some("family-parameter") => {
                    let full = common::text(le, "name").unwrap_or(k);
                    let name = match fam {
                        Some((fname, _)) => full
                            .strip_prefix(fname)
                            .and_then(|s| s.strip_prefix(": "))
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| full.to_string()),
                        None => full.split_once(": ").map(|(_, b)| b.to_string()).unwrap_or_else(|| full.to_string()),
                    };
                    let material = fam
                        .map(|(_, def)| family::param_kind(def, &name) == Some("material"))
                        .unwrap_or(false);
                    (name, material)
                }
                _ => (k.clone(), false),
            },
            None => (k.clone(), false),
        };
        let v = if material {
            match v.as_str().and_then(|g| material_name(cx, g)) {
                Some(n) => Value::s(n),
                None => v.clone(),
            }
        } else {
            v.clone()
        };
        out.insert(&name, v);
    }
    x.set("params", Value::Obj(out));
}
