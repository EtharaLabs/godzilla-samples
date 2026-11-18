//! Insert from File, its library: what the other project's library has that this one hasn't (by
//! GUID, then by kind and name) comes in, each entry with its GUID and a new id of this library's,
//! taken in the other library's id order; a family's types and parameters after every other
//! entry. Phases, phase filters, view templates, view filters and design options don't: what names
//! one of them is matched to this project's by name, or is left out.
//!
//! The parts of what comes in (a type's layers, a family's forms, a detail group's members, a
//! region's sketch lines) keep their ids where this project hasn't them; where it has, they are
//! given new ones, one under the lowest the project holds, in the order the file holds them.

use crate::json::{Map, Value};
use crate::project::Project;
use std::collections::{HashMap, HashSet};

/// The parts of the file a library entry of this kind lives in: the section, and within `types`
/// the category (and `runs` for the run types).
pub fn place_of(kind: &str) -> Option<(&'static str, Option<&'static str>, Option<String>)> {
    if let Some(cat) = kind.strip_prefix("type:") {
        const RUNS: &[&str] = &[
            "beam",
            "stripfooting",
            "pipe",
            "duct",
            "conduit",
            "cabletray",
            "wire",
            "downconductor",
            "groundconductor",
            "cable",
        ];
        if RUNS.contains(&cat) {
            return Some(("types", Some("runs"), Some(cat.to_string())));
        }
        let key = match cat {
            "structuralcolumn" => "structural_column".to_string(),
            c => c.to_string(),
        };
        return Some(("types", None, Some(key)));
    }
    let sec = match kind {
        "material" => "materials",
        "picture" => "images",
        "cloud" => "clouds",
        "cad" => "cads",
        "family" => "families",
        "parameter" => "parameters",
        "line-pattern" => "line_patterns",
        "line-style" => "line_styles",
        "fill-pattern" => "fill_patterns",
        "filled-region-type" => "region_types",
        "text-type" => "text_types",
        "dimension-type" => "dimension_types",
        "detail-group" => "detail_groups",
        "reinforcement-preset" => "reinforcement",
        "voltage" => "voltages",
        "distribution-system" => "distribution_systems",
        "wire-type" => "wire_types",
        _ => return None,
    };
    Some((sec, None, None))
}

/// How the reply names an entry that came in: `wall type: Exterior`, `fill pattern: Sand`.
pub fn label(kind: &str, name: &str) -> String {
    let words = if let Some(cat) = kind.strip_prefix("type:") {
        format!("{} type", cat)
    } else {
        match kind {
            "cloud" => "scan".to_string(),
            "cad" => "CAD drawing".to_string(),
            k => k.replace('-', " "),
        }
    };
    format!("{}: {}", words, name)
}

fn is_sub(kind: &str) -> bool {
    kind == "family-type" || kind == "family-parameter"
}

fn kind_of(e: &Value) -> &str {
    e.get("kind").and_then(|x| x.as_str()).unwrap_or("")
}
fn name_of(e: &Value) -> &str {
    e.get("name").and_then(|x| x.as_str()).unwrap_or("")
}
fn guid_of(e: &Value) -> &str {
    e.get("guid").and_then(|x| x.as_str()).unwrap_or("")
}

/// An entry of the other library that has no match here and can't come in: its kind and name
/// (and for a family's type or parameter, the family here and its own name in it).
#[derive(Clone, Debug)]
pub struct Unresolved {
    pub kind: String,
    pub name: String,
    pub family: Option<String>,
    pub sub: Option<String>,
}

#[derive(Default)]
pub struct LibMerge {
    /// The other library's GUIDs to this one's.
    pub gmap: HashMap<String, String>,
    pub unresolved: HashMap<String, Unresolved>,
    pub labels: Vec<String>,
    /// The entries that came in, as (kind, name), in the order they came.
    pub imported: Vec<(String, String)>,
    /// Those of them whose section entry was copied.
    pub copied: Vec<(String, String)>,
}

// ---------------------------------------------------------------- ids

/// Whether an object is a part: an id of the library's (a whole number from 900000) and a GUID.
pub fn part_id(m: &Map) -> Option<u64> {
    let id = match m.get("id") {
        Some(Value::Num(n)) => {
            let x = n.as_f64();
            if (900000.0..1_000_000.0).contains(&x) && x.fract() == 0.0 {
                x as u64
            } else {
                return None;
            }
        }
        _ => return None,
    };
    if matches!(m.get("guid"), Some(Value::Str(_))) {
        Some(id)
    } else {
        None
    }
}

