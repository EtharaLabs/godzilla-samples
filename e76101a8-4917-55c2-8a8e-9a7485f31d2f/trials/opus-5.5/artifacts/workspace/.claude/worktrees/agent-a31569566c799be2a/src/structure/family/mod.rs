//! `family`: the project's families, created, changed, read, listed, loaded and saved; their
//! model rules and what `inspect` warns of.
//!
//! A family (the file's `families`, by name in name order) is parameters, types that set them,
//! forms, plan symbols and connectors (`model`). The file holds materials by GUID, the original's
//! memory (and every reply) by name. Its library entries are `family`, `family-type`
//! ("Family: Type") and `family-parameter` ("Family: Parameter"), and its forms, symbols and
//! connectors are parts with an id and a GUID of their own (`ids`). The `family` command
//! (`cmd`) reads its parts as serde does (`de`), works every type out (`eval`, `geom`) and holds
//! the family to its rules (`check`).
//!
//! What the original does after a change, `put_family` does: the library entries a new family,
//! type or parameter needs (the family's, then its types' in name order, then its parameters'
//! in their order, ids counting down from the lowest the project has seen), the entries of the
//! types and parameters it no longer has taken away, then its parts' ids and GUIDs: kept where
//! nothing else in the project has them, fresh ones (forms, then symbols, then connectors) where
//! they're missing or taken. A part given without an id or a GUID where `forms`, `symbols` or
//! `connectors` replace a list takes those of the part in its place before.
//!
//! For other areas:
//! - Reading: [`family_of`] (the family as the original holds it, materials by name),
//!   [`name_of_guid`], [`type_guid`], [`type_name_of_guid`], [`param_guid`],
//!   [`param_name_of_guid`] (an element's `family`, `type` and `params` keys are these GUIDs;
//!   `component::held` reads an element of a family, component or opening, into names).
//! - Working a type out: [`type_values`] (each parameter's value, an element's own values by
//!   name over its type's, a hosted family's `Wall Thickness`: 200 when none), [`opening_size`]
//!   (a door's or window's width, height and default sill), [`pieces_of`] (its forms as solids in
//!   its own axes, voids cut, each with its material's name: for IFC and the views),
//!   [`marks_of`] (its plan symbols), [`connectors_of`] (what a device draws).
//! - Changing: [`put_family`] / [`put_family_value`] / [`put_family_value_with`] (a family into
//!   the project as a command leaves it: what loading a favorite needs), [`rename_family`],
//!   [`remove_family`], [`rename_family_type`], [`remove_family_type`].
//! - `inspect`: [`inspect_view`] (its `families`) and [`warnings`] (its `warnings` of families).
//! - The formulas themselves are `crate::structure::formula`.

pub mod check;
mod cmd;
pub mod de;
pub mod eval;
pub mod geom;
pub mod ids;
pub mod model;

pub use check::{ConnectorValues, Piece};
pub use eval::{Eval, PVal};
pub use model::Family;

