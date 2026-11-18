//! Insert from File, its elements: those named (all without `ids`) and what they point at that
//! this project hasn't, in the other project's id order. A level pointed at is this project's
//! (the one of its GUID, else the one of its name) where it has one. Each element keeps its id
//! unless this project has it, and its GUID unless this project has it (a copy, its parts with
//! GUIDs of their own too); what they point at among themselves follows them. A level's or a
//! view's name, a grid's name and a sheet's number taken here gets ` 2`, ` 3`…

use super::insert_lib::{remap, renumber_parts, Ids, LibMerge, Unresolved};
use crate::json::Value;
use crate::project::Project;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

pub struct Placed {
    pub ids: BTreeMap<u64, u64>,
    pub copies: Vec<u64>,
    pub left_out: Vec<String>,
}

/// The categories whose names are a view's (a level's plan among them): one name each among them.
const VIEWS: &[&str] = &["level", "section", "elevation", "schedule", "view3d", "planview"];

/// The schedules every project has (of its rooms, doors, windows, walls, floors and levels), by
/// the project's language: their names are taken whether or not the project holds them yet.
fn default_schedules(lang: &str) -> &'static [&'static str] {
    match lang {
        "pt" => &["Tabela de ambientes", "Tabela de portas", "Tabela de janelas", "Tabela de paredes", "Tabela de pisos", "Tabela de níveis"],
        "es" => &["Tabla de habitaciones", "Tabla de puertas", "Tabla de ventanas", "Tabla de muros", "Tabla de pisos", "Tabla de niveles"],
        "de" => &["Raumtabelle", "Türtabelle", "Fenstertabelle", "Wandtabelle", "Bodentabelle", "Geschosstabelle"],
        "fr" => &[
            "Nomenclature des pièces",
            "Nomenclature des portes",
            "Nomenclature des fenêtres",
            "Nomenclature des murs",
            "Nomenclature des sols",
            "Nomenclature des niveaux",
        ],
        "sv" => &["Rumsförteckning", "Dörrförteckning", "Fönsterförteckning", "Väggförteckning", "Bjälklagsförteckning", "Nivåförteckning"],
        "cs" => &["Výkaz místností", "Výkaz dveří", "Výkaz oken", "Výkaz stěn", "Výkaz podlah", "Výkaz podlaží"],
        "nl" => &["Ruimtelijst", "Deurenlijst", "Ramenlijst", "Murenlijst", "Vloerenlijst", "Niveaulijst"],
        "it" => &["Abaco zone", "Abaco porte", "Abaco finestre", "Abaco muri", "Abaco solai", "Abaco piani"],
        _ => &["Room Schedule", "Door Schedule", "Window Schedule", "Wall Schedule", "Floor Schedule", "Level Schedule"],
    }
}

fn cat(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}
fn guid(e: &Value) -> &str {
    e.get("guid").and_then(|c| c.as_str()).unwrap_or("")
}
fn text<'a>(e: &'a Value, k: &str) -> &'a str {
    e.get(k).and_then(|c| c.as_str()).unwrap_or("")
}

/// The other project's elements an element points at, by their GUIDs (its own and its parts'
/// left aside).
fn refs(v: &Value, by_guid: &HashMap<&str, u64>, out: &mut Vec<u64>) {
    match v {
        Value::Str(s) => {
            if let Some(id) = by_guid.get(s.as_str()) {
                out.push(*id);
            }
        }
        Value::Arr(a) => a.iter().for_each(|x| refs(x, by_guid, out)),
        Value::Obj(m) => {
            for (k, x) in &m.items {
                if k == "guid" {
                    continue;
                }
                if let Some(id) = by_guid.get(k.as_str()) {
                    out.push(*id);
                }
                refs(x, by_guid, out);
            }
        }
        _ => {}
    }
}

/// A name with ` 2`, ` 3`… where it is taken.
fn free_name(name: &str, taken: &dyn Fn(&str) -> bool) -> String {
    if !taken(name) {
        return name.to_string();
    }
    let mut n = 2u64;
    loop {
        let cand = format!("{} {}", name, n);
        if !taken(&cand) {
            return cand;
        }
        n += 1;
    }
}