pub fn collect_part_ids(v: &Value, out: &mut Vec<u64>) {
    match v {
        Value::Obj(m) => {
            if let Some(id) = part_id(m) {
                out.push(id);
            }
            for (_, x) in &m.items {
                collect_part_ids(x, out);
            }
        }
        Value::Arr(a) => a.iter().for_each(|x| collect_part_ids(x, out)),
        _ => {}
    }
}

/// The ids of the library and its parts, and the lowest of them, as new ones are handed out.
pub struct Ids {
    pub used: HashSet<u64>,
    pub low: u64,
}

impl Ids {
    /// Every id the project's library and parts hold (its elements' parts with them).
    pub fn of(pr: &Project) -> Ids {
        let mut held: Vec<u64> = pr.library.keys().cloned().collect();
        for (k, v) in &pr.doc.items {
            if k != "elements" && k != "library" {
                collect_part_ids(v, &mut held);
            }
        }
        for e in pr.elements.values() {
            collect_part_ids(e, &mut held);
        }
        let low = held.iter().cloned().min().unwrap_or(1_000_000).min(1_000_000).min(pr.lib_low);
        Ids { used: held.into_iter().collect(), low }
    }
    /// A new id, under every one handed out.
    pub fn fresh(&mut self) -> u64 {
        self.low -= 1;
        self.used.insert(self.low);
        self.low
    }
    pub fn hold(&mut self, id: u64) {
        self.used.insert(id);
        self.low = self.low.min(id);
    }
}

/// Gives the parts in `v` ids of their own where theirs are taken (and new GUIDs where `copy`),
/// in the order `v` holds them; the ids they hold count as held while new ones are found.
pub fn renumber_parts(v: &mut Value, ids: &mut Ids, copy: bool) {
    let mut own: Vec<u64> = Vec::new();
    collect_part_ids(v, &mut own);
    if let Some(m) = own.iter().cloned().min() {
        ids.low = ids.low.min(m);
    }
    walk_parts(v, ids, copy);
}

fn walk_parts(v: &mut Value, ids: &mut Ids, copy: bool) {
    match v {
        Value::Obj(m) => {
            if let Some(id) = part_id(m) {
                if ids.used.contains(&id) {
                    let nid = ids.fresh();
                    m.insert("id", Value::u(nid));
                } else {
                    ids.hold(id);
                }
                if copy {
                    m.insert("guid", Value::Str(crate::rand::guid()));
                }
            }
            for (_, x) in m.items.iter_mut() {
                walk_parts(x, ids, copy);
            }
        }
        Value::Arr(a) => a.iter_mut().for_each(|x| walk_parts(x, ids, copy)),
        _ => {}
    }
}

// ---------------------------------------------------------------- GUIDs in what is copied

/// Replaces the GUIDs a value holds (as strings, or as keys: an element's parameter values are
/// keyed by the parameter) by what `map` says; a part's own `guid` is left as it is.
pub fn remap(v: &mut Value, map: &dyn Fn(&str) -> Option<String>) {
    match v {
        Value::Str(s) => {
            if let Some(n) = map(s) {
                *s = n;
            }
        }
        Value::Arr(a) => a.iter_mut().for_each(|x| remap(x, map)),
        Value::Obj(m) => {
            for (k, x) in m.items.iter_mut() {
                if k == "guid" {
                    continue;
                }
                if let Some(n) = map(k) {
                    *k = n;
                }
                remap(x, map);
            }
        }
        _ => {}
    }
}

// ---------------------------------------------------------------- the sections

fn section_entry<'a>(pr: &'a Project, kind: &str, name: &str) -> Option<&'a Value> {
    let (sec, runs, cat) = place_of(kind)?;
    let mut m = pr.section(sec)?;
    if let Some(r) = runs {
        m = m.get(r)?.as_obj()?;
    }
    if let Some(c) = &cat {
        m = m.get(c)?.as_obj()?;
    }
    m.get(name)
}

/// The order of `types`' categories in a file.
const TYPE_ORDER: &[&str] = &[
    "wall",
    "floor",
    "door",
    "window",
    "column",
    "roof",
    "ceiling",
    "railing",
    "structural_column",
    "footing",
    "runs",
];

