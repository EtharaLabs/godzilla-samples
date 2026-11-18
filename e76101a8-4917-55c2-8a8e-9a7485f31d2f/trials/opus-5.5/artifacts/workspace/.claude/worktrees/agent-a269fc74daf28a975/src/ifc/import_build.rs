//! Building the project an IFC import makes: a new project's library and sections, the types
//! the file's elements need (named apart when they differ), and the library numbered again in
//! the order a project lists it.

use crate::json::{Map, Value};
use crate::project::Project;
use std::collections::BTreeMap;

/// A new project as an import starts it: the default library, no elements.
pub fn new_project(name: &str) -> Project {
    let mut pr = Project::new("en");
    pr.elements.clear();
    pr.doc.insert("name", Value::s(name));
    pr.doc.insert("next_id", Value::u(100000));
    pr
}

/// Rounds a length to a thousandth of a millimetre, as the import writes them (a negative zero
/// stays one).
pub fn r3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

/// Rounds to a hundredth (a roof's slope and thickness, a sill), a negative zero made zero.
pub fn r2(x: f64) -> f64 {
    let v = (x * 100.0).round() / 100.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// r3 with a negative zero made zero.
pub fn r3z(x: f64) -> f64 {
    let v = r3(x);
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// Rounds to a millionth (an angle in degrees).
pub fn r6(x: f64) -> f64 {
    let v = (x * 1e6).round() / 1e6;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// A number as a name shows it: `200`, `152.5`.
pub fn num_name(x: f64) -> String {
    let v = r3(x);
    if v == v.trunc() && v.abs() < 1e15 {
        format!("{}", v as i64)
    } else {
        format!("{}", v)
    }
}

/// A value with its `id` and `guid` keys taken out, at any depth (to compare types).
pub fn strip_ids(v: &Value) -> Value {
    match v {
        Value::Obj(m) => {
            let mut o = Map::new();
            for (k, x) in &m.items {
                if k == "id" || k == "guid" {
                    continue;
                }
                o.items.push((k.clone(), strip_ids(x)));
            }
            Value::Obj(o)
        }
        Value::Arr(a) => Value::Arr(a.iter().map(strip_ids).collect()),
        _ => v.clone(),
    }
}

pub fn is_run(cat: &str) -> bool {
    matches!(
        cat,
        "beam" | "cable" | "cabletray" | "conduit" | "downconductor" | "duct" | "groundconductor" | "pipe" | "stripfooting" | "wire"
    )
}

/// The types section of a category (`wall`, …, or a run kind under `runs`).
pub fn types_map<'a>(pr: &'a mut Project, cat: &str) -> &'a mut Map {
    let types = pr.section_mut("types");
    let (outer, inner) = if is_run(cat) { ("runs", Some(cat)) } else { (cat, None) };
    if !types.contains(outer) {
        types.insert(outer, Value::obj());
    }
    let mut m = types.get_mut(outer).unwrap().as_obj_mut().unwrap();
    if let Some(i) = inner {
        if !m.contains(i) {
            m.insert_sorted(i, Value::obj());
        }
        m = m.get_mut(i).unwrap().as_obj_mut().unwrap();
    }
    m
}

pub fn type_value<'a>(pr: &'a Project, cat: &str, name: &str) -> Option<&'a Value> {
    let types = pr.section("types")?;
    if is_run(cat) {
        types.get("runs")?.get(cat)?.get(name)
    } else {
        types.get(cat)?.get(name)
    }
}

/// Adds a type under a name, or finds the one that is the same; another with the same name and
/// other values is named `Name (2)`, `Name (3)`…. Returns the name it has.
pub fn add_type(pr: &mut Project, cat: &str, name: &str, v: Value) -> String {
    let m = types_map(pr, cat);
    let want = strip_ids(&v);
    let mut k = 1;
    loop {
        let cand = if k == 1 { name.to_string() } else { format!("{} ({})", name, k) };
        match m.get(&cand) {
            Some(x) => {
                if strip_ids(x) == want {
                    return cand;
                }
            }
            None => {
                m.insert_sorted(&cand, v);
                return cand;
            }
        }
        k += 1;
    }
}

/// The library kind of a type of a category.
pub fn type_kind(cat: &str) -> String {
    match cat {
        "structural_column" => "type:structuralcolumn".to_string(),
        _ => format!("type:{}", cat),
    }
}

/// The GUIDs library entries are to have, by (kind, name), before the library is numbered.
#[derive(Default)]
pub struct LibGuids {
    pub map: BTreeMap<(String, String), String>,
}

impl LibGuids {
    /// The GUID of an entry: the one the library has, the one given before, or a new one.
    pub fn get(&mut self, pr: &Project, kind: &str, name: &str) -> String {
        if let Some(g) = pr.lib_guid(kind, name) {
            return g;
        }
        self.map.entry((kind.to_string(), name.to_string())).or_insert_with(crate::rand::guid).clone()
    }
}

const DEFAULT_PHASES: &[&str] = &["Existing", "New Construction"];
const DEFAULT_PHASE_FILTERS: &[&str] = &["Show All", "Show Complete", "Show New", "Show Previous + Demolished", "Show Previous + New"];