/// The names (or numbers) of this project's elements of these categories under `field`.
fn names_of(pr: &Project, cats: &[&str], field: &str) -> Vec<String> {
    pr.elements
        .values()
        .filter(|e| cats.contains(&cat(e)))
        .filter_map(|e| e.get(field).and_then(|x| x.as_str()).map(|s| s.to_string()))
        .collect()
}

fn lib_names(pr: &Project, kind: &str) -> Vec<String> {
    let mut v: Vec<String> = pr
        .library
        .values()
        .filter(|e| e.get("kind").and_then(|x| x.as_str()) == Some(kind))
        .filter_map(|e| e.get("name").and_then(|x| x.as_str()).map(|s| s.to_string()))
        .collect();
    v.sort();
    v
}

/// The project's phases in order: as its file lists them, or (a file that doesn't) its library's,
/// first made first.
fn phase_names(pr: &Project) -> Vec<String> {
    if let Some(a) = pr.get("phases").and_then(|p| p.as_arr()) {
        return a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect();
    }
    pr.library
        .iter()
        .rev()
        .filter(|(_, e)| e.get("kind").and_then(|x| x.as_str()) == Some("phase"))
        .filter_map(|(_, e)| e.get("name").and_then(|x| x.as_str()).map(|s| s.to_string()))
        .collect()
}

/// What the model's check says of a view that names a phase, a phase filter, a view template, a
/// view filter or a design option set this project hasn't.
fn graphics_error(pr: &Project, c: &str, id: u64, g: &Value, un: &HashMap<String, Unresolved>) -> Option<String> {
    let name_if = |v: Option<&Value>, kind: &str| -> Option<String> {
        let s = v?.as_str()?;
        let u = un.get(s)?;
        if u.kind == kind {
            Some(u.name.clone())
        } else {
            None
        }
    };
    if let Some(n) = name_if(g.get("template"), "view-template") {
        return Some(format!(
            "{} {}: there's no view template `{}` (there are: {})",
            c,
            id,
            n,
            lib_names(pr, "view-template").join(", ")
        ));
    }
    if let Some(n) = name_if(g.get("phase"), "phase") {
        return Some(format!("{} {}: there's no phase `{}` (there are: {})", c, id, n, phase_names(pr).join(", ")));
    }
    if let Some(n) = name_if(g.get("phase_filter"), "phase-filter") {
        return Some(format!(
            "{} {}: there's no phase filter `{}` (there are: {})",
            c,
            id,
            n,
            lib_names(pr, "phase-filter").join(", ")
        ));
    }
    if let Some(fs) = g.get("filters").and_then(|f| f.as_arr()) {
        for f in fs {
            if let Some(n) = name_if(f.get("filter"), "view-filter") {
                return Some(format!("{} {}: there's no view filter `{}`", c, id, n));
            }
        }
    }
    if let Some(Value::Obj(o)) = g.get("options") {
        for (k, v) in o.iter() {
            if let Some(u) = un.get(k) {
                if u.kind == "option-set" {
                    return Some(format!("{} {}: there's no design option set `{}`", c, id, u.name));
                }
            }
            // the set is here, its option isn't
            let Some(u) = v.as_str().and_then(|s| un.get(s)) else { continue };
            if u.kind != "design-option" {
                continue;
            }
            let set = pr.lib_name(k).unwrap_or_default();
            let option = u.name.strip_prefix(&format!("{}: ", set)).unwrap_or(&u.name).to_string();
            let options: Vec<String> = pr
                .section("option_sets")
                .and_then(|m| m.get(&set))
                .and_then(|s| s.get("options"))
                .and_then(|a| a.as_arr())
                .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            return Some(format!(
                "{} {}: design option set `{}` has no option `{}` (there are: {})",
                c,
                id,
                set,
                option,
                options.join(", ")
            ));
        }
    }
    None
}

/// The built-in parameters that name a phase or a design option, in the order they are told.
const PHASE_PARAMS: &[(&str, &str, &str)] = &[
    ("Phase Created", "phase", "a phase"),
    ("Phase Demolished", "phase", "a phase"),
    ("Design Option", "design-option", "a design option"),
];

