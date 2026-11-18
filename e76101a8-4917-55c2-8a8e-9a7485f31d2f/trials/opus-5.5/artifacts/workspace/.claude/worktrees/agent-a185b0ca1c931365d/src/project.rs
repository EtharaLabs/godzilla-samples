//! The project: its library and its elements, held as the JSON a project file holds.

use crate::json::{Map, Value};
use std::collections::BTreeMap;

pub const FORMAT: u64 = 17;

#[derive(Clone)]
pub struct Project {
    /// Top-level keys in file order; `elements` and `library` stand in place as nulls.
    pub doc: Map,
    pub elements: BTreeMap<u64, Value>,
    pub library: BTreeMap<u64, Value>,
    /// The lowest library id handed out since the project was read: ids are never handed out twice,
    /// even once what had one is gone (an undo takes it back with the rest).
    pub lib_low: u64,
}

pub const LANGS: &[&str] = &["en", "pt", "es", "sv", "cs", "fr", "nl", "de", "it"];

fn template(lang: &str) -> &'static str {
    use crate::templates as t;
    match lang {
        "pt" => t::PT,
        "es" => t::ES,
        "sv" => t::SV,
        "cs" => t::CS,
        "fr" => t::FR,
        "nl" => t::NL,
        "de" => t::DE,
        "it" => t::IT,
        _ => t::EN,
    }
}

/// Replaces the `@G<n>` placeholders of a template with GUIDs made now, the same n the same GUID.
fn fill_guids(v: &mut Value, made: &mut Vec<Option<String>>) {
    match v {
        Value::Str(s) => {
            if let Some(n) = s.strip_prefix("@G") {
                if let Ok(n) = n.parse::<usize>() {
                    if made.len() <= n {
                        made.resize(n + 1, None);
                    }
                    if made[n].is_none() {
                        made[n] = Some(crate::rand::guid());
                    }
                    *s = made[n].clone().unwrap();
                }
            }
        }
        Value::Arr(a) => a.iter_mut().for_each(|x| fill_guids(x, made)),
        Value::Obj(m) => m.items.iter_mut().for_each(|(_, x)| fill_guids(x, made)),
        _ => {}
    }
}

pub fn new_uid() -> u64 {
    crate::rand::next_u64()
}

impl Project {
    pub fn new(lang: &str) -> Project {
        let mut v = crate::json::parse(template(lang)).expect("template");
        let mut made = Vec::new();
        fill_guids(&mut v, &mut made);
        let mut p = Project::from_value(v);
        p.doc.insert("uid", Value::u(new_uid()));
        p
    }

    pub fn from_value(v: Value) -> Project {
        let mut doc = match v {
            Value::Obj(m) => m,
            _ => Map::new(),
        };
        let mut elements = BTreeMap::new();
        let mut library = BTreeMap::new();
        if let Some(Value::Obj(m)) = doc.get_mut("elements").map(std::mem::take) {
            for (k, e) in m.items {
                if let Ok(id) = k.parse::<u64>() {
                    elements.insert(id, e);
                }
            }
        }
        if let Some(Value::Obj(m)) = doc.get_mut("library").map(std::mem::take) {
            for (k, e) in m.items {
                if let Ok(id) = k.parse::<u64>() {
                    library.insert(id, e);
                }
            }
        }
        if !doc.contains("elements") {
            doc.insert("elements", Value::Null);
        }
        if !doc.contains("library") {
            doc.insert("library", Value::Null);
        }
        Project { doc, elements, library, lib_low: 1_000_000 }
    }

    pub fn to_value(&self) -> Value {
        let mut out = Map::new();
        for (k, v) in &self.doc.items {
            if k == "elements" {
                let mut m = Map::new();
                for (id, e) in &self.elements {
                    m.items.push((id.to_string(), e.clone()));
                }
                out.items.push((k.clone(), Value::Obj(m)));
            } else if k == "library" {
                let mut m = Map::new();
                for (id, e) in &self.library {
                    m.items.push((id.to_string(), e.clone()));
                }
                out.items.push((k.clone(), Value::Obj(m)));
            } else {
                out.items.push((k.clone(), v.clone()));
            }
        }
        Value::Obj(out)
    }

    pub fn to_file_string(&self) -> String {
        self.to_value().to_pretty()
    }

    // ------------------------------------------------------------ top level

    pub fn get(&self, k: &str) -> Option<&Value> {
        self.doc.get(k)
    }
    pub fn get_mut(&mut self, k: &str) -> Option<&mut Value> {
        self.doc.get_mut(k)
    }
    pub fn name(&self) -> String {
        self.doc.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string()
    }
    pub fn language(&self) -> String {
        self.doc.get("language").and_then(|v| v.as_str()).unwrap_or("en").to_string()
    }
    /// A section of the file (`types`, `materials`…), made where the canonical order puts it.
    pub fn section_mut(&mut self, k: &str) -> &mut Map {
        if !self.doc.contains(k) {
            self.insert_top(k, Value::obj());
        }
        let v = self.doc.get_mut(k).unwrap();
        if !matches!(v, Value::Obj(_)) {
            *v = Value::obj();
        }
        v.as_obj_mut().unwrap()
    }
    pub fn section(&self, k: &str) -> Option<&Map> {
        self.doc.get(k).and_then(|v| v.as_obj())
    }
    /// Inserts a top-level key at its place in the file's order.
    pub fn insert_top(&mut self, k: &str, v: Value) {
        if self.doc.contains(k) {
            self.doc.insert(k, v);
            return;
        }
        let order = TOP_ORDER;
        let rank = |key: &str| order.iter().position(|o| *o == key).unwrap_or(usize::MAX);
        let r = rank(k);
        let pos = self.doc.items.iter().position(|(kk, _)| rank(kk) > r).unwrap_or(self.doc.items.len());
        self.doc.items.insert(pos, (k.to_string(), v));
    }
    pub fn remove_top(&mut self, k: &str) {
        self.doc.remove(k);
    }

