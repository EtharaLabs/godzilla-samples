//! What Purge Unused, Delete Type, Rename Type and Match Properties share: the types of a
//! category as the original finds them from a category's name, families and their types, what
//! uses them, and the original's long errors.

use crate::json::{Map, Value};
use crate::project::Project;

/// The longest error the original gives whole; past it, the rest is counted.
const MAX_ERROR: usize = 2000;

/// Marks an error the original's model check gives (after the command), which isn't clipped.
const CHECK: char = '\u{1}';

/// An error as the original's model check gives it after the command: said whole.
pub fn check_error(e: String) -> String {
    format!("{}{}", CHECK, e)
}

/// A command's error past 2000 characters: its first 2000 and how many more there were (what the
/// model's check finds is said whole).
pub fn clip_error(e: String) -> String {
    if let Some(rest) = e.strip_prefix(CHECK) {
        return rest.to_string();
    }
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

/// A category as the type commands read one: its ASCII letters and digits, lowercased, without
/// the s's it ends in (`Structural Columns`, `structural_column` and `structuralcolumn` are one),
/// but for the categories whose plural isn't an s more (masses, switches, pipe accessories).
pub fn norm_category(s: &str) -> String {
    let t: String = s.chars().filter(|c| c.is_ascii_alphanumeric()).collect::<String>().to_ascii_lowercase();
    match t.as_str() {
        "mass" | "masses" => "mass".to_string(),
        "switches" => "switch".to_string(),
        "pipeaccessories" => "pipeaccessory".to_string(),
        _ => t.trim_end_matches('s').to_string(),
    }
}

/// Where a category's types are kept.
#[derive(Clone, Debug, PartialEq)]
pub enum Loc {
    /// `types` under this key (`wall`, `structural_column`…).
    Types(String),
    /// `types.runs` under this key (`beam`, `pipe`…).
    Runs(String),
    /// A section of drafting types (`text_types`, `dimension_types`, `region_types`).
    Styles(&'static str),
}

/// The categories of `types` (and `types.runs`) by their keys: (normalised name, where).
pub fn type_categories(pr: &Project) -> Vec<(String, Loc)> {
    let mut out = Vec::new();
    if let Some(types) = pr.section("types") {
        for (k, v) in types.iter() {
            if k == "runs" {
                continue;
            }
            if v.as_obj().is_some() {
                out.push((norm_category(k), Loc::Types(k.clone())));
            }
        }
        if let Some(runs) = types.get("runs").and_then(|r| r.as_obj()) {
            for (k, v) in runs.iter() {
                if v.as_obj().is_some() {
                    out.push((norm_category(k), Loc::Runs(k.clone())));
                }
            }
        }
    }
    out
}

/// Where the types of a (normalised) category are; with `styles`, text, dimension and filled
/// region types too.
pub fn locate(pr: &Project, cat: &str, styles: bool) -> Option<Loc> {
    if let Some((_, loc)) = type_categories(pr).into_iter().find(|(n, _)| n == cat) {
        return Some(loc);
    }
    if !styles {
        return None;
    }
    match cat {
        "text" => Some(Loc::Styles("text_types")),
        "dimension" => Some(Loc::Styles("dimension_types")),
        "region" => Some(Loc::Styles("region_types")),
        _ => None,
    }
}

/// The types kept there.
pub fn loc_map<'a>(pr: &'a Project, loc: &Loc) -> Option<&'a Map> {
    match loc {
        Loc::Types(k) => pr.section("types")?.get(k)?.as_obj(),
        Loc::Runs(k) => pr.section("types")?.get("runs")?.get(k)?.as_obj(),
        Loc::Styles(s) => pr.section(s),
    }
}

pub fn loc_map_mut<'a>(pr: &'a mut Project, loc: &Loc) -> Option<&'a mut Map> {
    match loc {
        Loc::Types(k) => pr.get_mut("types")?.get_mut(k)?.as_obj_mut(),
        Loc::Runs(k) => pr.get_mut("types")?.get_mut("runs")?.get_mut(k)?.as_obj_mut(),
        Loc::Styles(s) => pr.get_mut(s)?.as_obj_mut(),
    }
}

