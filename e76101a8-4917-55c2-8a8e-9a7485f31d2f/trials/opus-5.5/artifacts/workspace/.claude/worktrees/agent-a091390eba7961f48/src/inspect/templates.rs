//! View filters and view templates as `inspect` shows them: as the project holds them, with what
//! they point at by GUID (filters, fill patterns, phases, phase filters, design options) by name.

use super::names;
use crate::json::{Map, Value};
use crate::project::Project;

pub fn view_filters(pr: &Project) -> Value {
    let mut out = Map::new();
    if let Some(fs) = pr.section("view_filters") {
        for (name, f) in fs.iter() {
            out.insert(name, filter(pr, f));
        }
    }
    Value::Obj(out).sorted()
}

/// A view filter with its rules' project parameters, phases and design options by name (a rule
/// without a value, and a filter without rules, as the original leaves them out).
fn filter(pr: &Project, f: &Value) -> Value {
    let mut f = f.clone();
    let mut keep_rules = true;
    if let Some(Value::Arr(rules)) = f.get_mut("rules") {
        for r in rules.iter_mut() {
            rename(pr, r, "field", "parameter");
            if r.get("value").map(|v| v.is_null()).unwrap_or(false) {
                r.remove("value");
            }
            match r.get("field").and_then(|x| x.as_str()) {
                Some("Phase Created") | Some("Phase Demolished") => rename(pr, r, "value", "phase"),
                Some("Design Option") => rename(pr, r, "value", "design-option"),
                _ => {}
            }
        }
        keep_rules = !rules.is_empty();
    }
    if !keep_rules || f.get("rules").map(|r| r.is_null()).unwrap_or(false) {
        f.remove("rules");
    }
    f
}

pub fn view_templates(pr: &Project) -> Value {
    let mut out = Map::new();
    if let Some(ts) = pr.section("view_templates") {
        for (name, t) in ts.iter() {
            let mut t = t.clone();
            if let Some(g) = t.get_mut("graphics") {
                graphics(pr, g);
            }
            out.insert(name, t);
        }
    }
    Value::Obj(out).sorted()
}

/// A fill pattern's GUID in an override's foreground or background, by name.
fn patterns(pr: &Project, ov: &mut Value) {
    for part in ["projection", "cut"] {
        if let Some(st) = ov.get_mut(part) {
            for layer in ["foreground", "background"] {
                if let Some(l) = st.get_mut(layer) {
                    if let Some(g) = l.get("pattern").and_then(|p| p.as_str()).map(|s| s.to_string()) {
                        if let Some(n) = names::lib(pr, "fill-pattern", &g) {
                            l.set("pattern", Value::Str(n));
                        }
                    }
                }
            }
        }
    }
}

fn rename(pr: &Project, v: &mut Value, key: &str, kind: &str) {
    if let Some(g) = v.get(key).and_then(|p| p.as_str()).map(|s| s.to_string()) {
        if let Some(n) = names::lib(pr, kind, &g) {
            v.set(key, Value::Str(n));
        }
    }
}

/// A view's (or template's) graphics with what they hold by GUID by name.
pub fn graphics(pr: &Project, g: &mut Value) {
    if let Some(Value::Obj(cats)) = g.get_mut("categories") {
        for (_, ov) in cats.items.iter_mut() {
            patterns(pr, ov);
        }
    }
    if let Some(Value::Obj(els)) = g.get_mut("elements") {
        for (_, ov) in els.items.iter_mut() {
            patterns(pr, ov);
        }
    }
    if let Some(Value::Arr(fs)) = g.get_mut("filters") {
        for f in fs.iter_mut() {
            rename(pr, f, "filter", "view-filter");
            patterns(pr, f);
        }
    }
    rename(pr, g, "phase", "phase");
    rename(pr, g, "phase_filter", "phase-filter");
    if let Some(Value::Obj(opts)) = g.get("options").cloned() {
        let mut m = Map::new();
        for (set, opt) in opts.items {
            let set_name = names::lib(pr, "option-set", &set).unwrap_or(set);
            let opt = match opt.as_str().and_then(|o| names::option(pr, o)) {
                Some(n) => Value::Str(n),
                None => opt,
            };
            m.insert(&set_name, opt);
        }
        g.set("options", Value::Obj(m));
    }
}