/// The map under `key`, made where `order` puts it (or in sorted order) if it isn't there.
fn sub_map<'a>(m: &'a mut Map, key: &str, order: Option<&[&str]>) -> &'a mut Map {
    if !m.contains(key) {
        match order {
            Some(order) => {
                let rank = |k: &str| order.iter().position(|o| *o == k).unwrap_or(usize::MAX);
                let r = rank(key);
                let pos = m.items.iter().position(|(k, _)| rank(k) > r).unwrap_or(m.items.len());
                m.items.insert(pos, (key.to_string(), Value::obj()));
            }
            None => m.insert_sorted(key, Value::obj()),
        }
    }
    let v = m.get_mut(key).unwrap();
    if !matches!(v, Value::Obj(_)) {
        *v = Value::obj();
    }
    v.as_obj_mut().unwrap()
}

/// Where an entry of this kind and name is held in its section: the section's map it is in.
fn entry_map<'a>(pr: &'a mut Project, kind: &str) -> Option<&'a mut Map> {
    let (sec, runs, cat) = place_of(kind)?;
    let mut m = pr.section_mut(sec);
    if let Some(r) = runs {
        m = sub_map(m, r, Some(TYPE_ORDER));
        if let Some(c) = &cat {
            m = sub_map(m, c, None);
        }
    } else if let Some(c) = &cat {
        m = sub_map(m, c, Some(TYPE_ORDER));
    }
    Some(m)
}

// ---------------------------------------------------------------- the merge

/// The family a family's type or parameter entry (`Family: Name`) is of, among `families`: the
/// longest family name it starts with, then `: `.
fn split_sub(name: &str, families: &[String]) -> Option<(String, String)> {
    let mut best: Option<&String> = None;
    for f in families {
        if name.len() > f.len() + 2
            && name.starts_with(f.as_str())
            && name[f.len()..].starts_with(": ")
            && best.map(|b| f.len() > b.len()).unwrap_or(true)
        {
            best = Some(f);
        }
    }
    let f = best?;
    Some((f.clone(), name[f.len() + 2..].to_string()))
}

/// Brings in what the other project's library has that this one hasn't; `ids` holds this
/// project's library and part ids, and those handed out.
pub fn merge(pr: &mut Project, src: &Project, ids: &mut Ids) -> LibMerge {
    let mut m = LibMerge::default();
    let src_families: Vec<String> = src
        .library
        .values()
        .filter(|e| kind_of(e) == "family")
        .map(|e| name_of(e).to_string())
        .collect();
    // the family each family of the other library is here (by its name here), and those that came
    let mut family_here: HashMap<String, String> = HashMap::new();
    let mut family_in: HashSet<String> = HashSet::new();
    for e in src.library.values() {
        let (kind, name, g) = (kind_of(e).to_string(), name_of(e).to_string(), guid_of(e).to_string());
        if is_sub(&kind) {
            continue;
        }
        if pr.lib_find_guid(&g).is_some() {
            if kind == "family" {
                let here = pr.lib_name(&g).unwrap_or_else(|| name.clone());
                family_here.insert(name.clone(), here);
            }
            m.gmap.insert(g.clone(), g);
            continue;
        }
        if let Some(tg) = pr.lib_guid(&kind, &name) {
            if kind == "family" {
                family_here.insert(name.clone(), name.clone());
            }
            m.gmap.insert(g, tg);
            continue;
        }
        if place_of(&kind).is_none() {
            m.unresolved.insert(g, Unresolved { kind, name, family: None, sub: None });
            continue;
        }
        let id = ids.fresh();
        pr.library.insert(id, crate::jobj! {"kind" => kind.clone(), "name" => name.clone(), "guid" => g.clone()});
        m.gmap.insert(g.clone(), g);
        m.labels.push(label(&kind, &name));
        if kind == "family" {
            family_in.insert(name.clone());
        }
        m.imported.push((kind, name));
    }
    // a family's types and parameters: with a family that came in, they come; else they are the
    // family's here of the same name
    for e in src.library.values() {
        let (kind, name, g) = (kind_of(e).to_string(), name_of(e).to_string(), guid_of(e).to_string());
        if !is_sub(&kind) {
            continue;
        }
        if pr.lib_find_guid(&g).is_some() {
            m.gmap.insert(g.clone(), g);
            continue;
        }
        let Some((fam, sub)) = split_sub(&name, &src_families) else {
            m.unresolved.insert(g, Unresolved { kind, name, family: None, sub: None });
            continue;
        };
        if family_in.contains(&fam) {
            let id = ids.fresh();
            pr.library.insert(id, crate::jobj! {"kind" => kind.clone(), "name" => name.clone(), "guid" => g.clone()});
            m.gmap.insert(g.clone(), g);
            continue;
        }
        let here = family_here.get(&fam).cloned().unwrap_or(fam.clone());
        let here_name = format!("{}: {}", here, sub);
        match pr.lib_guid(&kind, &here_name) {
            Some(tg) => {
                m.gmap.insert(g, tg);
            }
            None => {
                m.unresolved.insert(g, Unresolved { kind, name, family: Some(here), sub: Some(sub) });
            }
        }
    }
    // what came in, as the other file has it, its GUIDs made this project's
    let gmap = m.gmap.clone();
    let map = move |s: &str| gmap.get(s).filter(|t| t.as_str() != s).cloned();
    let mut copied: Vec<(String, String)> = Vec::new();
    for (kind, name) in &m.imported {
        if let Some(v) = section_entry(src, kind, name) {
            let mut v = v.clone();
            remap(&mut v, &map);
            let mut own: Vec<u64> = Vec::new();
            collect_part_ids(&v, &mut own);
            for id in own {
                ids.low = ids.low.min(id);
            }
            if let Some(em) = entry_map(pr, kind) {
                em.insert_sorted(name, v);
                copied.push((kind.clone(), name.clone()));
            }
        }
    }
    m.copied = copied;
    m
}