/// Their names, sorted.
pub fn loc_names(pr: &Project, loc: &Loc) -> Vec<String> {
    let mut v: Vec<String> = loc_map(pr, loc).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// The starter project's type of a (normalised) category, which a new element of it takes while
/// the project has it (and Purge Unused keeps when nothing uses any of the category's types).
pub fn preferred_type(cat: &str) -> Option<&'static str> {
    Some(match cat {
        "wall" => "Generic - 200mm",
        "floor" => "Generic - 200mm",
        "door" => "Single 900 x 2100",
        "window" => "Fixed 1200 x 1500",
        "column" => "Rectangular 400 x 400",
        "roof" => "Generic - 300mm",
        "ceiling" => "Generic - 20mm",
        "railing" => "Railing - 1000mm",
        "structuralcolumn" => "Concrete 300 x 300",
        "footing" => "Footing 1200 x 1200",
        "beam" => "Beam 200 x 500",
        "stripfooting" => "Strip 600 x 300",
        "pipe" => "PVC 50",
        "duct" => "Rectangular 400 x 300",
        "conduit" => "PVC 25",
        "cabletray" => "Perforated 100 x 50",
        "wire" => "Wire 2.5",
        "downconductor" => "Steel 8",
        "groundconductor" => "Copper 9",
        "cable" => "Cat6",
        _ => return None,
    })
}

/// The type a new element of a category (`wall`, `structural_column`, `beam`…, as typed) takes
/// without one: the starter's while the project has it, else the first by name.
pub fn default_type(pr: &Project, category: &str) -> Option<String> {
    let cat = norm_category(category);
    let names = loc_names(pr, &locate(pr, &cat, false)?);
    if let Some(p) = preferred_type(&cat) {
        if names.iter().any(|n| n == p) {
            return Some(p.to_string());
        }
    }
    names.first().cloned()
}

/// The library kind of a (normalised) category's types: `type:wall`, `type:structuralcolumn`.
pub fn type_kind(cat: &str) -> String {
    format!("type:{}", cat)
}

/// What an error lists of what there is: " (there are: a, b)", nothing when there is none.
pub fn there_are(names: &[String]) -> String {
    if names.is_empty() {
        String::new()
    } else {
        format!(" (there are: {})", names.join(", "))
    }
}

/// "1 time", "4 times".
pub fn times(n: usize) -> String {
    if n == 1 {
        "1 time".to_string()
    } else {
        format!("{} times", n)
    }
}

/// How many elements have this as their `type`.
pub fn uses_as_type(pr: &Project, guid: Option<&str>) -> usize {
    let Some(g) = guid else { return 0 };
    pr.elements.values().filter(|e| e.get("type").and_then(|t| t.as_str()) == Some(g)).count()
}

/// How many elements are of this family.
pub fn uses_as_family(pr: &Project, guid: Option<&str>) -> usize {
    let Some(g) = guid else { return 0 };
    pr.elements.values().filter(|e| e.get("family").and_then(|t| t.as_str()) == Some(g)).count()
}

// ---------------------------------------------------------------- families

pub fn families(pr: &Project) -> Option<&Map> {
    pr.section("families")
}