/// The elements that come: those named and what they point at that this project hasn't; and the
/// levels pointed at that are this project's (by their ids there), with their GUIDs here.
pub struct Selection {
    pub set: BTreeSet<u64>,
    pub level_here: HashMap<u64, String>,
}

impl Selection {
    /// The lowest part id the elements that come hold.
    pub fn lowest_part(&self, src: &Project) -> Option<u64> {
        let mut held = Vec::new();
        for id in &self.set {
            super::insert_lib::collect_part_ids(&src.elements[id], &mut held);
        }
        held.into_iter().min()
    }
}

pub fn select(pr: &Project, src: &Project, named: Option<Vec<u64>>) -> Selection {
    let by_guid: HashMap<&str, u64> = src.elements.iter().map(|(id, e)| (guid(e), *id)).collect();
    let here_guids: HashSet<String> = pr.elements.values().map(|e| guid(e).to_string()).collect();
    // this project's levels by name, the first of each name
    let mut level_named: HashMap<String, String> = HashMap::new();
    for e in pr.elements.values() {
        if cat(e) == "level" {
            level_named.entry(text(e, "name").to_string()).or_insert_with(|| guid(e).to_string());
        }
    }
    let mut set: BTreeSet<u64> = match named {
        Some(v) => v.into_iter().collect(),
        None => src.elements.keys().cloned().collect(),
    };
    // what they point at: this project's where it has it, else it comes too
    let mut level_here: HashMap<u64, String> = HashMap::new();
    let mut queue: Vec<u64> = set.iter().cloned().collect();
    while let Some(id) = queue.pop() {
        let mut rs = Vec::new();
        refs(&src.elements[&id], &by_guid, &mut rs);
        for r in rs {
            if set.contains(&r) || level_here.contains_key(&r) {
                continue;
            }
            let re = &src.elements[&r];
            let g = guid(re);
            if here_guids.contains(g) {
                if cat(re) == "level" {
                    level_here.insert(r, g.to_string());
                }
                continue;
            }
            if cat(re) == "level" {
                if let Some(h) = level_named.get(text(re, "name")) {
                    level_here.insert(r, h.clone());
                    continue;
                }
            }
            set.insert(r);
            queue.push(r);
        }
    }
    Selection { set, level_here }
}