/// Gives the parts of the entries that came in ids of their own where theirs are taken, in the
/// order the file holds them: section by section, and in a section by name (`types` by category
/// first). Their parts keep their ids unless this project has them.
pub fn renumber_imported(pr: &mut Project, copied: &[(String, String)], ids: &mut Ids) {
    // where each one is: (section, path in it, name)
    let mut came: HashSet<(String, String, String)> = HashSet::new();
    for (kind, name) in copied {
        if let Some((sec, runs, cat)) = place_of(kind) {
            let path = match (runs, cat) {
                (Some(r), Some(c)) => format!("{}/{}", r, c),
                (None, Some(c)) => c,
                _ => String::new(),
            };
            came.insert((sec.to_string(), path, name.clone()));
        }
    }
    let secs: Vec<String> = pr.doc.items.iter().map(|(k, _)| k.clone()).collect();
    for sec in secs {
        if sec == "elements" || sec == "library" {
            continue;
        }
        let mut entries: Vec<(String, String)> = Vec::new();
        if let Some(Value::Obj(m)) = pr.doc.get(&sec) {
            if sec == "types" {
                for (c, ts) in m.iter() {
                    let Some(ts) = ts.as_obj() else { continue };
                    if c == "runs" {
                        for (rc, rts) in ts.iter() {
                            if let Some(rts) = rts.as_obj() {
                                for (n, _) in rts.iter() {
                                    entries.push((format!("runs/{}", rc), n.clone()));
                                }
                            }
                        }
                    } else {
                        for (n, _) in ts.iter() {
                            entries.push((c.clone(), n.clone()));
                        }
                    }
                }
            } else {
                for (n, _) in m.iter() {
                    entries.push((String::new(), n.clone()));
                }
            }
        }
        for (path, name) in entries {
            if !came.contains(&(sec.clone(), path.clone(), name.clone())) {
                continue;
            }
            let Some(slot) = entry_at(pr, &sec, &path, &name) else { continue };
            let mut v = std::mem::take(slot);
            walk_parts(&mut v, ids, false);
            if let Some(slot) = entry_at(pr, &sec, &path, &name) {
                *slot = v;
            }
        }
    }
}

fn entry_at<'a>(pr: &'a mut Project, sec: &str, path: &str, name: &str) -> Option<&'a mut Value> {
    let mut m = pr.doc.get_mut(sec)?.as_obj_mut()?;
    if !path.is_empty() {
        for part in path.split('/') {
            m = m.get_mut(part)?.as_obj_mut()?;
        }
    }
    m.get_mut(name)
}