use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::R;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "family" => cmd::run(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// A material's name as a family names it: one the library has.
pub fn has_material(pr: &Project, name: &str) -> bool {
    pr.lib_find("material", name).is_some() || pr.section("materials").map(|m| m.contains(name)).unwrap_or(false)
}

/// The name of the material with this GUID (anything else as it is).
fn material_name(pr: &Project, s: &str) -> String {
    if let Some(id) = pr.lib_find_guid(s) {
        if let Some(e) = pr.library.get(&id) {
            if e.get("kind").and_then(|k| k.as_str()) == Some("material") {
                if let Some(n) = e.get("name").and_then(|n| n.as_str()) {
                    return n.to_string();
                }
            }
        }
    }
    s.to_string()
}

/// Whether the project has a family of this name.
pub fn exists(pr: &Project, name: &str) -> bool {
    pr.section("families").map(|f| f.contains(name)).unwrap_or(false)
}

/// A family of the project, as the original holds it (materials by name).
pub fn family_of(pr: &Project, name: &str) -> Option<Family> {
    let v = pr.section("families")?.get(name)?;
    Some(model::from_file(v, &|s: &str| material_name(pr, s)))
}

/// A family as `family` shows it.
pub fn view_of(pr: &Project, name: &str) -> Option<Value> {
    family_of(pr, name).map(|f| f.view())
}

/// The name of the family with this GUID (an element's `family`).
pub fn name_of_guid(pr: &Project, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(ids::FAMILY) {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

/// The family-type GUID of a family's type (what an element's `type` holds).
pub fn type_guid(pr: &Project, family: &str, ty: &str) -> Option<String> {
    pr.lib_guid(ids::FAMILY_TYPE, &ids::entry_name(family, ty))
}

/// The type name a family-type GUID names, for a family.
pub fn type_name_of_guid(pr: &Project, family: &str, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(ids::FAMILY_TYPE) {
        return None;
    }
    let n = e.get("name").and_then(|n| n.as_str())?;
    n.strip_prefix(&format!("{}: ", family)).map(|s| s.to_string())
}

/// The family-parameter GUID of a family's parameter (what an element's `params` keys it by).
pub fn param_guid(pr: &Project, family: &str, param: &str) -> Option<String> {
    pr.lib_guid(ids::FAMILY_PARAMETER, &ids::entry_name(family, param))
}

/// The parameter name a family-parameter GUID names, for a family.
pub fn param_name_of_guid(pr: &Project, family: &str, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(ids::FAMILY_PARAMETER) {
        return None;
    }
    let n = e.get("name").and_then(|n| n.as_str())?;
    n.strip_prefix(&format!("{}: ", family)).map(|s| s.to_string())
}

/// Remembers the lowest id the library and the parts hold, so that none is handed out again
/// once what has it goes (the original counts down from the lowest it has seen).
fn remember_lowest(pr: &mut Project) {
    pr.lib_low = ids::lowest(pr);
}

/// Puts a family into the project under `name` (over one of that name), as the original leaves
/// it after a command: its library entries made where it has none (the family's, its types' in
/// name order, its parameters' in their order) and taken away for the types and parameters it no
/// longer has; its forms', symbols' and connectors' ids and GUIDs kept where nothing else in the
/// project has them, fresh ones (counting down) where they're missing or taken.
pub fn put_family(pr: &mut Project, name: &str, fam: &Family) {
    let old = family_of(pr, name);
    put_over(pr, name, fam, old);
}

fn put_over(pr: &mut Project, name: &str, fam: &Family, old: Option<Family>) {
    remember_lowest(pr);
    let file = {
        let p: &Project = pr;
        fam.to_file(&|m: &str| p.lib_guid("material", m))
    };
    crate::structure::types::put_sorted(pr.section_mut("families"), name, file);
    ids::ensure_entry(pr, ids::FAMILY, name);
    for (t, _) in &fam.types {
        ids::ensure_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(name, t));
    }
    for p in &fam.parameters {
        ids::ensure_entry(pr, ids::FAMILY_PARAMETER, &ids::entry_name(name, &p.name));
    }
    if let Some(o) = old {
        for (t, _) in &o.types {
            if fam.type_values(t).is_none() {
                ids::remove_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(name, t));
            }
        }
        for p in &o.parameters {
            if fam.param(&p.name).is_none() {
                ids::remove_entry(pr, ids::FAMILY_PARAMETER, &ids::entry_name(name, &p.name));
            }
        }
    }
    ids::fix_parts(pr, name);
}

/// Puts a family given as a project file holds it (materials by GUID or by name) into the
/// project, as [`put_family`] does: what loading a favorite family needs (its parts get fresh
/// ids, counting down, where the project has theirs, and fresh GUIDs where it has those).
pub fn put_family_value(pr: &mut Project, name: &str, file: &Value) {
    let fam = model::from_file(file, &|s: &str| material_name(pr, s));
    put_family(pr, name, &fam);
}

/// [`put_family_value`] for a family that brings materials (a favorite): `load_materials` puts
/// them in the project once the family's parts hold their ids there, so that their library
/// entries count down from below those ids, as the original gives every entry after the
/// command (materials first, then the family's).
pub fn put_family_value_with(
    pr: &mut Project,
    name: &str,
    file: &Value,
    load_materials: &mut dyn FnMut(&mut Project) -> Result<(), String>,
) -> Result<(), String> {
    let old = family_of(pr, name);
    let before = pr.section("families").and_then(|f| f.get(name)).cloned();
    crate::structure::types::put_sorted(pr.section_mut("families"), name, file.clone());
    if let Err(e) = load_materials(pr) {
        match before {
            Some(v) => crate::structure::types::put_sorted(pr.section_mut("families"), name, v),
            None => {
                pr.section_mut("families").remove(name);
            }
        }
        return Err(e);
    }
    let fam = model::from_file(file, &|s: &str| material_name(pr, s));
    put_over(pr, name, &fam, old);
    Ok(())
}

/// Renames a family: it moves in the file, its library entries follow (keeping their GUIDs).
pub fn rename_family(pr: &mut Project, from: &str, to: &str) {
    let Some(f) = family_of(pr, from) else { return };
    let fams = pr.section_mut("families");
    let v = fams.remove(from).unwrap_or(Value::Null);
    crate::structure::types::put_sorted(fams, to, v);
    ids::rename_entry(pr, ids::FAMILY, from, to);
    for (t, _) in &f.types {
        ids::rename_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(from, t), &ids::entry_name(to, t));
    }
    for p in &f.parameters {
        ids::rename_entry(pr, ids::FAMILY_PARAMETER, &ids::entry_name(from, &p.name), &ids::entry_name(to, &p.name));
    }
}

