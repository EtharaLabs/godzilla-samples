//! What the original fills in for a section a file leaves out: what an English project starts
//! with (whatever the file's language), naming what it names by name.

use super::refs::{self, Resolve};
use crate::json::{Map, Value};
use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;

struct Template {
    doc: Map,
}

/// A template's `@Gn` placeholders read as the names its library gives them.
struct Placeholders(HashMap<(String, String), String>);

impl Resolve for Placeholders {
    fn map(&mut self, kind: &str, whose: Option<&str>, s: &str) -> String {
        match self.0.get(&(kind.to_string(), s.to_string())) {
            Some(n) => match whose.and_then(|w| n.strip_prefix(&format!("{}: ", w))) {
                Some(rest) => rest.to_string(),
                None => n.clone(),
            },
            None => s.to_string(),
        }
    }
}

fn template() -> &'static Template {
    static T: OnceLock<Template> = OnceLock::new();
    T.get_or_init(|| {
        let v = crate::json::parse(crate::templates::EN).expect("template");
        let mut doc = match v {
            Value::Obj(m) => m,
            _ => Map::new(),
        };
        let mut lib = HashMap::new();
        if let Some(Value::Obj(l)) = doc.get("library") {
            for (_, e) in &l.items {
                let kind = e.get("kind").and_then(|x| x.as_str()).unwrap_or("").to_string();
                let name = e.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string();
                let guid = e.get("guid").and_then(|x| x.as_str()).unwrap_or("").to_string();
                lib.insert((kind, guid), name);
            }
        }
        doc.remove("library");
        doc.remove("elements");
        let mut els = BTreeMap::new();
        refs::walk(&mut Placeholders(lib), &mut doc, &mut els);
        Template { doc }
    })
}

/// The section an English project starts with (an empty map where it starts with none).
pub fn section(name: &str) -> Value {
    template().doc.get(name).cloned().unwrap_or_else(Value::obj)
}
