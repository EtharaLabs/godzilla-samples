//! The library once a file is read: one entry for each thing the model holds that the library
//! names (its types, materials, families and their types and parameters, styles…), the file's own
//! where it has one (its id and GUID kept), a new one where it hasn't (an id below every id the
//! file's library and its parts hold, a new GUID), and none for what the model doesn't hold.

use super::de::R;
use crate::json::{Map, Value};
use std::collections::{BTreeMap, HashMap, HashSet};

/// How the original names a kind of library entry in "two … are named".
pub fn plural(kind: &str) -> String {
    if let Some(c) = kind.strip_prefix("type:") {
        return format!("{} types", c);
    }
    match kind {
        "cloud" => "scans".into(),
        "cad" => "CAD drawings".into(),
        "option-set" => "design option sets".into(),
        "filled-region-type" => "filled region types".into(),
        _ => format!("{}s", kind.replace('-', " ")),
    }
}

/// The library's own rules: no two entries with one GUID, nor two of a kind with one name.
pub fn check(library: &BTreeMap<u64, Value>) -> R<()> {
    let mut guids: HashMap<String, u64> = HashMap::new();
    let mut names: HashSet<(String, String)> = HashSet::new();
    for (id, e) in library {
        if let Some(Value::Num(_)) = e.get("guid") {
            return Err(format!("library entry {}: its GUID is a number", id));
        }
        let s = |k: &str| e.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
        let (kind, name, guid) = (s("kind"), s("name"), s("guid"));
        if let Some(first) = guids.get(&guid) {
            return Err(format!("library entries {} and {} have the same GUID {}", first, id, guid));
        }
        guids.insert(guid, *id);
        if !names.insert((kind.clone(), name.clone())) {
            return Err(format!("two {} are named `{}` in the library", plural(&kind), name));
        }
    }
    Ok(())
}

fn keys(doc: &Map, k: &str) -> Vec<String> {
    doc.get(k).and_then(|v| v.as_obj()).map(|m| m.keys().cloned().collect()).unwrap_or_default()
}

/// What the model holds that the library names, in the order the original makes their entries.
pub fn wanted(doc: &Map) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    let push = |kind: &str, names: Vec<String>, out: &mut Vec<(String, String)>| {
        for n in names {
            out.push((kind.to_string(), n));
        }
    };
    if let Some(Value::Obj(types)) = doc.get("types") {
        for (sec, kind) in [
            ("wall", "type:wall"),
            ("floor", "type:floor"),
            ("door", "type:door"),
            ("window", "type:window"),
            ("column", "type:column"),
            ("roof", "type:roof"),
            ("ceiling", "type:ceiling"),
            ("railing", "type:railing"),
            ("structural_column", "type:structuralcolumn"),
            ("footing", "type:footing"),
        ] {
            let names: Vec<String> = types.get(sec).and_then(|v| v.as_obj()).map(|m| m.keys().cloned().collect()).unwrap_or_default();
            push(kind, names, &mut out);
        }
        if let Some(Value::Obj(runs)) = types.get("runs") {
            for (cat, m) in &runs.items {
                let names: Vec<String> = m.as_obj().map(|m| m.keys().cloned().collect()).unwrap_or_default();
                push(&format!("type:{}", cat), names, &mut out);
            }
        }
    }
    push("material", keys(doc, "materials"), &mut out);
    push("picture", keys(doc, "images"), &mut out);
    push("cloud", keys(doc, "clouds"), &mut out);
    push("cad", keys(doc, "cads"), &mut out);
    push("family", keys(doc, "families"), &mut out);
    push("parameter", keys(doc, "parameters"), &mut out);
    push("view-filter", keys(doc, "view_filters"), &mut out);
    push("view-template", keys(doc, "view_templates"), &mut out);
    let phases: Vec<String> = match doc.get("phases").and_then(|v| v.as_arr()) {
        Some(a) => a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect(),
        None => crate::styles::phasing::DEFAULT_PHASES.iter().map(|s| s.to_string()).collect(),
    };
    push("phase", phases, &mut out);
    let filters: Vec<String> = match doc.get("phase_filters").and_then(|v| v.as_obj()) {
        Some(m) => m.keys().cloned().collect(),
        None => ["Show All", "Show Complete", "Show New", "Show Previous + Demolished", "Show Previous + New"]
            .iter()
            .map(|s| s.to_string())
            .collect(),
    };
    push("phase-filter", filters, &mut out);
    push("option-set", keys(doc, "option_sets"), &mut out);
    let mut options = Vec::new();
    if let Some(Value::Obj(sets)) = doc.get("option_sets") {
        for (set, v) in &sets.items {
            if let Some(Value::Arr(a)) = v.get("options") {
                for o in a {
                    if let Some(o) = o.as_str() {
                        options.push(format!("{}: {}", set, o));
                    }
                }
            }
        }
    }
    push("design-option", options, &mut out);
    let mut ftypes = Vec::new();
    let mut fparams = Vec::new();
    if let Some(Value::Obj(fams)) = doc.get("families") {
        for (fam, f) in &fams.items {
            if let Some(Value::Obj(ts)) = f.get("types") {
                for t in ts.keys() {
                    ftypes.push(format!("{}: {}", fam, t));
                }
            }
            if let Some(Value::Arr(ps)) = f.get("parameters") {
                for p in ps {
                    if let Some(n) = p.get("name").and_then(|x| x.as_str()) {
                        fparams.push(format!("{}: {}", fam, n));
                    }
                }
            }
        }
    }
    push("family-type", ftypes, &mut out);
    push("family-parameter", fparams, &mut out);
    push("line-pattern", keys(doc, "line_patterns"), &mut out);
    push("line-style", keys(doc, "line_styles"), &mut out);
    push("fill-pattern", keys(doc, "fill_patterns"), &mut out);
    push("filled-region-type", keys(doc, "region_types"), &mut out);
    push("detail-group", keys(doc, "detail_groups"), &mut out);
    push("text-type", keys(doc, "text_types"), &mut out);
    push("reinforcement-preset", keys(doc, "reinforcement"), &mut out);
    push("dimension-type", keys(doc, "dimension_types"), &mut out);
    push("voltage", keys(doc, "voltages"), &mut out);
    push("distribution-system", keys(doc, "distribution_systems"), &mut out);
    push("wire-type", keys(doc, "wire_types"), &mut out);
    out
}

/// The library's entries for what the model doesn't hold, gone.
pub fn drop_stale(library: &mut BTreeMap<u64, Value>, doc: &Map) {
    let set: HashSet<(String, String)> = wanted(doc).into_iter().collect();
    library.retain(|_, e| {
        let s = |k: &str| e.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
        set.contains(&(s("kind"), s("name")))
    });
}

/// An entry for each thing the model holds that the library hasn't, made in the original's order.
pub fn add_missing(library: &mut BTreeMap<u64, Value>, doc: &Map, alloc: &mut super::ids::Alloc) {
    let want = wanted(doc);
    let mut have: HashSet<(String, String)> = HashSet::new();
    for (_, e) in library.iter() {
        let s = |k: &str| e.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
        have.insert((s("kind"), s("name")));
    }
    for (kind, name) in want {
        if have.contains(&(kind.clone(), name.clone())) {
            continue;
        }
        let id = alloc.lib();
        library.insert(id, jobj! {"kind" => kind.as_str(), "name" => name.as_str(), "guid" => crate::rand::guid()});
        have.insert((kind, name));
    }
}