/// The library's entries in the order a project lists them.
fn library_order(pr: &Project) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    let keys = |k: &str| -> Vec<String> { pr.section(k).map(|m| m.keys().cloned().collect()).unwrap_or_default() };
    if let Some(types) = pr.section("types") {
        for (cat, ts) in types.iter() {
            if cat == "runs" {
                if let Some(runs) = ts.as_obj() {
                    for (run, rts) in runs.iter() {
                        if let Some(rts) = rts.as_obj() {
                            for (name, _) in rts.iter() {
                                out.push((format!("type:{}", run), name.clone()));
                            }
                        }
                    }
                }
                continue;
            }
            if let Some(ts) = ts.as_obj() {
                for (name, _) in ts.iter() {
                    out.push((type_kind(cat), name.clone()));
                }
            }
        }
    }
    for n in keys("materials") {
        out.push(("material".into(), n));
    }
    for n in keys("images") {
        out.push(("image".into(), n));
    }
    for n in keys("families") {
        out.push(("family".into(), n));
    }
    for n in keys("parameters") {
        out.push(("parameter".into(), n));
    }
    for n in keys("view_filters") {
        out.push(("view-filter".into(), n));
    }
    for n in keys("view_templates") {
        out.push(("view-template".into(), n));
    }
    match pr.doc.get("phases").and_then(|p| p.as_arr()) {
        Some(a) => {
            for p in a {
                if let Some(s) = p.as_str() {
                    out.push(("phase".into(), s.to_string()));
                }
            }
        }
        None => {
            for p in DEFAULT_PHASES {
                out.push(("phase".into(), p.to_string()));
            }
        }
    }
    match pr.section("phase_filters") {
        Some(m) => {
            for n in m.keys() {
                out.push(("phase-filter".into(), n.clone()));
            }
        }
        None => {
            for p in DEFAULT_PHASE_FILTERS {
                out.push(("phase-filter".into(), p.to_string()));
            }
        }
    }
    if let Some(os) = pr.section("option_sets") {
        for n in os.keys() {
            out.push(("option-set".into(), n.clone()));
        }
        for (n, s) in os.iter() {
            if let Some(opts) = s.get("options").and_then(|o| o.as_arr()) {
                for o in opts {
                    if let Some(o) = o.as_str() {
                        out.push(("design-option".into(), format!("{}: {}", n, o)));
                    }
                }
            }
        }
    }
    if let Some(f) = pr.section("families") {
        for (name, fv) in f.iter() {
            if let Some(ts) = fv.get("types").and_then(|t| t.as_obj()) {
                for (t, _) in ts.iter() {
                    out.push(("family-type".into(), format!("{}: {}", name, t)));
                }
            }
        }
        for (name, fv) in f.iter() {
            if let Some(ps) = fv.get("parameters").and_then(|p| p.as_arr()) {
                for p in ps {
                    if let Some(n) = p.get("name").and_then(|n| n.as_str()) {
                        out.push(("family-parameter".into(), format!("{}: {}", name, n)));
                    }
                }
            }
        }
    }
    for (sec, kind) in [
        ("line_patterns", "line-pattern"),
        ("line_styles", "line-style"),
        ("fill_patterns", "fill-pattern"),
        ("region_types", "filled-region-type"),
        ("text_types", "text-type"),
        ("dimension_types", "dimension-type"),
        ("detail_groups", "detail-group"),
        ("voltages", "voltage"),
        ("distribution_systems", "distribution-system"),
        ("wire_types", "wire-type"),
    ] {
        for n in keys(sec) {
            out.push((kind.into(), n));
        }
    }
    out
}

/// Numbers the library again from 999999 down, in the order a project lists it, each entry
/// keeping its GUID (the library's, else the one given, else a new one); then the parts that
/// carry ids (types' layers, families' forms, symbols and connectors) after them.
pub fn renumber(pr: &mut Project, given: &LibGuids) {
    let order = library_order(pr);
    let mut lib: BTreeMap<u64, Value> = BTreeMap::new();
    let mut id = 999_999u64;
    for (kind, name) in order {
        let g = pr
            .lib_guid(&kind, &name)
            .or_else(|| given.map.get(&(kind.clone(), name.clone())).cloned())
            .unwrap_or_else(crate::rand::guid);
        lib.insert(id, crate::jobj! {"kind" => kind.as_str(), "name" => name.as_str(), "guid" => g});
        id -= 1;
    }
    pr.library = lib;
    // the parts
    let set_id = |item: &mut Value, id: &mut u64| {
        if let Value::Obj(m) = item {
            let mut n = Map::new();
            n.items.push(("id".into(), Value::u(*id)));
            if !m.contains("guid") {
                n.items.push(("guid".into(), Value::s(&crate::rand::guid())));
            }
            for (k, x) in m.items.drain(..) {
                if k == "id" {
                    continue;
                }
                n.items.push((k, x));
            }
            *m = n;
            *id -= 1;
        }
    };
    if let Some(Value::Obj(types)) = pr.doc.get_mut("types") {
        for (cat, ts) in types.items.iter_mut() {
            if cat == "runs" {
                continue;
            }
            if let Value::Obj(ts) = ts {
                for (_, t) in ts.items.iter_mut() {
                    if let Some(Value::Arr(ls)) = t.get_mut("layers") {
                        for l in ls.iter_mut() {
                            set_id(l, &mut id);
                        }
                    }
                }
            }
        }
    }
    if let Some(Value::Obj(fams)) = pr.doc.get_mut("families") {
        for (_, f) in fams.items.iter_mut() {
            for part in ["forms", "symbols", "connectors"] {
                if let Some(Value::Arr(ls)) = f.get_mut(part) {
                    for l in ls.iter_mut() {
                        set_id(l, &mut id);
                    }
                }
            }
        }
    }
    // the elements' parts: a shaped floor's or roof's points and lines
    for (_, e) in pr.elements.iter_mut() {
        if let Some(sh) = e.get_mut("shape") {
            for part in ["points", "lines"] {
                if let Some(Value::Arr(ls)) = sh.get_mut(part) {
                    for l in ls.iter_mut() {
                        set_id(l, &mut id);
                    }
                }
            }
        }
    }
    pr.lib_low = id + 1;
}
