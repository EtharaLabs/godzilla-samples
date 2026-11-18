//! Reading the model: `inspect` and `elements`.

use crate::json::{Map, Value};
use crate::session::Session;

pub fn inspect(s: &Session) -> Value {
    let pr = &s.project;
    let mut m = Map::new();
    let mut counts = Map::new();
    for e in pr.elements.values() {
        let c = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        let n = counts.get(&c).and_then(|v| v.as_u64()).unwrap_or(0);
        counts.insert(&c, Value::u(n + 1));
    }
    m.insert("counts", Value::Obj(counts));
    m.insert("history", s.history().into());
    m.insert("language", pr.language().into());
    m.insert("name", pr.name().into());
    let levels: Vec<Value> = crate::commands::basic::level_ids_sorted(pr)
        .iter()
        .map(|id| {
            let e = pr.el(*id).unwrap();
            jobj! {"elevation" => e.get("elevation").cloned().unwrap_or(Value::Null), "id" => *id, "name" => e.get("name").cloned().unwrap_or(Value::Null)}
        })
        .collect();
    m.insert("levels", Value::Arr(levels));
    for (k, v) in crate::styles::inspect_entries(s) {
        m.insert(&k, v);
    }
    Value::Obj(m)
}

pub fn elements(s: &Session, p: &Value) -> Result<Value, String> {
    let pr = &s.project;
    let cat = p.get("category").and_then(|c| c.as_str()).map(|c| c.to_string());
    let mut out = Vec::new();
    for (id, e) in &pr.elements {
        let c = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        if let Some(want) = &cat {
            if c != want {
                continue;
            }
        }
        let mut x = e.clone();
        x.set("id", Value::u(*id));
        if c == "level" {
            x.set("computation_height", Value::f(1200.0));
        }
        if c == "pointcloud" {
            crate::cloud::element_view(pr, &mut x);
        }
        if c == "link" {
            crate::edit::link::element_view(pr, &mut x);
        }
        out.push(x);
    }
    let n = out.len();
    Ok(jobj! {"count" => n, "elements" => Value::Arr(out), "returned" => n})
}