/// Renames one of a family's types: it moves in the family's `types` (name order) and its
/// `family-type` library entry follows, keeping its GUID, so what's of it follows too. Nothing
/// is checked here (that the family has `from` and not `to`).
pub fn rename_family_type(pr: &mut Project, family: &str, from: &str, to: &str) {
    let Some(mut f) = family_of(pr, family) else { return };
    let Some(vals) = f.type_values(from).cloned() else { return };
    f.remove_type(from);
    f.set_type(to, vals);
    ids::rename_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(family, from), &ids::entry_name(family, to));
    let file = {
        let p: &Project = pr;
        f.to_file(&|m: &str| p.lib_guid("material", m))
    };
    crate::structure::types::put_sorted(pr.section_mut("families"), family, file);
}

/// Takes one of a family's types away with its `family-type` library entry. Nothing is checked
/// here (that it isn't the last, that nothing is of it).
pub fn remove_family_type(pr: &mut Project, family: &str, ty: &str) {
    remember_lowest(pr);
    let Some(mut f) = family_of(pr, family) else { return };
    if f.type_values(ty).is_none() {
        return;
    }
    f.remove_type(ty);
    ids::remove_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(family, ty));
    let file = {
        let p: &Project = pr;
        f.to_file(&|m: &str| p.lib_guid("material", m))
    };
    crate::structure::types::put_sorted(pr.section_mut("families"), family, file);
}

/// Takes a family away with its library entries.
pub fn remove_family(pr: &mut Project, name: &str) {
    remember_lowest(pr);
    let Some(f) = family_of(pr, name) else { return };
    pr.section_mut("families").remove(name);
    ids::remove_entry(pr, ids::FAMILY, name);
    for (t, _) in &f.types {
        ids::remove_entry(pr, ids::FAMILY_TYPE, &ids::entry_name(name, t));
    }
    for p in &f.parameters {
        ids::remove_entry(pr, ids::FAMILY_PARAMETER, &ids::entry_name(name, &p.name));
    }
}

/// A project file's `families` read as the original's loader reads them: its serde error where
/// one can't be (what `open` says after "<path> is not a BIMCraft project: "). For the loader.
pub fn check_file_families(v: &Value) -> R<()> {
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
            keys.sort_by(|a, b| a.0.cmp(&b.0));
            for (_, f) in keys {
                de::check_file_family(f)?;
            }
            Ok(())
        }
        _ => Err(de::invalid(v, "a map")),
    }
}

/// The model rules of this part, checked after every command (and by the original on opening a
/// file): every family, in name order, held to its rules; the first refusal.
pub fn check(pr: &Project) -> R<()> {
    let Some(fams) = pr.section("families") else { return Ok(()) };
    let mut names: Vec<&String> = fams.keys().collect();
    names.sort();
    let mut entries: std::collections::HashSet<(bool, String)> = std::collections::HashSet::new();
    let mut twice = false;
    for n in names {
        let f = model::from_file(fams.get(n).unwrap(), &|s: &str| material_name(pr, s));
        check::rules(&f, &|_m: &str| true).map_err(|e| format!("family `{}`: {}", n, e))?;
        // two families' types or parameters can't be one library entry ("A: B: C")
        for (t, _) in &f.types {
            twice |= !entries.insert((true, ids::entry_name(n, t)));
        }
        let mut own: Vec<&str> = Vec::new();
        for p in &f.parameters {
            if own.contains(&p.name.as_str()) {
                continue;
            }
            own.push(&p.name);
            twice |= !entries.insert((false, ids::entry_name(n, &p.name)));
        }
    }
    if twice {
        return Err("the library's ids and GUIDs are not those of what it has".into());
    }
    Ok(())
}