/// Brings the elements in.
pub fn place(pr: &mut Project, src: &Project, sel: Selection, lib: &LibMerge, ids: &mut Ids) -> Result<Placed, String> {
    let Selection { set, level_here } = sel;
    let here_guids: HashSet<String> = pr.elements.values().map(|e| guid(e).to_string()).collect();
    // ids and GUIDs
    let mut emap: HashMap<String, String> = HashMap::new();
    let mut idmap: BTreeMap<u64, u64> = BTreeMap::new();
    let mut copies: Vec<u64> = Vec::new();
    let mut is_copy: HashMap<u64, bool> = HashMap::new();
    for &sid in &set {
        let e = &src.elements[&sid];
        let tid = if pr.elements.contains_key(&sid) {
            pr.alloc_id()
        } else {
            if pr.next_id() <= sid {
                pr.doc.insert("next_id", Value::u(sid + 1));
            }
            sid
        };
        // held for it, so no other takes it
        pr.elements.insert(tid, Value::Null);
        let g = guid(e).to_string();
        let copy = here_guids.contains(&g);
        let ng = if copy { crate::rand::guid() } else { g.clone() };
        emap.insert(g, ng);
        idmap.insert(sid, tid);
        is_copy.insert(sid, copy);
        if copy {
            copies.push(tid);
        }
    }
    for (r, h) in &level_here {
        emap.insert(guid(&src.elements[r]).to_string(), h.clone());
    }
    let map = |s: &str| -> Option<String> {
        if let Some(n) = emap.get(s) {
            return if n != s { Some(n.clone()) } else { None };
        }
        if let Some(n) = lib.gmap.get(s) {
            return if n != s { Some(n.clone()) } else { None };
        }
        None
    };
    let mut left_out: Vec<String> = Vec::new();
    let mut error: Option<String> = None;
    for &sid in &set {
        let tid = idmap[&sid];
        let mut e = src.elements[&sid].clone();
        let c = cat(&e).to_string();
        let g = emap[guid(&e)].clone();
        e.set("guid", Value::Str(g.clone()));
        remap(&mut e, &map);
        renumber_parts(&mut e, ids, is_copy[&sid]);
        // the parameters naming a phase or an option this project hasn't are left out
        if let Some(Value::Obj(ps)) = e.get_mut("params") {
            for (key, kind, words) in PHASE_PARAMS {
                let Some(v) = ps.get(key).and_then(|v| v.as_str()).map(|s| s.to_string()) else { continue };
                if let Some(u) = lib.unresolved.get(&v) {
                    if u.kind == *kind {
                        left_out.push(format!("element {}: `{}` {} isn't {} of this project", tid, key, u.name, words));
                        ps.remove(key);
                    }
                }
            }
            if ps.is_empty() {
                if let Value::Obj(m) = &mut e {
                    m.remove("params");
                }
            }
        }
        if error.is_none() {
            error = element_error(pr, &c, tid, &e, &lib.unresolved);
        }
        // names and numbers taken here
        match c.as_str() {
            "level" | "section" | "elevation" | "schedule" | "view3d" => {
                if let Some(n) = e.get("name").and_then(|x| x.as_str()).map(|s| s.to_string()) {
                    let mut taken = names_of(pr, VIEWS, "name");
                    taken.extend(default_schedules(&pr.language()).iter().map(|s| s.to_string()));
                    let nn = free_name(&n, &|x| taken.iter().any(|t| t == x));
                    if nn != n {
                        e.set("name", Value::Str(nn));
                    }
                }
            }
            "grid" => {
                if let Some(n) = e.get("name").and_then(|x| x.as_str()).map(|s| s.to_string()) {
                    let taken = names_of(pr, &["grid"], "name");
                    let nn = free_name(&n, &|x| taken.iter().any(|t| t == x));
                    if nn != n {
                        e.set("name", Value::Str(nn));
                    }
                }
            }
            "sheet" => {
                if let Some(n) = e.get("number").and_then(|x| x.as_str()).map(|s| s.to_string()) {
                    let taken = names_of(pr, &["sheet"], "number");
                    let nn = free_name(&n, &|x| taken.iter().any(|t| t == x));
                    if nn != n {
                        e.set("number", Value::Str(nn));
                    }
                }
            }
            _ => {}
        }
        pr.elements.insert(tid, e);
    }
    if let Some(err) = error {
        return Err(err);
    }
    Ok(Placed { ids: idmap, copies, left_out })
}

/// What the model's check says of an element that names what this project hasn't and can't take
/// in: a family's type or parameter its family here lacks, a view's phase or template.
fn element_error(pr: &Project, c: &str, id: u64, e: &Value, un: &HashMap<String, Unresolved>) -> Option<String> {
    if let Some(g) = e.get("graphics") {
        if let Some(err) = graphics_error(pr, c, id, g, un) {
            return Some(err);
        }
    }
    if let Some(t) = e.get("type").and_then(|t| t.as_str()) {
        if let Some(u) = un.get(t) {
            if u.kind == "family-type" {
                let fam = u.family.clone().unwrap_or_default();
                let mut types: Vec<String> = pr
                    .section("families")
                    .and_then(|f| f.get(&fam))
                    .and_then(|f| f.get("types"))
                    .and_then(|t| t.as_obj())
                    .map(|t| t.keys().cloned().collect())
                    .unwrap_or_default();
                types.sort();
                return Some(format!(
                    "{} {}: type `{}` doesn't exist (there are: {})",
                    c,
                    id,
                    u.sub.clone().unwrap_or_default(),
                    types.join(", ")
                ));
            }
        }
    }
    if let Some(Value::Obj(ps)) = e.get("params") {
        for (k, _) in ps.iter() {
            if let Some(u) = un.get(k) {
                if u.kind == "family-parameter" {
                    return Some(format!(
                        "{} {}: `{}` isn't a parameter of {}s; add it with `parameter`",
                        c,
                        id,
                        u.sub.clone().unwrap_or_default(),
                        c
                    ));
                }
            }
        }
    }
    None
}