/// The project's families' names, sorted.
pub fn family_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = families(pr).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// A family's types' names, sorted.
pub fn family_type_names(fam: &Value) -> Vec<String> {
    let mut v: Vec<String> = fam.get("types").and_then(|t| t.as_obj()).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// A family's parameters' names, in order.
pub fn family_param_names(fam: &Value) -> Vec<String> {
    fam.get("parameters")
        .and_then(|a| a.as_arr())
        .map(|a| a.iter().filter_map(|x| x.get("name").and_then(|n| n.as_str()).map(|n| n.to_string())).collect())
        .unwrap_or_default()
}

/// How the library names one of a family's types or parameters: `Bed: 900 x 2000`.
pub fn qualified(family: &str, name: &str) -> String {
    format!("{}: {}", family, name)
}

/// Takes the library entry of this kind and name away.
pub fn lib_remove(pr: &mut Project, kind: &str, name: &str) {
    if let Some(id) = pr.lib_find(kind, name) {
        pr.library.remove(&id);
    }
}

/// Renames the library entry of this kind and name.
pub fn lib_rename(pr: &mut Project, kind: &str, from: &str, to: &str) {
    if let Some(id) = pr.lib_find(kind, from) {
        if let Some(e) = pr.library.get_mut(&id) {
            e.set("name", Value::s(to));
        }
    }
}

/// Takes a family away, and its library entries with it: its own, its types' and its
/// parameters'.
pub fn remove_family(pr: &mut Project, name: &str) {
    let Some(fam) = families(pr).and_then(|m| m.get(name)).cloned() else { return };
    for t in family_type_names(&fam) {
        lib_remove(pr, "family-type", &qualified(name, &t));
    }
    for p in family_param_names(&fam) {
        lib_remove(pr, "family-parameter", &qualified(name, &p));
    }
    lib_remove(pr, "family", name);
    if let Some(m) = pr.get_mut("families").and_then(|v| v.as_obj_mut()) {
        m.remove(name);
    }
}

/// Takes one of a family's types away, and its library entry.
pub fn remove_family_type(pr: &mut Project, family: &str, t: &str) {
    if let Some(types) = pr
        .get_mut("families")
        .and_then(|v| v.get_mut(family))
        .and_then(|f| f.get_mut("types"))
        .and_then(|t| t.as_obj_mut())
    {
        types.remove(t);
    }
    lib_remove(pr, "family-type", &qualified(family, t));
}

/// A key of a map renamed in place, the map kept in sorted order.
pub fn rename_key_sorted(m: &mut Map, from: &str, to: &str) {
    if let Some(v) = m.remove(from) {
        m.insert_sorted(to, v);
    }
}

/// A name that reads as a GUID (8-4-4-4-12 hex digits, braces or not, any case).
pub fn is_guid_name(s: &str) -> bool {
    crate::styles::electrical::as_guid(s).is_some()
}

// ---------------------------------------------------------------- elements named

/// One element a command names, as `common::resolve` reads it, but for a GUID that is no
/// element's: a library entry's is refused by its name (`"Generic - 200mm" is not an element id
/// or GUID`), any other is `no element <guid>`, as the original says.
pub fn resolve_element(pr: &Project, cmd: &str, v: &Value) -> Result<u64, String> {
    if let Value::Str(s) = v {
        let t = s.trim();
        if t.parse::<u64>().is_err() {
            if let Some(g) = super::common::strict_guid(t) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
                if let Some(e) = pr.library.values().find(|e| e.get("guid").and_then(|x| x.as_str()) == Some(g.as_str())) {
                    let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("");
                    return Err(format!("{}: {} is not an element id or GUID", cmd, Value::s(name).to_compact()));
                }
                return Err(format!("{}: no element {}", cmd, g));
            }
        }
    }
    super::common::resolve(pr, cmd, v)
}

/// The elements a command names in `ids` (or, without it, `id`), each once, in the order named.
pub fn element_ids(pr: &Project, cmd: &str, p: &Value) -> Result<Vec<u64>, String> {
    let list: Vec<Value> = match p.get("ids") {
        Some(Value::Null) | None => match p.get("id") {
            None => return Err(format!("{}: `ids` [id, …] is required", cmd)),
            Some(v) => vec![v.clone()],
        },
        Some(Value::Arr(a)) => a.clone(),
        Some(_) => return Err(format!("{}: `ids` [id, …] is required", cmd)),
    };
    let mut out: Vec<u64> = Vec::new();
    for v in &list {
        let id = resolve_element(pr, cmd, v)?;
        if !out.contains(&id) {
            out.push(id);
        }
    }
    Ok(out)
}