/// The components of each family, by family name (for the warnings).
fn placed(pr: &Project) -> Vec<(String, usize)> {
    let mut out: Vec<(String, usize)> = Vec::new();
    for e in pr.elements.values() {
        if e.get("category").and_then(|c| c.as_str()) != Some("component") {
            continue;
        }
        let Some(g) = e.get("family").and_then(|f| f.as_str()) else { continue };
        let Some(n) = name_of_guid(pr, g) else { continue };
        match out.iter_mut().find(|(m, _)| *m == n) {
            Some((_, c)) => *c += 1,
            None => out.push((n, 1)),
        }
    }
    out.sort();
    out
}

/// What `inspect` warns of: each lighting, outlet or switch family in use that has forms and
/// holds no connector, so its devices count as zero load.
pub fn warnings(pr: &Project) -> Vec<String> {
    let mut out = Vec::new();
    for (n, count) in placed(pr) {
        let Some(f) = family_of(pr, &n) else { continue };
        if !matches!(f.category.as_str(), "lighting" | "outlet" | "switch") || !f.connectors.is_empty() || f.forms.is_empty() {
            continue;
        }
        let what = if count == 1 { "device counts" } else { "devices count" };
        out.push(format!(
            "family `{}` has no connector, so its {} placed {} as a load of zero: give it one with `family` `connectors`",
            n, count, what
        ));
    }
    out
}

/// The project's families as `inspect` shows them: {name: {category, connectors: [{kind,
/// system}], parameters: [names], types: [names]}}.
pub fn inspect_view(pr: &Project) -> Value {
    let mut out = Map::new();
    let Some(fams) = pr.section("families") else { return Value::Obj(out) };
    for (n, _) in fams.iter() {
        let Some(f) = family_of(pr, n) else { continue };
        let conns: Vec<Value> =
            f.connectors.iter().map(|c| crate::jobj! {"kind" => c.kind.name(), "system" => c.system.name()}).collect();
        out.insert_sorted(
            n,
            crate::jobj! {
                "category" => f.category.as_str(),
                "connectors" => Value::Arr(conns),
                "parameters" => Value::Arr(f.parameters.iter().map(|p| Value::s(&p.name)).collect()),
                "types" => Value::Arr(f.type_names().into_iter().map(Value::Str).collect()),
            },
        );
    }
    Value::Obj(out)
}

/// A family's type worked out, its parameters' values in their order (a hosted family's `Wall
/// Thickness` last): `instance` are a component's (or an opening's) own values by parameter name
/// over the type's, `wall` a hosted family's wall thickness (200 when none). None when the project
/// has no such family or type.
pub fn type_values(
    pr: &Project,
    family: &str,
    ty: &str,
    instance: Option<&Map>,
    wall: Option<f64>,
) -> Option<Result<Vec<(String, PVal)>, String>> {
    let f = family_of(pr, family)?;
    f.type_values(ty)?;
    let ev = Eval::new(&f, Some(ty), instance, wall);
    Some(ev.values())
}

/// A door's or window's family type's opening: (width, height, the sill a window takes by
/// default: its `Sill Height`, 0 when it has none).
pub fn opening_size(pr: &Project, family: &str, ty: &str, instance: Option<&Map>) -> Option<(f64, f64, f64)> {
    let vals = type_values(pr, family, ty, instance, None)?.ok()?;
    let get = |n: &str| vals.iter().find(|(k, _)| k == n).map(|(_, v)| v.num());
    Some((get("Width").unwrap_or(0.0), get("Height").unwrap_or(0.0), get("Sill Height").unwrap_or(0.0)))
}

/// A family's forms worked out for a type (and an instance's values), in its own axes, the voids
/// cut out of the solid forms listed before them: each solid with its material's name.
pub fn pieces_of(pr: &Project, family: &str, ty: &str, instance: Option<&Map>, wall: Option<f64>) -> Vec<Piece> {
    let Some(f) = family_of(pr, family) else { return Vec::new() };
    let ev = Eval::new(&f, Some(ty), instance, wall);
    check::cut(&check::pieces(&f, &ev))
}

/// The plan symbols of a family's type (and an instance's values) worked out, in its own axes:
/// what a plan draws besides its forms (a door's swing…).
pub fn marks_of(pr: &Project, family: &str, ty: &str, instance: Option<&Map>, wall: Option<f64>) -> Vec<check::Mark> {
    let Some(f) = family_of(pr, family) else { return Vec::new() };
    let ev = Eval::new(&f, Some(ty), instance, wall);
    check::marks(&f, &ev)
}

