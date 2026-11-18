//! The types as `inspect` shows them: each category's, as the project holds them, with their
//! layers' and runs' materials by name.

use super::names;
use crate::json::{Map, Value};
use crate::project::Project;

pub fn types(pr: &Project) -> Value {
    let mut out = Map::new();
    let Some(t) = pr.section("types") else {
        return Value::Obj(out);
    };
    for (cat, ts) in t.iter() {
        if cat == "runs" {
            let mut runs = Map::new();
            if let Some(rs) = ts.as_obj() {
                for (rcat, rts) in rs.iter() {
                    runs.insert(rcat, category(pr, rts));
                }
            }
            out.insert(cat, Value::Obj(runs));
        } else {
            out.insert(cat, category(pr, ts));
        }
    }
    Value::Obj(out).sorted()
}

fn category(pr: &Project, ts: &Value) -> Value {
    let mut out = Map::new();
    if let Some(m) = ts.as_obj() {
        for (name, def) in m.iter() {
            out.insert(name, one(pr, def));
        }
    }
    Value::Obj(out)
}

fn material(pr: &Project, v: &mut Value) {
    if let Some(g) = v.get("material").and_then(|m| m.as_str()).map(|s| s.to_string()) {
        if let Some(n) = names::lib(pr, "material", &g) {
            v.set("material", Value::Str(n));
        }
    }
}

fn one(pr: &Project, def: &Value) -> Value {
    let mut d = def.clone();
    material(pr, &mut d);
    if let Some(layers) = d.get_mut("layers").and_then(|l| l.as_arr_mut()) {
        for l in layers.iter_mut() {
            material(pr, l);
        }
    }
    d
}
