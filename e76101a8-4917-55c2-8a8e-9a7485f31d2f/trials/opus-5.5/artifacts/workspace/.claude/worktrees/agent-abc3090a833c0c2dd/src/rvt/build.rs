//! Building the BIMCraft project an import makes: a new project's library and sections, the
//! types the file's elements need (named apart when they differ), and the library registered.

use crate::json::{Map, Value};
use crate::project::Project;

/// A new project as an import starts it: the default library, no elements.
pub fn new_project(name: &str) -> Project {
    let mut pr = Project::new("en");
    pr.elements.clear();
    pr.doc.insert("name", Value::s(name));
    pr.doc.insert("next_id", Value::u(100000));
    pr
}

/// Rounds a length to a thousandth of a millimetre, as the import writes them.
pub fn r3(x: f64) -> f64 {
    let v = (x * 1000.0).round() / 1000.0;
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

/// Feet to millimetres, rounded.
pub fn mm(ft: f64) -> f64 {
    r3(ft * 304.8)
}

/// A value with its `id` and `guid` keys taken out, at any depth (to compare types).
fn strip_ids(v: &Value) -> Value {
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

/// The types section of a category (`wall`, …, or a run kind under `runs`).
fn types_map<'a>(pr: &'a mut Project, cat: &str) -> &'a mut Map {
    let types = pr.section_mut("types");
    let (outer, inner) = match cat {
        "pipe" | "duct" | "cabletray" | "conduit" | "cable" | "beam" | "wire" => ("runs", Some(cat)),
        _ => (cat, None),
    };
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

/// Adds a type under a name unless one has it already (a run's type is known by its name).
pub fn add_type_once(pr: &mut Project, cat: &str, name: &str, v: Value) -> String {
    let m = types_map(pr, cat);
    if !m.contains(name) {
        m.insert_sorted(name, v);
    }
    name.to_string()
}

pub fn type_value<'a>(pr: &'a Project, cat: &str, name: &str) -> Option<&'a Value> {
    let types = pr.section("types")?;
    match cat {
        "pipe" | "duct" | "cabletray" | "conduit" | "cable" | "beam" | "wire" => types.get("runs")?.get(cat)?.get(name),
        _ => types.get(cat)?.get(name),
    }
}

/// The library kind of a type of a category.
pub fn type_kind(cat: &str) -> String {
    match cat {
        "structural_column" => "type:structuralcolumn".to_string(),
        _ => format!("type:{}", cat),
    }
}

/// The GUID a material has in the library, by its name.
pub fn material_guid(pr: &Project, name: &str) -> Option<String> {
    pr.lib_guid("material", name)
}

/// Registers in the library what the sections hold and it has not (types, families, their types
/// and parameters), then gives the new layers and forms their ids.
pub fn sync_library(pr: &mut Project, made: &std::collections::BTreeMap<(String, String), String>) {
    let mut add: Vec<(String, String)> = Vec::new();
    if let Some(types) = pr.section("types") {
        for (cat, ts) in types.iter() {
            if cat == "runs" {
                if let Some(runs) = ts.as_obj() {
                    for (run, rts) in runs.iter() {
                        if let Some(rts) = rts.as_obj() {
                            for (name, _) in rts.iter() {
                                add.push((format!("type:{}", run), name.clone()));
                            }
                        }
                    }
                }
                continue;
            }
            if let Some(ts) = ts.as_obj() {
                for (name, _) in ts.iter() {
                    add.push((type_kind(cat), name.clone()));
                }
            }
        }
    }
    let mut fam_names: Vec<String> = Vec::new();
    let mut fam_types: Vec<String> = Vec::new();
    let mut fam_params: Vec<String> = Vec::new();
    if let Some(f) = pr.section("families") {
        for (name, fv) in f.iter() {
            fam_names.push(name.clone());
            if let Some(ts) = fv.get("types").and_then(|t| t.as_obj()) {
                for (t, _) in ts.iter() {
                    fam_types.push(format!("{}: {}", name, t));
                }
            }
            if let Some(ps) = fv.get("parameters").and_then(|p| p.as_arr()) {
                for p in ps {
                    if let Some(n) = p.get("name").and_then(|n| n.as_str()) {
                        fam_params.push(format!("{}: {}", name, n));
                    }
                }
            }
        }
    }
    for n in fam_names {
        add.push(("family".into(), n));
    }
    for n in fam_types {
        add.push(("family-type".into(), n));
    }
    for n in fam_params {
        add.push(("family-parameter".into(), n));
    }
    for (kind, name) in add {
        if pr.lib_find(&kind, &name).is_none() {
            let id = pr.alloc_lib_id();
            let g = made.get(&(kind.clone(), name.clone())).cloned().unwrap_or_else(crate::rand::guid);
            pr.library.insert(id, crate::jobj! {"kind" => kind.as_str(), "name" => name.as_str(), "guid" => g});
        }
    }
    // ids for the parts that have none: layers of types, forms of families
    let mut paths: Vec<(String, Vec<String>, usize)> = Vec::new();
    if let Some(types) = pr.section("types") {
        for (cat, ts) in types.iter() {
            if cat == "runs" {
                continue;
            }
            if let Some(ts) = ts.as_obj() {
                for (name, t) in ts.iter() {
                    if let Some(ls) = t.get("layers").and_then(|l| l.as_arr()) {
                        for (i, l) in ls.iter().enumerate() {
                            if l.get("id").is_none() {
                                paths.push(("types".into(), vec![cat.clone(), name.clone(), "layers".into()], i));
                            }
                        }
                    }
                }
            }
        }
    }
    if let Some(f) = pr.section("families") {
        for (name, fv) in f.iter() {
            if let Some(fs) = fv.get("forms").and_then(|l| l.as_arr()) {
                for (i, l) in fs.iter().enumerate() {
                    if l.get("id").is_none() {
                        paths.push(("families".into(), vec![name.clone(), "forms".into()], i));
                    }
                }
            }
        }
    }
    for (sec, path, i) in paths {
        let id = pr.alloc_lib_id();
        let mut v: &mut Value = pr.doc.get_mut(&sec).unwrap();
        for k in &path {
            v = v.get_mut(k).unwrap();
        }
        let item = &mut v.as_arr_mut().unwrap()[i];
        // the id goes first, as the core writes a part
        if let Value::Obj(m) = item {
            let mut n = Map::new();
            n.items.push(("id".into(), Value::u(id)));
            for (k, x) in m.items.drain(..) {
                n.items.push((k, x));
            }
            *m = n;
        }
    }
}