/// A family's connectors worked out for a type (and an instance's values).
pub fn connectors_of(pr: &Project, family: &str, ty: &str, instance: Option<&Map>) -> Vec<(model::Connector, ConnectorValues)> {
    let Some(f) = family_of(pr, family) else { return Vec::new() };
    let ev = Eval::new(&f, Some(ty), instance, None);
    f.connectors
        .iter()
        .filter_map(|c| check::connector_values(c, &ev).ok().map(|v| (c.clone(), v)))
        .collect()
}

#[cfg(test)]
mod tests {
    use crate::json::Value;

    fn load(path: &str) -> crate::project::Project {
        let v = crate::json::parse(&std::fs::read_to_string(path).unwrap()).unwrap();
        crate::load::load(v).unwrap()
    }

    /// Writes what `inspect` shows of the families of the project at $FAM_IN (`families` and the
    /// `warnings`) to $FAM_OUT, to compare with the original's.
    #[test]
    #[ignore]
    fn inspect_dump() {
        let pr = load(&std::env::var("FAM_IN").unwrap());
        let w: Vec<Value> = super::warnings(&pr).into_iter().map(Value::Str).collect();
        let v = crate::jobj! {"families" => super::inspect_view(&pr), "warnings" => Value::Arr(w)};
        std::fs::write(std::env::var("FAM_OUT").unwrap(), v.sorted().to_compact()).unwrap();
    }

    /// Writes the model's first refusal for the project at $FAM_IN to $FAM_OUT ("ok" for none).
    #[test]
    #[ignore]
    fn check_dump() {
        let path = std::env::var("FAM_IN").unwrap();
        let v = crate::json::parse(&std::fs::read_to_string(&path).unwrap()).unwrap();
        if let Some(f) = v.get("families") {
            if let Err(e) = super::check_file_families(f) {
                std::fs::write(std::env::var("FAM_OUT").unwrap(), format!("is not a BIMCraft project: {}", e)).unwrap();
                return;
            }
        }
        let pr = load(&path);
        let r = match crate::check::check(&pr) {
            Ok(()) => "ok".to_string(),
            Err(e) => e,
        };
        std::fs::write(std::env::var("FAM_OUT").unwrap(), r).unwrap();
    }

    /// Loads favorite family $FAV_NAME from the favorites at $FAV_PATH into the project at
    /// $FAM_IN as `favorite load` does it with `put_family_value` (as $FAV_AS), and writes the
    /// project to $FAM_OUT.
    #[test]
    #[ignore]
    fn favorite_load() {
        let mut pr = load(&std::env::var("FAM_IN").unwrap());
        let favs = crate::media::favorite::read(&std::env::var("FAV_PATH").unwrap()).unwrap();
        let name = std::env::var("FAV_NAME").unwrap();
        let target = std::env::var("FAV_AS").unwrap_or_else(|_| name.clone());
        let e = favs.families.iter().find(|(n, _)| *n == name).map(|(_, e)| e.clone()).unwrap();
        super::put_family_value_with(&mut pr, &target, &e.family, &mut |pr| {
            for (mname, me) in &e.materials {
                if !super::has_material(pr, mname) {
                    crate::media::favorite::load_material(pr, mname, me)?;
                }
            }
            Ok(())
        })
        .unwrap();
        std::fs::write(std::env::var("FAM_OUT").unwrap(), pr.to_file_string()).unwrap();
    }

    /// Writes the forms of each component of the project at $FAM_IN as `local_pieces` works them
    /// out (per component, per piece, its triangles) to $FAM_OUT, to compare with the original's
    /// IFC.
    #[test]
    #[ignore]
    fn pieces_dump() {
        let pr = load(&std::env::var("FAM_IN").unwrap());
        let point = |v: &[f64; 3]| Value::Arr(v.iter().map(|c| Value::from(*c)).collect());
        let mut out = Vec::new();
        for id in pr.ids_of("component") {
            let pieces = crate::structure::component::local_pieces(&pr, id)
                .into_iter()
                .map(|p| Value::Arr(p.triangles.iter().map(|t| Value::Arr(t.iter().map(point).collect())).collect()))
                .collect();
            out.push(Value::Arr(pieces));
        }
        std::fs::write(std::env::var("FAM_OUT").unwrap(), Value::Arr(out).to_compact()).unwrap();
    }
}
