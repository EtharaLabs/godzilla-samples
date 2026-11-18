//! The families as `inspect` lists them: each its category, its connectors (kind and system), its
//! parameters' names and its types' names.

use crate::json::{Map, Value};
use crate::project::Project;

pub fn families(pr: &Project) -> Value {
    let mut out = Map::new();
    let Some(fs) = pr.section("families") else {
        return Value::Obj(out);
    };
    for (name, f) in fs.iter() {
        out.insert(name, one(f));
    }
    Value::Obj(out).sorted()
}

fn one(f: &Value) -> Value {
    let category = f.get("category").cloned().unwrap_or(Value::Null);
    let connectors: Vec<Value> = f
        .get("connectors")
        .and_then(|c| c.as_arr())
        .map(|cs| {
            cs.iter()
                .map(|c| {
                    jobj! {
                        "kind" => c.get("kind").cloned().unwrap_or(Value::Null),
                        "system" => c.get("system").cloned().unwrap_or(Value::Null)
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    let parameters: Vec<Value> = f
        .get("parameters")
        .and_then(|p| p.as_arr())
        .map(|ps| ps.iter().map(|p| p.get("name").cloned().unwrap_or(Value::Null)).collect())
        .unwrap_or_default();
    let mut types: Vec<String> = f.get("types").and_then(|t| t.as_obj()).map(|t| t.keys().cloned().collect()).unwrap_or_default();
    types.sort();
    jobj! {
        "category" => category,
        "connectors" => Value::Arr(connectors),
        "parameters" => Value::Arr(parameters),
        "types" => types
    }
}