    // ------------------------------------------------------------ ids

    pub fn next_id(&self) -> u64 {
        self.doc.get("next_id").and_then(|v| v.as_u64()).unwrap_or(100000)
    }
    pub fn alloc_id(&mut self) -> u64 {
        let mut id = self.next_id();
        while self.elements.contains_key(&id) {
            id += 1;
        }
        self.doc.insert("next_id", Value::u(id + 1));
        id
    }

    /// The lowest id the library and its parts use.
    pub fn lowest_lib_id(&self) -> u64 {
        let mut low = 1_000_000u64;
        if let Some(k) = self.library.keys().next() {
            low = low.min(*k);
        }
        fn scan(v: &Value, low: &mut u64) {
            match v {
                Value::Obj(m) => {
                    if let Some(Value::Num(n)) = m.get("id") {
                        let x = n.as_f64();
                        if x >= 900000.0 && x < 1_000_000.0 {
                            *low = (*low).min(x as u64);
                        }
                    }
                    for (_, x) in &m.items {
                        scan(x, low);
                    }
                }
                Value::Arr(a) => a.iter().for_each(|x| scan(x, low)),
                _ => {}
            }
        }
        for (k, v) in &self.doc.items {
            if k != "elements" && k != "library" {
                scan(v, &mut low);
            }
        }
        low
    }
    pub fn alloc_lib_id(&mut self) -> u64 {
        let id = self.lowest_lib_id().min(self.lib_low) - 1;
        self.lib_low = id;
        id
    }

    // ------------------------------------------------------------ elements

    pub fn el(&self, id: u64) -> Option<&Value> {
        self.elements.get(&id)
    }
    pub fn el_mut(&mut self, id: u64) -> Option<&mut Value> {
        self.elements.get_mut(&id)
    }
    pub fn category(&self, id: u64) -> Option<&str> {
        self.elements.get(&id).and_then(|e| e.get("category")).and_then(|c| c.as_str())
    }
    pub fn guid_of(&self, id: u64) -> Option<String> {
        self.elements.get(&id).and_then(|e| e.get("guid")).and_then(|g| g.as_str()).map(|s| s.to_string())
    }
    pub fn find_guid(&self, g: &str) -> Option<u64> {
        self.elements
            .iter()
            .find(|(_, e)| e.get("guid").and_then(|x| x.as_str()) == Some(g))
            .map(|(id, _)| *id)
    }
    pub fn ids_of(&self, cat: &str) -> Vec<u64> {
        self.elements
            .iter()
            .filter(|(_, e)| e.get("category").and_then(|c| c.as_str()) == Some(cat))
            .map(|(id, _)| *id)
            .collect()
    }

    // ------------------------------------------------------------ library

    pub fn lib_find_guid(&self, g: &str) -> Option<u64> {
        self.library
            .iter()
            .find(|(_, e)| e.get("guid").and_then(|x| x.as_str()) == Some(g))
            .map(|(id, _)| *id)
    }
    pub fn lib_find(&self, kind: &str, name: &str) -> Option<u64> {
        self.library
            .iter()
            .find(|(_, e)| {
                e.get("kind").and_then(|x| x.as_str()) == Some(kind) && e.get("name").and_then(|x| x.as_str()) == Some(name)
            })
            .map(|(id, _)| *id)
    }
    pub fn lib_guid(&self, kind: &str, name: &str) -> Option<String> {
        let id = self.lib_find(kind, name)?;
        self.library.get(&id).and_then(|e| e.get("guid")).and_then(|g| g.as_str()).map(|s| s.to_string())
    }
    /// The name of the library entry with this GUID.
    pub fn lib_name(&self, g: &str) -> Option<String> {
        let id = self.lib_find_guid(g)?;
        self.library.get(&id).and_then(|e| e.get("name")).and_then(|g| g.as_str()).map(|s| s.to_string())
    }
    pub fn lib_add(&mut self, kind: &str, name: &str) -> (u64, String) {
        let id = self.alloc_lib_id();
        let g = crate::rand::guid();
        self.library.insert(id, crate::jobj! {"kind" => kind, "name" => name, "guid" => g.clone()});
        (id, g)
    }
}

/// The order of a project file's top-level keys.
pub const TOP_ORDER: &[&str] = &[
    "format",
    "name",
    "uid",
    "units",
    "language",
    "room_area",
    "next_id",
    "types",
    "materials",
    "images",
    "clouds",
    "cads",
    "families",
    "parameters",
    "view_filters",
    "view_templates",
    "phases",
    "phase_filters",
    "phase_overrides",
    "option_sets",
    "line_weights",
    "standard",
    "object_styles",
    "line_patterns",
    "line_styles",
    "fill_patterns",
    "region_types",
    "text_types",
    "dimension_types",
    "detail_groups",
    "reinforcement",
    "voltages",
    "distribution_systems",
    "wire_types",
    "links",
    "elements",
    "library",
];
